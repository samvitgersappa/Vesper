"""Shared helpers for the Catalyst Swing Trader jobs.

- `_record_run` logs every job run to finance.job_runs (the existing CronRun
  style table) so the scheduler/ops can audit success, degraded and error runs.
- `ist_today` returns the trading date in Asia/Kolkata (the schedule is IST).
- `sector_for_symbol` maps a Nifty-500 symbol to its Industry using the bundled
  `ind_nifty500list.csv` (used by the Layer-2 sector score).

Every fetch degrades honestly: failures are logged as `degraded` runs, never
raised — the pipeline continues (plan §16, Quiver port rule).
"""

import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger("vesper.finance.catalyst")

_UNIVERSE_CSV = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "raw" / "ind_nifty500list.csv"
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")[:19]


def ist_today() -> str:
    """Trading date (Asia/Kolkata), as YYYY-MM-DD."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")


async def record_run(job: str, status: str, detail: str = "", rows: int | None = None) -> None:
    """Log a job run to finance.job_runs (status ok|degraded|error)."""
    try:
        from sqlalchemy import text

        from backend.modules.db import session_factory

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
                    "started": _now_utc(),
                    "finished": _now_utc(),
                    "error": detail[:500] if status in {"error", "degraded"} else None,
                    "rows": rows,
                },
            )
            await db.commit()
    except Exception as exc:  # pragma: no cover - never fail the job on logging
        logger.warning("record_run(%s) failed: %s", job, exc)


@lru_cache(maxsize=1)
def _sector_frame():
    import pandas as pd

    if not _UNIVERSE_CSV.exists():
        return None
    try:
        df = pd.read_csv(_UNIVERSE_CSV, usecols=["Symbol", "Industry"])
        return df
    except Exception:  # pragma: no cover - malformed CSV degrades to None
        return None


def sector_for_symbol(symbol: str) -> Optional[str]:
    """Nifty-500 Industry for a symbol (None if unmapped)."""
    sym = (symbol or "").removesuffix(".NS").strip().upper()
    df = _sector_frame()
    if df is None:
        return None
    row = df.loc[df["Symbol"].astype(str).str.upper() == sym]
    if row.empty:
        return None
    return str(row.iloc[0]["Industry"]).strip()
