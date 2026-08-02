"""Plain-data job scheduler (APScheduler) + event subscribers.

Pure-DATA jobs ONLY — market jobs, RSS, graph analytics, mechanical
knowledge-architect work, CRM follow-up sweeps, vault backup, hermes mirror,
notification sweep. Reasoning jobs (Morning Brief, Daily Journal Questionnaire,
Evening Review, etc.) are Hermes Agent cron skills (hermes-config/cron/), never
here (plan.md §12).

Schedules mirror plan.md §12 (IST):
- Market: fetch_equity 06:00, compute_factors 06:30, fetch_macro 07:00,
  update_universe 07:30, paper_trade_eod 17:00 Mon-Fri
- Knowledge Architect Pass: nightly 02:30
- Graph Analytics: nightly 03:00
- CRM Follow-ups: hourly sweep
- RSS: weekly (Mon 06:45)
- Vault Backup & Publish: daily 00:15 (addendum §7)
- Hermes mirror: every 5 min
- Notification "what matters" sweep: 08:00 + 18:00
"""

import asyncio
import logging

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
    "paper_trade_eod": {"trigger": "cron", "hour": 17, "minute": 0, "day_of_week": "mon-fri"},
    "knowledge_architect_pass": {"trigger": "cron", "hour": 2, "minute": 30},
    "graph_analytics_pass": {"trigger": "cron", "hour": 3, "minute": 0},
    "crm_followups_sweep": {"trigger": "interval", "hours": 1},
    "rss_process": {"trigger": "cron", "hour": 6, "minute": 45, "day_of_week": "mon"},
    "index_vault_semantic": {"trigger": "cron", "hour": 3, "minute": 15},
    "journal_questionnaire_deadline": {"trigger": "cron", "hour": 23, "minute": 55},
    "vault_backup_publish": {"trigger": "cron", "hour": 0, "minute": 15},
    "hermes_mirror": {"trigger": "interval", "minutes": 5},
    "notification_sweep_morning": {"trigger": "cron", "hour": 8, "minute": 0},
    "notification_sweep_evening": {"trigger": "cron", "hour": 18, "minute": 0},
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
    from backend.automation.jobs.graph_analytics import graph_analytics_pass
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
        "crm_followups_sweep": crm_followups_sweep,
        "rss_process": rss_process,
        "index_vault_semantic": index_vault_semantic,
        "journal_questionnaire_deadline": journal_questionnaire_deadline,
        "hermes_mirror": hermes_mirror,
    }
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
        from backend.modules.graph.write_adapter import graph_subscriber
        from backend.events.bus import bus

        try:
            bus.subscribe_multi(
                ["PersonUpdated", "InteractionLogged", "KnowledgeIndexed"],
                graph_subscriber,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("graph subscriber stopped: %s", exc)

    def _notify_sub():
        from backend.notification import notify_event
        from backend.events.bus import bus

        try:
            bus.subscribe_multi(
                ["ReminderDue", "DailyJournalCompleted", "PortfolioNAVUpdated"],
                notify_event,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("notification subscriber stopped: %s", exc)

    threading.Thread(target=_graph_sub, daemon=True).start()
    threading.Thread(target=_notify_sub, daemon=True).start()


def run() -> None:
    """Start the blocking scheduler + event subscribers (worker entrypoint)."""
    _register_all()
    logger.info("Starting Vesper data scheduler")
    scheduler.start()
