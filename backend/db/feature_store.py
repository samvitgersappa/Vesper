"""Finance feature store (plan.md §13) — DuckDB-backed price/factor persistence.

The Finance data pipeline fetches live market data (yfinance) and persists it
here as analytical tables — the same DuckDB/Parquet feature-store model Quiver
used, re-implemented for the monolith. Tables:

- `equity_daily`    long-format OHLCV for the tradable universe
- `macro_series`    long-format close prices for macro tickers
- `factor_features` per-symbol factor values computed from equity_daily
- `index_membership` Nifty membership intervals (from ind_nifty500list.csv)
- `symbol_mapping`  old→new symbol remaps

All writes go through the read-write `DuckDBClient`; reads use the shared
read-only client. Created lazily on first write (`CREATE TABLE IF NOT EXISTS`),
so an empty-but-ready feature store exists even before the first fetch.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import pandas as pd

from backend.db.duckdb_client import client

logger = logging.getLogger("vesper.finance.store")

_UNIVERSE_CSV = Path(__file__).resolve().parent.parent / "data" / "raw" / "ind_nifty500list.csv"

_SCHEMA = {
    "equity_daily": """
        CREATE TABLE IF NOT EXISTS equity_daily (
            Date DATE,
            Symbol VARCHAR,
            Open DOUBLE,
            High DOUBLE,
            Low DOUBLE,
            Close DOUBLE,
            Volume BIGINT
        )
    """,
    "macro_series": """
        CREATE TABLE IF NOT EXISTS macro_series (
            Date DATE,
            Series VARCHAR,
            Close DOUBLE
        )
    """,
    "factor_features": """
        CREATE TABLE IF NOT EXISTS factor_features (
            Date DATE,
            Symbol VARCHAR,
            ret_1d DOUBLE,
            ret_5d DOUBLE,
            ret_20d DOUBLE,
            momentum_6m DOUBLE,
            vol_20d DOUBLE,
            vol_60d DOUBLE,
            ma_ratio_20_200 DOUBLE
        )
    """,
    "index_membership": """
        CREATE TABLE IF NOT EXISTS index_membership (
            symbol VARCHAR,
            index_name VARCHAR,
            effective_from DATE,
            effective_to DATE
        )
    """,
    "symbol_mapping": """
        CREATE TABLE IF NOT EXISTS symbol_mapping (
            old_symbol VARCHAR,
            new_symbol VARCHAR,
            effective_date DATE
        )
    """,
}


def ensure_schema() -> None:
    """Create all feature-store tables if they don't exist (idempotent)."""
    for name, ddl in _SCHEMA.items():
        try:
            client.execute(ddl)
        except Exception as exc:  # pragma: no cover - read-only lock race
            logger.warning("ensure_schema(%s) failed: %s", name, exc)


def universe_symbols(limit: int | None = None) -> list[str]:
    """Nifty membership symbols from the bundled CSV (ticker-suffix aware)."""
    if not _UNIVERSE_CSV.exists():
        return []
    df = pd.read_csv(_UNIVERSE_CSV)
    syms = [str(s).strip() for s in df["Symbol"].tolist() if str(s).strip()]
    out = []
    for s in syms:
        if s in {"NIFTY", "BANKNIFTY", "FINNIFTY"}:
            continue
        if s.isdigit() and len(s) == 3:  # noqa: PLR2004 - weird 3-digit entries
            continue
        out.append(f"{s}.NS")
    return out[:limit] if limit else out


# ── Macro ticker map: internal name → yfinance symbol ─────────────────────
MACRO_TICKERS = {
    "nifty50": "^NSEI",
    "bank_nifty": "^NSEBANK",
    "nifty_it": "^CNXIT",
    "nasdaq": "^IXIC",
    "brent": "BZ=F",
    "usdinr": "USDINR=X",
    "india_vix": "^INDIAVIX",
    "gold": "GC=F",
}


def write_equity(df: pd.DataFrame) -> int:
    """Upsert long-format equity OHLCV into equity_daily. Returns rows written.

    Replaces only the symbols present in the frame (re-run safe — a full
    history fetch overwrites those symbols; unrelated symbols are untouched).
    """
    if df is None or df.empty:
        return 0
    df = df.rename(columns={"Ticker": "Symbol"})
    cols = ["Date", "Symbol", "Open", "High", "Low", "Close", "Volume"]
    cols = [c for c in cols if c in df.columns]
    sub = df[cols].copy()
    sub["Date"] = pd.to_datetime(sub["Date"]).dt.date
    sub = sub.drop_duplicates(subset=["Date", "Symbol"], keep="last")
    ensure_schema()
    with client.session() as conn:
        conn.register("_equity_upsert", sub)
        conn.execute(
            "DELETE FROM equity_daily WHERE Symbol IN (SELECT DISTINCT Symbol FROM _equity_upsert)"
        )
        conn.execute("INSERT INTO equity_daily SELECT * FROM _equity_upsert")
    return len(sub)


def write_macro(df: pd.DataFrame) -> int:
    """Persist macro closes (replaces the affected series — re-run safe)."""
    if df is None or df.empty:
        return 0
    sub = df[["Date", "Series", "Close"]].copy()
    sub["Date"] = pd.to_datetime(sub["Date"]).dt.date
    sub = sub.drop_duplicates(subset=["Date", "Series"], keep="last")
    ensure_schema()
    with client.session() as conn:
        conn.register("_macro_upsert", sub)
        conn.execute(
            "DELETE FROM macro_series WHERE Series IN (SELECT DISTINCT Series FROM _macro_upsert)"
        )
        conn.execute("INSERT INTO macro_series SELECT * FROM _macro_upsert")
    return len(sub)


def write_factors(df: pd.DataFrame) -> int:
    """Replace factor_features with the freshly computed factor frame."""
    if df is None or df.empty:
        return 0
    ensure_schema()
    with client.session() as conn:
        conn.execute("DELETE FROM factor_features")
        conn.register("_factor_upsert", df)
        conn.execute("INSERT INTO factor_features SELECT * FROM _factor_upsert")
    return len(df)


def upsert_membership(symbols: list[str], index_name: str = "Nifty 500") -> int:
    """Refresh index_membership for the current universe."""
    ensure_schema()
    today = date.today()
    rows = [(s, index_name, today, None) for s in symbols]
    with client.session() as conn:
        conn.execute("DELETE FROM index_membership WHERE index_name = $i", {"i": index_name})
        conn.register("_memb_upsert", pd.DataFrame(rows, columns=["symbol", "index_name", "effective_from", "effective_to"]))
        conn.execute("INSERT INTO index_membership SELECT * FROM _memb_upsert")
    return len(rows)


def equity_closes(symbol: str | None = None, since: str | None = None) -> pd.DataFrame:
    """Read long-format equity closes (wide pivot) from the feature store."""
    # Use the shared read-write client for in-process reads (the read-only
    # client is for a *separate* API process; DuckDB forbids two configs on the
    # same file in one process).
    ro = client
    where = ""
    params: dict = {}
    if symbol:
        where = "WHERE Symbol = $s"
        params["s"] = symbol
    elif since:
        where = "WHERE Date >= $d"
        params["d"] = since
    q = f"SELECT Date, Symbol, Close FROM equity_daily {where} ORDER BY Date"
    try:
        df = ro.df(q, params)
    except Exception:
        return pd.DataFrame(columns=["Date", "Symbol", "Close"])
    if df.empty:
        return df
    wide = df.pivot(index="Date", columns="Symbol", values="Close").sort_index()
    return wide
