"""Notification engine — "what matters" (plan.md §11, addendum §11).

Hermes Agent's native gateway is the delivery channel (Telegram). This module
implements the *triage* half ("what matters"): rule-based checks over events and
module data, turning a cheap, high-signal subset into a Telegram message via the
bot API. No ntfy — Telegram covers everything (§11 decision).

Anti-nagging policy (addendum §5): a captured note with reminder-like intent but
no explicit date/time is surfaced ONLY in Weekly Review, never here.

Rule set (common, simple cases — plan §11 says keep common cases as rule checks,
not an LLM call every time):
- NAV dropped ≥ 4% today (PortfolioNAVUpdated / finance.nav)
- Birthday tomorrow (CalendarEventCreated / calendar.birthdays)
- Due/cold contact today (PersonUpdated / relationship.get_due_today)
- ReminderDue (CRM follow-up sweep)
- Journal not completed by the 21:30+ retry window (DailyJournalCompleted)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from datetime import date, timedelta

import httpx

from backend.events.catalog import (
    REMINDER_DUE,
    PORTFOLIO_NAV_UPDATED,
    DAILY_JOURNAL_COMPLETED,
)
from backend.modules.common import publish  # noqa: F401 (exported for subscribers)

logger = logging.getLogger("vesper.notification")
_journal_alerted_dates: set[str] = set()


def _journal_notification_snoozed(date: str) -> bool:
    """Allow an operational one-day snooze without disabling journal writes."""
    directory = Path(os.environ.get("VESPER_JOURNAL_SNOOZE_DIR", "/tmp"))
    return (directory / f"vesper-journal-notification-snooze-{date}").exists()

# anti-nagging: undated, reminder-like captures never surface here (addendum §5).
# They only appear in Weekly Review (hermes-config/cron/weekly_review).


def _chat_id() -> str:
    return os.environ.get("TELEGRAM_HOME_CHANNEL", "") or os.environ.get(
        "TELEGRAM_ALLOWED_USERS", ""
    )


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


async def send_telegram(message: str) -> bool:
    """Send a plain text message via the Telegram Bot API. Best-effort."""
    token, chat = _token(), _chat_id()
    if not token or not chat:
        logger.warning("notification: TELEGRAM_BOT_TOKEN or chat id unset — drop")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat, "text": message[:4000]},
            )
            ok = r.json().get("ok", False)
        if not ok:
            logger.warning("telegram send failed: %s", r.text[:200])
        return ok
    except Exception as exc:  # pragma: no cover
        logger.warning("telegram send error: %s", exc)
        return False


async def _nav_drop_alert() -> str | None:
    """NAV dropped ≥ 4% today for any strategy (plan §11 example)."""
    try:
        from backend.modules.finance.logic import nav
        from backend.modules.db import session_factory, dispose  # noqa: F401

        for strategy in ("",):
            data = await nav(strategy, limit=2)
            points = data.get("points", [])
            if len(points) < 2:
                continue
            latest, prev = points[-1], points[-2]
            lv = latest.get("nav") or 0
            pv = prev.get("nav") or 0
            if pv:
                change = (lv - pv) / pv * 100
                if change <= -4.0:
                    return (
                        f"⚠️ {strategy or 'portfolio'} NAV {change:.1f}% today "
                        f"({lv:.2f}) — worth a look."
                    )
    except Exception as exc:  # pragma: no cover
        logger.debug("nav drop check failed: %s", exc)
    return None


async def _birthday_alert() -> str | None:
    """Birthday tomorrow (plan §11 example)."""
    try:
        from backend.modules.calendar.logic import birthdays
        items = await birthdays()
        tomorrow = date.today() + timedelta(days=1)
        for b in items.get("birthdays", []):
            bday = b.get("birthday")
            if bday:
                md = bday[5:] if isinstance(bday, str) and len(bday) >= 7 else None
                if md and md == tomorrow.strftime("%m-%d"):
                    return f"🎂 {b.get('name')}'s birthday is tomorrow."
    except Exception as exc:  # pragma: no cover
        logger.debug("birthday check failed: %s", exc)
    return None


async def _due_contact_alert() -> str | None:
    """Due/cold contact today."""
    try:
        from backend.modules.relationship.logic import relationship_get_due_today
        data = await relationship_get_due_today()
        due = data.get("due_today") or data.get("results") or []
        if due and len(due) >= 1:
            names = ", ".join(
                d.get("name") or d.get("person_name") or "?" for d in due[:3]
            )
            return f"📅 Contact overdue/due today: {names}."
    except Exception as exc:  # pragma: no cover
        logger.debug("due-contact check failed: %s", exc)
    return None


async def triage() -> list[str]:
    """Run all rule checks; return the list of messages worth surfacing."""
    checks = [_nav_drop_alert, _birthday_alert, _due_contact_alert]
    messages: list[str] = []
    for check in checks:
        try:
            msg = await check()
            if msg:
                messages.append(msg)
        except Exception as exc:  # pragma: no cover
            logger.debug("triage check failed: %s", exc)
    return messages


async def notify_event(event: str, payload: dict) -> None:
    """Event-driven notification (subscriber callback). Best-effort."""
    if event == REMINDER_DUE:
        msg = f"⏰ Reminder: {payload.get('message', 'Follow up')}"
        await send_telegram(msg)
    elif event == PORTFOLIO_NAV_UPDATED:
        pass  # covered by the scheduled triage sweep (avoid double pings)
    elif event == DAILY_JOURNAL_COMPLETED:
        if not payload.get("complete"):
            event_date = str(payload.get("date", ""))
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
            if event_date != today or event_date in _journal_alerted_dates or _journal_notification_snoozed(event_date):
                return
            _journal_alerted_dates.add(event_date)
            await send_telegram("📝 Today's journal wasn't completed — backfill in the morning brief.")
