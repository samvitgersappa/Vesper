"""Catalyst Swing Trader — data acquisition (Part E).

Per the Trader 6 Data Acquisition Guide:

- Bhavcopy (18:00 IST)  -> delivery_stats          (NSE Common Bhavcopy)
- FII/DII (18:05)       -> market_sentiment_daily  (NSE provisional stats)
- Index PCR (18:07)     -> index_options_sentiment (NSE index option chain)
- Sector (18:10)        -> sector_scores_daily     (yfinance sector indices)
- Breadth (18:15)       -> market_breadth_daily    (computed from equity_daily)

Failure policy: every external fetch retries 3 times, then records a
`degraded` run in finance.job_runs. The pipeline never aborts and never
fabricates data. NSE endpoints need a session cookie (homepage handshake).
"""

import io
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
import pandas as pd

from backend.db import feature_store
from backend.modules.db import session_factory
from backend.modules.finance.catalyst import SECTOR_TICKERS
from backend.modules.finance.catalyst._util import record_run

logger = logging.getLogger("vesper.finance.catalyst.sources")

RETRIES = 3
TIMEOUT = 20

NSE_BHAVCOPY_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
NSE_FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
NSE_OPTION_CHAIN_URL = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _client() -> httpx.Client:
    """httpx client that performs the NSE homepage cookie handshake."""
    c = httpx.Client(headers=_HEADERS, timeout=TIMEOUT, follow_redirects=True)
    try:
        c.get("https://www.nseindia.com", timeout=TIMEOUT)
    except Exception:  # pragma: no cover - handshake failure degrades later
        pass
    return c


def _get(url: str, *, session: Optional[httpx.Client] = None, text: bool = False) -> Any:
    """GET with 3 retries (NSE throttling / flake). Returns parsed body or None."""
    own = session is None
    client = session or _client()
    try:
        for attempt in range(1, RETRIES + 1):
            try:
                resp = client.get(url, timeout=TIMEOUT)
                if resp.status_code in (200, 301, 302):
                    return resp.text if text else resp.json()
            except Exception as exc:  # noqa: BLE001 - retry on any transport error
                logger.warning("GET %s attempt %d failed: %s", url, attempt, exc)
            time.sleep(1.5 * attempt)
    finally:
        if own:
            client.close()
    return None


# ── 1. Bhavcopy / delivery ──────────────────────────────────────────────
async def fetch_bhavcopy(today: str | None = None) -> dict:
    """18:00 IST — NSE Common Bhavcopy delivery data into delivery_stats."""
    date = today or datetime.now().strftime("%Y%m%d")
    url = NSE_BHAVCOPY_URL.format(date=date)
    csv_text = _get(url, text=True)
    if not csv_text:
        await record_run("fetch_bhavcopy", "degraded", f"bhavcopy unreachable after {RETRIES} retries")
        return {"ok": True, "job": "fetch_bhavcopy", "degraded": True, "note": "unreachable"}

    try:
        df = pd.read_csv(io.StringIO(csv_text))
    except Exception as exc:  # pragma: no cover - malformed CSV degrades
        await record_run("fetch_bhavcopy", "degraded", f"bhavcopy parse failed: {exc}")
        return {"ok": True, "job": "fetch_bhavcopy", "degraded": True, "note": str(exc)[:200]}

    expected = {"SYMBOL", "TOTTRDQTY", "TOTTRDVAL"}
    if not expected.issubset(df.columns):
        await record_run("fetch_bhavcopy", "degraded", f"bhavcopy missing columns: {sorted(set(expected) - set(df.columns))}")
        return {"ok": True, "job": "fetch_bhavcopy", "degraded": True, "note": "missing columns"}

    rows = []
    iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    for _, r in df.iterrows():
        sym = str(r["SYMBOL"]).strip()
        if not sym:
            continue
        total_qty = _as_int(r.get("TOTTRDQTY"))
        delivery_qty = _as_int(r.get("DELIV_QTY"))
        delivery_pct = _as_float(r.get("DELIV_PER"))
        if delivery_pct is None and total_qty and delivery_qty:
            delivery_pct = round(delivery_qty / total_qty * 100.0, 2)
        rows.append({
            "date": iso,
            "symbol": f"{sym}.NS",
            "total_qty": total_qty,
            "total_val": _as_float(r.get("TOTTRDVAL")),
            "delivery_qty": delivery_qty,
            "delivery_pct": delivery_pct,
        })

    if not rows:
        await record_run("fetch_bhavcopy", "degraded", "bhavcopy empty")
        return {"ok": True, "job": "fetch_bhavcopy", "degraded": True, "note": "empty"}

    await _upsert_delivery(rows)
    n_deliv = sum(1 for x in rows if x["delivery_pct"] is not None)
    await record_run("fetch_bhavcopy", "ok", f"{len(rows)} rows, delivery% populated for {n_deliv}", rows=len(rows))
    return {"ok": True, "job": "fetch_bhavcopy", "rows": len(rows), "delivery_pct_populated": n_deliv}


async def _upsert_delivery(rows: list[dict]) -> None:
    from sqlalchemy import text

    async with session_factory()() as db:
        for r in rows:
            await db.execute(
                text(
                    "INSERT INTO finance.delivery_stats "
                    "(date, symbol, total_qty, total_val, delivery_qty, delivery_pct) "
                    "VALUES (:d, :s, :tq, :tv, :dq, :dp) "
                    "ON CONFLICT (date, symbol) DO UPDATE SET "
                    "total_qty = EXCLUDED.total_qty, total_val = EXCLUDED.total_val, "
                    "delivery_qty = EXCLUDED.delivery_qty, delivery_pct = EXCLUDED.delivery_pct"
                ),
                {
                    "d": r["date"], "s": r["symbol"], "tq": r["total_qty"],
                    "tv": r["total_val"], "dq": r["delivery_qty"], "dp": r["delivery_pct"],
                },
            )
        await db.commit()


# ── 2. FII/DII ───────────────────────────────────────────────────────────
async def fetch_fii_dii(today: str | None = None) -> dict:
    """18:05 IST — NSE provisional FII/DII net flows into market_sentiment_daily."""
    date = today or datetime.now().strftime("%Y-%m-%d")
    session = _client()
    try:
        data = _get(NSE_FII_DII_URL, session=session)
    finally:
        session.close()
    if not data:
        await record_run("fetch_fii_dii", "degraded", f"FII/DII unreachable after {RETRIES} retries")
        return {"ok": True, "job": "fetch_fii_dii", "degraded": True, "note": "unreachable"}

    rows = _parse_fii_dii(data, date)
    if not rows:
        await record_run("fetch_fii_dii", "degraded", "FII/DII payload had no parseable rows")
        return {"ok": True, "job": "fetch_fii_dii", "degraded": True, "note": "no parseable rows"}

    from sqlalchemy import text

    async with session_factory()() as db:
        for r in rows:
            await db.execute(
                text(
                    "INSERT INTO finance.market_sentiment_daily (date, actor, buy, sell, net) "
                    "VALUES (:d, :a, :b, :s, :n) "
                    "ON CONFLICT (date, actor) DO UPDATE SET "
                    "buy = EXCLUDED.buy, sell = EXCLUDED.sell, net = EXCLUDED.net"
                ),
                {"d": date, "a": r["actor"], "b": r["buy"], "s": r["sell"], "n": r["net"]},
            )
        await db.commit()

    await record_run("fetch_fii_dii", "ok", f"{len(rows)} actors", rows=len(rows))
    return {"ok": True, "job": "fetch_fii_dii", "rows": len(rows)}


def _parse_fii_dii(data: Any, date: str) -> list[dict]:
    """Parse the NSE fiidiiTradeReact JSON into (actor, buy, sell, net) rows.

    Defensive: accepts both the raw dict with 'FII'/'DII' keys and a
    'data' list form. Returns [] when nothing parseable.
    """
    out: list[dict] = []
    raw = data.get("data") if isinstance(data, dict) else data
    if isinstance(raw, dict):
        for actor in ("FII", "DII"):
            rec = raw.get(actor) or {}
            buy = _as_float(rec.get("buyValue") or rec.get("buy"))
            sell = _as_float(rec.get("sellValue") or rec.get("sell"))
            net = _as_float(rec.get("netValue") or rec.get("net"))
            if buy is None and sell is None and net is None:
                continue
            out.append({"actor": actor, "buy": buy, "sell": sell, "net": net})
    elif isinstance(raw, list):
        for rec in raw:
            actor = str(rec.get("category") or rec.get("name") or "").strip().upper()
            if actor not in {"FII", "DII"}:
                continue
            out.append({
                "actor": actor,
                "buy": _as_float(rec.get("buyValue") or rec.get("buy")),
                "sell": _as_float(rec.get("sellValue") or rec.get("sell")),
                "net": _as_float(rec.get("netValue") or rec.get("net")),
            })
    return out


# ── 3. Index PCR ─────────────────────────────────────────────────────────
async def fetch_index_pcr(today: str | None = None) -> dict:
    """18:07 IST — Nifty/BankNifty index option-chain PCR into index_options_sentiment."""
    date = today or datetime.now().strftime("%Y-%m-%d")
    session = _client()
    try:
        rows: list[dict] = []
        for idx in ("NIFTY", "BANKNIFTY"):
            data = _get(NSE_OPTION_CHAIN_URL.format(symbol=idx), session=session)
            parsed = _parse_option_chain(data)
            if parsed:
                rows.append({"index_name": idx, **parsed})
    finally:
        session.close()

    if not rows:
        await record_run("fetch_index_pcr", "degraded", f"option chain unreachable after {RETRIES} retries")
        return {"ok": True, "job": "fetch_index_pcr", "degraded": True, "note": "unreachable"}

    from sqlalchemy import text

    async with session_factory()() as db:
        for r in rows:
            await db.execute(
                text(
                    "INSERT INTO finance.index_options_sentiment (date, index_name, pcr, ce_oi, pe_oi) "
                    "VALUES (:d, :i, :pcr, :ce, :pe) "
                    "ON CONFLICT (date, index_name) DO UPDATE SET "
                    "pcr = EXCLUDED.pcr, ce_oi = EXCLUDED.ce_oi, pe_oi = EXCLUDED.pe_oi"
                ),
                {"d": date, "i": r["index_name"], "pcr": r["pcr"], "ce": r["ce_oi"], "pe": r["pe_oi"]},
            )
        await db.commit()

    await record_run("fetch_index_pcr", "ok", f"{len(rows)} indices", rows=len(rows))
    return {"ok": True, "job": "fetch_index_pcr", "rows": len(rows)}


def _parse_option_chain(data: Any) -> Optional[dict]:
    """Aggregate total PE/CE OI from an NSE option-chain payload → PCR."""
    if not data or not isinstance(data, dict):
        return None
    records = (data.get("filtered") or {}).get("data")
    if not isinstance(records, list) or not records:
        return None
    ce_oi = 0.0
    pe_oi = 0.0
    for rec in records:
        ce = rec.get("CE") or {}
        pe = rec.get("PE") or {}
        ce_oi += _as_float(ce.get("openInterest")) or 0.0
        pe_oi += _as_float(pe.get("openInterest")) or 0.0
    if ce_oi <= 0:
        return None
    return {"pcr": round(pe_oi / ce_oi, 4), "ce_oi": round(ce_oi, 2), "pe_oi": round(pe_oi, 2)}


# ── 4. Sector indices ────────────────────────────────────────────────────
async def fetch_sector_indices(today: str | None = None) -> dict:
    """18:10 IST — yfinance sector indices → 20D return, 50DMA, momentum, score."""
    date = today or datetime.now().strftime("%Y-%m-%d")
    try:
        import yfinance as yf  # noqa: PLC0415 - lazy, network
    except ImportError as exc:  # pragma: no cover
        await record_run("fetch_sector_indices", "degraded", f"yfinance unavailable: {exc}")
        return {"ok": True, "job": "fetch_sector_indices", "degraded": True, "note": str(exc)}

    symbols = list(SECTOR_TICKERS.values())
    rows: list[dict] = []
    try:
        hist = yf.download(symbols, period="1y", progress=False, auto_adjust=True, group_by="ticker")
    except Exception as exc:  # noqa: BLE001 - provider flake degrades
        await record_run("fetch_sector_indices", "degraded", f"sector download failed: {exc}")
        return {"ok": True, "job": "fetch_sector_indices", "degraded": True, "note": str(exc)[:200]}
    if hist is None or hist.empty:
        await record_run("fetch_sector_indices", "degraded", "sector download empty")
        return {"ok": True, "job": "fetch_sector_indices", "degraded": True, "note": "empty"}

    name_by_sym = {v: k for k, v in SECTOR_TICKERS.items()}
    for sym in symbols:
        try:
            closes = hist[sym]["Close"].dropna()
        except Exception:  # pragma: no cover - missing sector ticker
            continue
        if len(closes) < 50:
            continue
        ret_20d = float(closes.iloc[-1]) / float(closes.iloc[-20]) - 1.0 if len(closes) >= 20 else None
        dma_50 = float(closes.iloc[-1]) / float(closes.iloc[-50:].mean()) if len(closes) >= 50 else None
        momentum = float(closes.iloc[-1]) / float(closes.iloc[-63]) - 1.0 if len(closes) >= 63 else ret_20d
        rows.append({
            "date": date,
            "sector": name_by_sym[sym],
            "ret_20d": _r(ret_20d),
            "dma_50": _r(dma_50),
            "momentum": _r(momentum),
        })

    if not rows:
        await record_run("fetch_sector_indices", "degraded", "no sector series parsed")
        return {"ok": True, "job": "fetch_sector_indices", "degraded": True, "note": "no rows"}

    scores = _sector_scores(rows)
    from sqlalchemy import text

    async with session_factory()() as db:
        for r in rows:
            await db.execute(
                text(
                    "INSERT INTO finance.sector_scores_daily (date, sector, ret_20d, dma_50, momentum, score) "
                    "VALUES (:d, :s, :r20, :dma, :mom, :score) "
                    "ON CONFLICT (date, sector) DO UPDATE SET "
                    "ret_20d = EXCLUDED.ret_20d, dma_50 = EXCLUDED.dma_50, "
                    "momentum = EXCLUDED.momentum, score = EXCLUDED.score"
                ),
                {
                    "d": date, "s": r["sector"], "r20": r["ret_20d"],
                    "dma": r["dma_50"], "mom": r["momentum"], "score": scores.get(r["sector"]),
                },
            )
        await db.commit()

    await record_run("fetch_sector_indices", "ok", f"{len(rows)} sectors", rows=len(rows))
    return {"ok": True, "job": "fetch_sector_indices", "rows": len(rows)}


def _sector_scores(rows: list[dict]) -> dict[str, float]:
    """0..1 cross-sectional sector scores from momentum + trend (neutral 0.5)."""
    def _norm(vals: list[float], lo: float, hi: float) -> float:
        if not vals:
            return 0.5
        v = max(lo, min(hi, vals[-1]))
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    for r in rows:
        score = 0.5
        mom = r["momentum"]
        dma = r["dma_50"]
        if mom is not None or dma is not None:
            m = _norm([mom] if mom is not None else [0.0], -0.10, 0.10)
            d = _norm([dma] if dma is not None else [1.0], 0.95, 1.05)
            score = round(0.5 * m + 0.5 * d, 4)
        r["score"] = score
    return {r["sector"]: r["score"] for r in rows}


# ── 5. Breadth (computed, no API) ───────────────────────────────────────
async def compute_breadth(today: str | None = None) -> dict:
    """18:15 IST — breadth from equity_daily → market_breadth_daily."""
    date = today or datetime.now().strftime("%Y-%m-%d")
    closes = feature_store.equity_closes()
    if closes.empty or len(closes) < 2:
        await record_run("compute_breadth", "degraded", "equity_daily empty — run fetch_equity first")
        return {"ok": True, "job": "compute_breadth", "degraded": True, "note": "feature store empty"}

    last = closes.iloc[-1]
    prev = closes.iloc[-2]
    adv = int((last > prev).sum())
    dec = int((last < prev).sum())
    pct50 = _pct_above(closes, 50)
    pct200 = _pct_above(closes, 200)
    highs52 = _count_52w_highs(closes)
    lows52 = _count_52w_lows(closes)

    from sqlalchemy import text

    async with session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO finance.market_breadth_daily "
                "(date, advance, decline, pct_above_50dma, pct_above_200dma, highs_52w, lows_52w) "
                "VALUES (:d, :a, :de, :p50, :p200, :hi, :lo) "
                "ON CONFLICT (date) DO UPDATE SET "
                "advance = EXCLUDED.advance, decline = EXCLUDED.decline, "
                "pct_above_50dma = EXCLUDED.pct_above_50dma, pct_above_200dma = EXCLUDED.pct_above_200dma, "
                "highs_52w = EXCLUDED.highs_52w, lows_52w = EXCLUDED.lows_52w"
            ),
            {"d": date, "a": adv, "de": dec, "p50": _r(pct50), "p200": _r(pct200), "hi": highs52, "lo": lows52},
        )
        await db.commit()

    await record_run("compute_breadth", "ok", f"A/D={adv}/{dec}, >50DMA={pct50:.0f}%, >200DMA={pct200:.0f}%", rows=1)
    return {"ok": True, "job": "compute_breadth", "advance": adv, "decline": dec}


def _pct_above(closes: pd.DataFrame, window: int) -> float:
    if len(closes) < window:
        return 0.0
    dma = closes.rolling(window).mean().iloc[-1]
    above = (closes.iloc[-1] > dma).sum()
    total = closes.iloc[-1].notna().sum()
    return above / total * 100.0 if total else 0.0


def _count_52w_highs(closes: pd.DataFrame, window: int = 250) -> int:
    if len(closes) < window:
        return 0
    recent = closes.iloc[-1]
    hist = closes.iloc[-window:-1]
    highs = (hist.max(axis=0) < recent) & recent.notna()
    return int(highs.sum())


def _count_52w_lows(closes: pd.DataFrame, window: int = 250) -> int:
    if len(closes) < window:
        return 0
    recent = closes.iloc[-1]
    hist = closes.iloc[-window:-1]
    lows = (hist.min(axis=0) > recent) & recent.notna()
    return int(lows.sum())


# ── Numeric helpers ──────────────────────────────────────────────────────
def _as_float(v: Any) -> Optional[float]:
    if v is None or pd.isna(v):
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> Optional[int]:
    f = _as_float(v)
    return int(f) if f is not None else None


def _r(v: Optional[float]) -> Optional[float]:
    return round(float(v), 6) if v is not None else None
