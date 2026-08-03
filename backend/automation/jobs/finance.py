"""Finance data jobs (plan.md §12) — real market-data pipeline.

Port of Quiver's EOD pipeline onto the shared feature store:
`fetch_equity` → `compute_factors` → `fetch_macro` → `update_universe` →
`paper_trade_eod`.

Live data comes from yfinance (the same source Quiver used). When yfinance is
unavailable (no network / provider block), each job degrades honestly: it
records a `degraded` run in `finance.job_runs` and logs why — it never fails
the worker, and never fabricates data. Every run is logged via `_record_run`.

Emitted events: TradeExecuted, PortfolioNAVUpdated (worker is the only Finance
writer — plan §16).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from backend.modules.db import session_factory
from backend.events.catalog import PORTFOLIO_NAV_UPDATED
from backend.modules.common import publish
from backend.db import feature_store

logger = logging.getLogger("vesper.automation.finance")


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")[:19]


async def _record_run(job: str, status: str, detail: str = "", rows: int | None = None) -> None:
    """Log a job run to finance.job_runs (the existing CronRun-style table)."""
    try:
        from sqlalchemy import text

        async with session_factory()() as db:
            await db.execute(
                text(
                    "INSERT INTO finance.job_runs "
                    "(job_name, status, started_at, finished_at, error_message, rows_processed) "
                    "VALUES (:job, :status, :started, :finished, :error, :rows)"
                ),
                {
                    "job": job,
                    "status": status,
                    "started": _now(),
                    "finished": _now(),
                    "error": detail[:500] if status in {"error", "degraded"} else None,
                    "rows": rows,
                },
            )
            await db.commit()
    except Exception as exc:  # pragma: no cover - never fail the job on logging
        logger.warning("record_run(%s) failed: %s", job, exc)


def _yf():
    """Import yfinance lazily (only needed for live fetches)."""
    import yfinance as yf

    return yf


async def fetch_equity(limit: int = 200, start: str = "2018-01-01") -> dict:
    """06:00 IST — fetch the Nifty universe from yfinance into equity_daily.

    Degrades honestly (logged run, no data) when yfinance is unreachable.
    """
    try:
        yf = _yf()
    except ImportError as exc:  # pragma: no cover
        await _record_run("fetch_equity", "degraded", f"yfinance unavailable: {exc}")
        return {"ok": True, "job": "fetch_equity", "degraded": True, "note": str(exc)}

    symbols = feature_store.universe_symbols(limit)
    if not symbols:
        await _record_run("fetch_equity", "degraded", "universe CSV missing")
        return {"ok": True, "job": "fetch_equity", "degraded": True, "note": "no universe symbols"}

    try:
        end = (datetime.now() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        df = yf.download(symbols, start=start, end=end, progress=False, auto_adjust=True, group_by="ticker", threads=True)
    except Exception as exc:  # noqa: BLE001 - any fetch failure degrades, not crashes
        await _record_run("fetch_equity", "degraded", f"yfinance download failed: {exc}")
        logger.warning("fetch_equity download failed: %s", exc)
        return {"ok": True, "job": "fetch_equity", "degraded": True, "note": str(exc)[:300]}

    if df is None or df.empty:
        await _record_run("fetch_equity", "degraded", "yfinance returned empty")
        return {"ok": True, "job": "fetch_equity", "degraded": True, "note": "empty download"}

    # yf.download with group_by='ticker' yields MultiIndex columns (ticker, field).
    rows: list[dict] = []
    for symbol in df.columns.get_level_values(0).unique():
        try:
            sub = df[symbol].dropna(subset=["Close"])
            for ts, r in sub.iterrows():
                rows.append({
                    "Date": pd.Timestamp(ts).date(),
                    "Symbol": symbol,
                    "Open": float(r.get("Open") or 0),
                    "High": float(r.get("High") or 0),
                    "Low": float(r.get("Low") or 0),
                    "Close": float(r.get("Close") or 0),
                    "Volume": int(r.get("Volume") or 0),
                })
        except Exception:  # pragma: no cover - skip a bad ticker
            continue

    if not rows:
        await _record_run("fetch_equity", "degraded", "no rows parsed")
        return {"ok": True, "job": "fetch_equity", "degraded": True, "note": "no rows parsed"}

    written = feature_store.write_equity(pd.DataFrame(rows))
    await _record_run("fetch_equity", "ok", f"persisted {written} rows across {len(symbols)} symbols", rows=written)
    logger.info("fetch_equity: %d rows persisted", written)
    return {"ok": True, "job": "fetch_equity", "rows": written, "symbols": len(symbols)}


async def compute_factors() -> dict:
    """06:30 IST — compute per-symbol factor features from equity_daily.

    Factors: 1/5/20-day returns, 6-month momentum, 20/60-day volatility,
    and the 20/200 MA ratio. Persisted to `factor_features`.
    """
    closes = feature_store.equity_closes()
    if closes.empty:
        await _record_run("compute_factors", "degraded", "feature store empty — run fetch_equity first")
        return {"ok": True, "job": "compute_factors", "degraded": True, "note": "feature store empty"}

    try:
        ret1 = closes.pct_change(1)
        ret5 = closes.pct_change(5)
        ret20 = closes.pct_change(20)
        mom6 = closes.pct_change(126)
        vol20 = closes.pct_change(1).rolling(20).std() * (252 ** 0.5)
        vol60 = closes.pct_change(1).rolling(60).std() * (252 ** 0.5)
        ma20 = closes.rolling(20).mean()
        ma200 = closes.rolling(200).mean()
        ma_ratio = (ma20 / ma200).where(ma200 != 0)

        out_rows: list[dict] = []
        for ts, idx in closes.iterrows():
            for symbol in closes.columns:
                if pd.isna(idx[symbol]):
                    continue
                out_rows.append({
                    "Date": pd.Timestamp(ts).date(),
                    "Symbol": symbol,
                    "ret_1d": _f(ret1.at[ts, symbol]),
                    "ret_5d": _f(ret5.at[ts, symbol]),
                    "ret_20d": _f(ret20.at[ts, symbol]),
                    "momentum_6m": _f(mom6.at[ts, symbol]),
                    "vol_20d": _f(vol20.at[ts, symbol]),
                    "vol_60d": _f(vol60.at[ts, symbol]),
                    "ma_ratio_20_200": _f(ma_ratio.at[ts, symbol]),
                })
        written = feature_store.write_factors(pd.DataFrame(out_rows))
        await _record_run("compute_factors", "ok", f"{written} factor rows across {len(closes.columns)} symbols", rows=written)
        return {"ok": True, "job": "compute_factors", "rows": written}
    except Exception as exc:  # pragma: no cover - never fail the batch
        await _record_run("compute_factors", "error", str(exc)[:300])
        logger.error("compute_factors failed: %s", exc)
        return {"ok": False, "job": "compute_factors", "error": str(exc)}


async def fetch_macro() -> dict:
    """07:00 IST — fetch macro closes (Nifty, VIX, USD/INR, crude, etc.)."""
    try:
        yf = _yf()
    except ImportError as exc:  # pragma: no cover
        await _record_run("fetch_macro", "degraded", f"yfinance unavailable: {exc}")
        return {"ok": True, "job": "fetch_macro", "degraded": True, "note": str(exc)}

    rows: list[dict] = []
    for name, sym in feature_store.MACRO_TICKERS.items():
        try:
            df = yf.download(sym, period="1y", progress=False, auto_adjust=True)
        except Exception:  # pragma: no cover - resilient per-ticker
            continue
        if df is None or df.empty:
            continue
        # yfinance may return MultiIndex columns even for a single symbol;
        # flatten to a single level keyed on the field name.
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = [c[0] for c in df.columns]
        if "Close" not in df.columns:
            continue
        for ts, r in df.iterrows():
            rows.append({
                "Date": pd.Timestamp(ts).date(),
                "Series": name,
                "Close": float(r["Close"] or 0),
            })

    if not rows:
        await _record_run("fetch_macro", "degraded", "no macro series fetched")
        return {"ok": True, "job": "fetch_macro", "degraded": True, "note": "no macro data"}

    written = feature_store.write_macro(pd.DataFrame(rows))
    await _record_run("fetch_macro", "ok", f"{written} macro rows across {len(feature_store.MACRO_TICKERS)} series", rows=written)
    return {"ok": True, "job": "fetch_macro", "rows": written}


async def update_universe() -> dict:
    """07:30 IST — refresh index_membership from the bundled Nifty CSV."""
    symbols = feature_store.universe_symbols()
    if not symbols:
        await _record_run("update_universe", "degraded", "universe CSV missing")
        return {"ok": True, "job": "update_universe", "degraded": True, "note": "no universe"}
    written = feature_store.upsert_membership(symbols)
    await _record_run("update_universe", "ok", f"{written} membership rows refreshed", rows=written)
    return {"ok": True, "job": "update_universe", "symbols": written}


async def paper_trade_eod() -> dict:
    """17:00 IST weekdays — end-of-day paper trading for all 5 traders.

    Runs the full EOD engine (`backend.modules.finance.eod.run_eod`): generate
    targets per strategy from the factor store, execute orders against cash,
    update holdings/trades/NAV, and emit TradeExecuted / PortfolioNAVUpdated.
    """
    from backend.modules.finance.eod import run_eod

    res = await run_eod()
    if not res.get("ok"):
        await _record_run("paper_trade_eod", "degraded", res.get("note", "") or res.get("error", ""))
        return res
    n_traders = len(res.get("traders", []))
    n_trades = res.get("trades", 0)
    await _record_run("paper_trade_eod", "ok", f"{n_traders} traders, {n_trades} trades executed")
    res["accounts"] = n_traders
    return res


def _f(v) -> float | None:
    """Round a float to 6dp, NaN → None."""
    if v is None or pd.isna(v):
        return None
    return round(float(v), 6)


ALL_JOBS = {
    "fetch_equity": fetch_equity,
    "compute_factors": compute_factors,
    "fetch_macro": fetch_macro,
    "update_universe": update_universe,
    "paper_trade_eod": paper_trade_eod,
}
