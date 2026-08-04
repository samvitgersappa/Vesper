"""Plain-data job scheduler (APScheduler) + event subscribers.

Pure-DATA jobs ONLY — market jobs, RSS, graph analytics, mechanical
knowledge-architect work, CRM follow-up sweeps, vault backup, hermes mirror,
notification sweep. Reasoning jobs (Morning Brief, Daily Journal Questionnaire,
Evening Review, etc.) are Hermes Agent cron skills (hermes-config/cron/), never
here (plan.md §12).

Schedules mirror plan.md §12 (IST):
- Market: fetch_equity 06:00, compute_factors 06:30, fetch_macro 07:00,
  update_universe 07:30, paper_trade_eod 18:00 Mon-Fri (5 classic traders;
  6th catalyst_swing runs its own 19:00 job after its 18:00-18:50 data feed)
- Knowledge Architect Pass: nightly 02:30
- Graph Analytics: nightly 03:00
- Graph projection backfill: nightly 03:05 (and once at worker startup)
- CRM Follow-ups: hourly sweep
- RSS: weekly (Mon 06:45)
- Vault Backup & Publish: daily 00:15 (addendum §7)
- Hermes mirror: every 5 min
- Notification "what matters" sweep: 08:00 + 18:00
"""

import asyncio
import logging
import threading

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger("vesper.automation")

# Uses the blocking scheduler when run as the worker entrypoint, and a
# background scheduler when embedded (e.g. tests). Timezone is IST so cron
# values match plan.md §12 exactly.
scheduler = BlockingScheduler(timezone="Asia/Kolkata")


def _job(name: str):
    def _decorator(fn):
        scheduler.add_job(fn, id=name, replace_existing=True, **JOB_SCHEDULE[name])
        logger.info("Registered data job %s", name)
        return fn

    return _decorator


# ── Schedules (plan.md §12, IST) ─────────────────────────────────────────
JOB_SCHEDULE = {
    "fetch_equity": {"trigger": "cron", "hour": 6, "minute": 0},
    "compute_factors": {"trigger": "cron", "hour": 6, "minute": 30},
    "fetch_macro": {"trigger": "cron", "hour": 7, "minute": 0},
    "update_universe": {"trigger": "cron", "hour": 7, "minute": 30},
    "paper_trade_eod": {"trigger": "cron", "hour": 18, "minute": 0, "day_of_week": "mon-fri"},
    "knowledge_architect_pass": {"trigger": "cron", "hour": 2, "minute": 30},
    "graph_analytics_pass": {"trigger": "cron", "hour": 3, "minute": 0},
    "graph_projection_backfill": {"trigger": "cron", "hour": 3, "minute": 5},
    "crm_followups_sweep": {"trigger": "interval", "hours": 1},
    "rss_process": {"trigger": "cron", "hour": 6, "minute": 45, "day_of_week": "mon"},
    "index_vault_semantic": {"trigger": "cron", "hour": 3, "minute": 15},
    "journal_questionnaire_deadline": {"trigger": "cron", "hour": 23, "minute": 55},
    "vault_backup_publish": {"trigger": "cron", "hour": 0, "minute": 15},
    "hermes_mirror": {"trigger": "interval", "minutes": 5},
    "notification_sweep_morning": {"trigger": "cron", "hour": 8, "minute": 0},
    "notification_sweep_evening": {"trigger": "cron", "hour": 18, "minute": 5},
    # Catalyst Swing Trader (Part E) — 18:00–19:00 IST weekdays.
    "fetch_catalyst_bhavcopy": {"trigger": "cron", "hour": 18, "minute": 0, "day_of_week": "mon-fri"},
    "fetch_fii_dii": {"trigger": "cron", "hour": 18, "minute": 5, "day_of_week": "mon-fri"},
    "fetch_index_pcr": {"trigger": "cron", "hour": 18, "minute": 7, "day_of_week": "mon-fri"},
    "fetch_sector_indices": {"trigger": "cron", "hour": 18, "minute": 10, "day_of_week": "mon-fri"},
    "compute_market_breadth": {"trigger": "cron", "hour": 18, "minute": 15, "day_of_week": "mon-fri"},
    "catalyst_screen": {"trigger": "cron", "hour": 18, "minute": 20, "day_of_week": "mon-fri"},
    "catalyst_news": {"trigger": "cron", "hour": 18, "minute": 30, "day_of_week": "mon-fri"},
    "catalyst_llm": {"trigger": "cron", "hour": 18, "minute": 40, "day_of_week": "mon-fri"},
    "catalyst_risk": {"trigger": "cron", "hour": 18, "minute": 50, "day_of_week": "mon-fri"},
    "catalyst_paper_trade": {"trigger": "cron", "hour": 19, "minute": 0, "day_of_week": "mon-fri"},
}


def _asyncio_wrap(coro_fn):
    """Run an async job inside the blocking scheduler (which is sync)."""

    def _run():
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return
            loop.run_until_complete(coro_fn())
        except RuntimeError:
            asyncio.run(coro_fn())

    return _run


def register_data_job(job_id: str, schedule_kwargs: dict, fn) -> None:
    """Register a plain data job with APScheduler (public API)."""
    scheduler.add_job(fn, id=job_id, replace_existing=True, **schedule_kwargs)
    logger.info("Registered data job %s", job_id)


def _register_all() -> None:
    """Wire every data job from plan.md §12 + event subscribers."""
    from backend.automation.jobs.finance import (
        fetch_equity, compute_factors, fetch_macro, update_universe, paper_trade_eod,
    )
    from backend.automation.jobs.catalyst import ALL_JOBS as catalyst_jobs
    from backend.automation.jobs.graph_analytics import graph_analytics_pass
    from backend.modules.graph.backfill import backfill_graph
    from backend.automation.jobs.knowledge_architect import knowledge_architect_pass
    from backend.automation.jobs.crm_followups import crm_followups_sweep
    from backend.automation.jobs.rss import rss_process
    from backend.automation.jobs.lancedb import index_vault_semantic
    from backend.automation.jobs.journal_deadline import journal_questionnaire_deadline
    from backend.automation.jobs.vault_publish import vault_backup_publish
    from backend.automation.jobs.hermes_mirror import hermes_mirror
    from backend.notification import triage, send_telegram

    jobs = {
        "fetch_equity": fetch_equity,
        "compute_factors": compute_factors,
        "fetch_macro": fetch_macro,
        "update_universe": update_universe,
        "paper_trade_eod": paper_trade_eod,
        "knowledge_architect_pass": knowledge_architect_pass,
        "graph_analytics_pass": graph_analytics_pass,
        "graph_projection_backfill": backfill_graph,
        "crm_followups_sweep": crm_followups_sweep,
        "rss_process": rss_process,
        "index_vault_semantic": index_vault_semantic,
        "journal_questionnaire_deadline": journal_questionnaire_deadline,
        "hermes_mirror": hermes_mirror,
    }
    jobs.update(catalyst_jobs)
    for name, fn in jobs.items():
        register_data_job(name, JOB_SCHEDULE[name], _asyncio_wrap(fn))

    # Sync jobs (no asyncio wrap needed).
    register_data_job("vault_backup_publish", JOB_SCHEDULE["vault_backup_publish"], vault_backup_publish)

    async def _notification_sweep():
        messages = await triage()
        for m in messages:
            await send_telegram(m)

    register_data_job(
        "notification_sweep_morning",
        JOB_SCHEDULE["notification_sweep_morning"],
        _asyncio_wrap(_notification_sweep),
    )
    register_data_job(
        "notification_sweep_evening",
        JOB_SCHEDULE["notification_sweep_evening"],
        _asyncio_wrap(_notification_sweep),
    )

    _start_event_subscribers()


def _start_event_subscribers() -> None:
    """Subscribe the worker to the event bus for reactive side effects:
    - graph write adapter (PersonUpdated/InteractionLogged/KnowledgeIndexed)
    - notification event delivery (ReminderDue, DailyJournalCompleted)
    Runs each subscription in its own daemon thread.
    """
    import threading

    def _graph_sub():
        import asyncio

        from backend.modules.graph.write_adapter import graph_subscriber
        from backend.events.bus import bus

        async def _run_graph(event: str, payload: dict) -> None:
            try:
                await graph_subscriber(event, payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("graph_subscriber failed: %s", exc)

        try:
            bus.subscribe_multi(
                ["PersonUpdated", "InteractionLogged", "KnowledgeIndexed"],
                lambda ev, pl: asyncio.run(_run_graph(ev, pl)),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("graph subscriber stopped: %s", exc)

    def _notify_sub():
        import asyncio

        from backend.notification import notify_event
        from backend.events.bus import bus

        async def _run_notify(event: str, payload: dict) -> None:
            try:
                await notify_event(event, payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("notify_event failed: %s", exc)

        try:
            bus.subscribe_multi(
                ["ReminderDue", "DailyJournalCompleted", "PortfolioNAVUpdated"],
                lambda ev, pl: asyncio.run(_run_notify(ev, pl)),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("notification subscriber stopped: %s", exc)

    threading.Thread(target=_graph_sub, daemon=True).start()
    threading.Thread(target=_notify_sub, daemon=True).start()


def run() -> None:
    """Start the blocking scheduler + event subscribers (worker entrypoint)."""
    _register_all()

    def _bootstrap_graph():
        """Project any pre-existing source rows on worker start (self-healing)."""
        import threading
        from backend.modules.graph.backfill import backfill_graph
        try:
            asyncio.run(backfill_graph())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("startup graph backfill failed: %s", exc)

    threading.Thread(target=_bootstrap_graph, daemon=True).start()

    def _bootstrap_catalyst():
        """Create the catalyst_swing paper account once (idempotent)."""
        import threading
        from backend.automation.jobs.catalyst import ensure_catalyst_account
        try:
            asyncio.run(ensure_catalyst_account())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("startup catalyst account bootstrap failed: %s", exc)

    threading.Thread(target=_bootstrap_catalyst, daemon=True).start()

    def _catch_up_traders():
        """Dispatch any trader jobs that missed today's window (startup after
        18:00 IST, worker crash/restart, server waking from sleep). Checks
        finance.job_runs for today's non-degraded paper_trade_eod run; if
        missing, dispatches it immediately so the trading day is never lost.

        Also catches up the catalyst paper trader if today's screen/LLM data
        pipeline has already run (the catalyst trader degrades honestly when
        the feature store is empty, so running it pre-emptively is harmless).
        """
        import time as _time
        from datetime import datetime, timezone, timedelta

        _time.sleep(6)  # let the scheduler + event subscribers settle

        ist = timezone(timedelta(hours=5, minutes=30))
        today = datetime.now(ist).strftime("%Y-%m-%d")
        weekday = datetime.now(ist).weekday()  # 0=Mon .. 6=Sun
        if weekday >= 5:
            logger.info("catch-up: weekend (%s) — paper_trade_eod only runs Mon–Fri, skip", today)
            return
        try:
            from backend.modules.db import session_factory
            from sqlalchemy import text
            async def _catch_up():
                async with session_factory()() as db:
                    already = (await db.execute(
                        text(
                            "SELECT 1 FROM finance.job_runs "
                            "WHERE job_name = 'paper_trade_eod' "
                            "AND (status = 'ok' OR status = 'holiday_skip') "
                            "AND finished_at LIKE :today"
                        ), {"today": today + "%"},
                    )).scalar()
                if already:
                    logger.info("catch-up: paper_trade_eod already ran today — skip")
                    return
                logger.info("catch-up: paper_trade_eod missed today — running now")
                from backend.automation.jobs.finance import paper_trade_eod
                res = await paper_trade_eod()
                n = len(res.get("traders", []))
                logger.info("catch-up: paper_trade_eod done (%d traders, degraded=%s)", n, res.get("degraded"))
            asyncio.run(_catch_up())
        except Exception as exc:  # pragma: no cover
            logger.warning("catch-up paper_trade_eod failed: %s", exc)

        # Catalyst paper trader: run if today's catalyst_llm/catalyst_risk have
        # already produced data (the cron schedule feeds them before the trade).
        # If the screen never ran but factor_features exist in DuckDB, run the
        # screen first, then the trade — the catalyst becomes self-sufficient
        # when price data exists, not dependent on the full NSE live pipeline.
        try:
            from backend.modules.db import session_factory
            from sqlalchemy import text
            async def _catch_up_catalyst():
                async with session_factory()() as db:
                    already = (await db.execute(
                        text(
                            "SELECT 1 FROM finance.job_runs "
                            "WHERE job_name = 'catalyst_paper_trade' "
                            "AND (status = 'ok' OR status = 'holiday_skip') "
                            "AND finished_at LIKE :today"
                        ), {"today": today + "%"},
                    )).scalar()
                if already:
                    logger.info("catch-up: catalyst_paper_trade already ran today — skip")
                    return
                prev = (await db.execute(
                    text("SELECT 1 FROM finance.job_runs WHERE job_name = 'catalyst_screen' AND finished_at LIKE :today"),
                    {"today": today + "%"},
                )).scalar()
                if not prev:
                    # Screen never ran. If factor features exist, run the screen
                    # now so the trader has candidates to evaluate.
                    try:
                        from backend.db import feature_store as fs
                        f = fs.client.df("SELECT 1 FROM factor_features LIMIT 1")
                        has_factors = not f.empty
                    except Exception:
                        has_factors = False
                    if has_factors:
                        logger.info("catch-up: catalyst_screen missed — running it now (factors exist)")
                        from backend.modules.finance.catalyst.scores import screen as catalyst_screen
                        scr = await catalyst_screen()
                        logger.info("catch-up: catalyst_screen done (degraded=%s, scored=%s)", scr.get("degraded"), scr.get("scored"))
                    else:
                        logger.info("catch-up: catalyst_screen not run and no factors — deferring to cron")
                        return
                logger.info("catch-up: catalyst_paper_trade missed today — running now")
                from backend.modules.finance.catalyst.trader import run_day as catalyst_run_day
                res = await catalyst_run_day()
                logger.info("catch-up: catalyst_paper_trade done (degraded=%s)", res.get("degraded"))
            asyncio.run(_catch_up_catalyst())
        except Exception as exc:  # pragma: no cover
            logger.warning("catch-up catalyst_paper_trade failed: %s", exc)

    threading.Thread(target=_catch_up_traders, daemon=True).start()

    logger.info("Starting Vesper data scheduler")
    scheduler.start()
