"""One-shot bootstrap for the paper-trading roster (start.sh).

Idempotent: creates a `finance.paper_account` row for every strategy in the
STRATEGIES roster that doesn't already have one, seeds a baseline NAV row so
the web app's performance chart isn't empty, and leaves existing accounts
(and their trading history) untouched. Called by start.sh after migrations;
the worker's own scheduler bootstrap still runs independently at startup.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import text

from backend.modules.db import session_factory
from backend.modules.finance.catalyst.trader import STARTING_CAPITAL as CATALYST_CAPITAL
from backend.modules.finance.logic import STRATEGIES

logger = logging.getLogger("vesper.finance.bootstrap")

# The 5 classic EOD traders are paper-funded at ₹5L each (multi_trader 500k).
CLASSIC_CAPITAL = 500_000.0

# Capital per trader_id: catalyst_swing is funded at ₹10L (work order);
# every other roster trader falls back to the classic ₹5L.
_CAPITAL = {s["trader_id"]: CLASSIC_CAPITAL for s in STRATEGIES}
_CAPITAL.update({"catalyst_swing": CATALYST_CAPITAL})


async def bootstrap_traders() -> dict:
    """Create any missing paper accounts (idempotent) and report status.

    For each strategy in the roster:
    - if the account already exists, skip it (never resets history);
    - otherwise insert the account at its configured capital and write a
      baseline `paper_nav_history` row for today so NAV charts start populated.
    """
    created, existing = [], []
    today = datetime.now().strftime("%Y-%m-%d")
    async with session_factory()() as db:
        for meta in STRATEGIES:
            tid = meta["trader_id"]
            row = (await db.execute(
                text("SELECT trader_id FROM finance.paper_account WHERE trader_id = :t"),
                {"t": tid},
            )).first()
            if row is not None:
                existing.append(tid)
                continue
            cap = float(_CAPITAL.get(tid, CLASSIC_CAPITAL))
            await db.execute(
                text(
                    "INSERT INTO finance.paper_account "
                    "(trader_id, available_cash, settled_cash, blocked_cash, pending_settlements) "
                    "VALUES (:t, :c, :c, 0, '[]')"
                ),
                {"t": tid, "c": cap},
            )
            await db.execute(
                text(
                    "INSERT INTO finance.paper_nav_history "
                    "(trader_id, date, total_equity, cash, holdings_value, n_positions) "
                    "VALUES (:t, :d, :c, :c, 0, 0) "
                    "ON CONFLICT (trader_id, date) DO NOTHING"
                ),
                {"t": tid, "d": today, "c": cap},
            )
            created.append(tid)
        await db.commit()
    logger.info("bootstrap_traders: created=%s existing=%s", created, existing)
    return {
        "ok": True,
        "created": created,
        "existing": existing,
        "capital": {tid: _CAPITAL[tid] for tid in created},
    }


def main() -> None:
    """CLI entry for start.sh: prints a JSON summary."""
    import json

    print(json.dumps(asyncio.run(bootstrap_traders()), indent=1))


if __name__ == "__main__":
    main()
