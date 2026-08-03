"""Catalyst Swing Trader jobs (Part E) — data acquisition → screen → LLM → trade.

Schedules (IST, plan §12 / Trader 6 guide):
  18:00 fetch_catalyst_bhavcopy    NSE bhavcopy delivery → delivery_stats
  18:05 fetch_fii_dii              NSE provisional FII/DII → market_sentiment_daily
  18:07 fetch_index_pcr            NSE index option chain PCR → index_options_sentiment
  18:10 fetch_sector_indices       yfinance sector indices → sector_scores_daily
  18:15 compute_market_breadth     breadth from equity_daily → market_breadth_daily
  18:20 catalyst_screen            Layer 1/2/3 scores + watchlist funnel
  18:40 catalyst_llm               DeepSeek V4 Flash catalyst analysis (capped)
  18:50 catalyst_risk              exits-only risk pass (stops/trailing/time/rank)
  19:00 catalyst_paper_trade       entries + NAV

Every job records a run in finance.job_runs and degrades honestly on failure;
the worker never aborts the pipeline (plan §16). `ensure_account` bootstraps
the `catalyst_swing` paper account once at worker startup.
"""

import logging

from backend.modules.finance.catalyst import llm, scores, sources, trader

logger = logging.getLogger("vesper.automation.catalyst")

ALL_JOBS = {
    "fetch_catalyst_bhavcopy": sources.fetch_bhavcopy,
    "fetch_fii_dii": sources.fetch_fii_dii,
    "fetch_index_pcr": sources.fetch_index_pcr,
    "fetch_sector_indices": sources.fetch_sector_indices,
    "compute_market_breadth": sources.compute_breadth,
    "catalyst_screen": scores.screen,
    "catalyst_risk": trader.run_risk,
    "catalyst_paper_trade": trader.run_day,
}


async def catalyst_llm() -> dict:
    """18:40 IST — run the capped LLM catalyst stage over the top of the funnel."""
    from backend.modules.finance.catalyst._util import ist_today

    d = ist_today()
    candidates = await scores.funnel_for_llm(d)
    if not candidates:
        from backend.modules.finance.catalyst._util import record_run

        await record_run("catalyst_llm", "degraded", "no funnel candidates — run catalyst_screen first")
        return {"ok": True, "job": "catalyst_llm", "degraded": True, "note": "no candidates"}
    results = await llm.analyze_funnel(candidates, d)
    return {
        "ok": True,
        "job": "catalyst_llm",
        "date": d,
        "analyzed": len(results),
        "positive": sum(1 for c in results if c.get("signal") == "positive"),
    }


ALL_JOBS["catalyst_llm"] = catalyst_llm


async def ensure_catalyst_account() -> None:
    """Bootstrap the catalyst_swing paper account (idempotent)."""
    await trader.ensure_account()
