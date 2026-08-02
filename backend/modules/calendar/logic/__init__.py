"""calendar module business logic.

There is no calendar schema/table — the Calendar module is an aggregation layer
that merges event-shaped rows from OTHER schemas (plan.md §5/§8, calendar.skill):
birthdays, interactions, reminders and life events from the `relationship`
schema, plus exam/test dates from the `study` schema.

The pure date helpers at the top are deterministic and unit-testable without a
DB; the DB-backed functions use the shared async session factory
(`session_factory()()` — the sessionmaker itself is NOT an async CM).
"""

from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from sqlalchemy import select

from backend.db.postgres.schemas.relationship.models import (
    Person, Interaction, Reminder, LifeEvent,
)
from backend.db.postgres.schemas.study.models import Test
from backend.modules.db import session_factory


# ─── Pure date helpers (no DB) ───────────────────────────────────────────────

def parse_iso_date(s: str) -> Optional[date]:
    """Safely parse a 'YYYY-MM-DD' string into a date.

    Returns None (never raises) on empty/whitespace/malformed input.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def resolve_date(s: str, today: date, is_end: bool) -> Optional[date]:
    """Resolve a date string, supporting relative shorthands.

    - ``today``     -> today
    - ``tomorrow``  -> today + 1 day
    - ``week``      -> today + 7 days (used as an end bound)
    - ``month``     -> today + 30 days (used as an end bound)
    - otherwise     -> parsed as ISO ``YYYY-MM-DD``

    Returns None for anything unrecognized.
    """
    if not s or not isinstance(s, str):
        return None
    key = s.strip().lower()
    if key == "today":
        return today
    if key == "tomorrow":
        return today + timedelta(days=1)
    if key == "week":
        return today + timedelta(days=7)
    if key == "month":
        return today + timedelta(days=30)
    return parse_iso_date(s)


def resolve_range(from_str: str, to_str: str, today: Optional[date] = None) -> Optional[tuple[date, date]]:
    """Resolve a ``(from, to)`` pair into inclusive ``(start, end)`` dates.

    Returns None if either bound is invalid or ``end < start``.
    """
    t = today or date.today()
    start = resolve_date(from_str, t, is_end=False)
    end = resolve_date(to_str, t, is_end=True)
    if start is None or end is None or end < start:
        return None
    return start, end


def birthday_occurrences(birthday: date, start: date, end: date) -> list[date]:
    """Every date on which an annual birthday falls within ``[start, end]``.

    Handles year rollover (range may span a year boundary) and Feb 29 → Feb 28
    in non-leap years.
    """
    occurrences: list[date] = []
    for year in range(start.year, end.year + 1):
        try:
            occ = birthday.replace(year=year)
        except ValueError:
            occ = birthday.replace(year=year, month=2, day=28)
        if start <= occ <= end:
            occurrences.append(occ)
    return occurrences


def _as_date(value: Any) -> Optional[date]:
    """Coerce a datetime/date to a date (None-safe)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_iso_date(str(value))


# ─── Tools (DB-backed) ───────────────────────────────────────────────────────

async def events(from_str: str, to_str: str) -> dict[str, Any]:
    """Merged, date-sorted calendar events across all sources for a date range.

    Each item: ``{date, type, title, source}``. Returns an error dict (rather
    than raising) for empty/malformed/inverted date ranges.
    """
    resolved = resolve_range(from_str, to_str)
    if resolved is None:
        return {
            "error": "invalid date range",
            "message": "Pass ISO dates (YYYY-MM-DD) or today/tomorrow/week/month for both `from` and `to`, with `from` <= `to`.",
        }
    start, end = resolved
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.max)

    items: list[dict[str, Any]] = []

    async with session_factory()() as db:
        # Birthdays: match month/day within the range regardless of year.
        persons = (
            await db.execute(select(Person).where(Person.is_archived.is_(False)))
        ).scalars().all()
        for p in persons:
            bday = _as_date(p.birthday)
            if not bday:
                continue
            for occ in birthday_occurrences(bday, start, end):
                items.append({
                    "date": occ.isoformat(),
                    "type": "birthday",
                    "title": f"{p.name}'s birthday",
                    "source": "relationship.persons",
                })

        # Interactions (join Person for the contact name).
        rows = (
            await db.execute(
                select(Interaction, Person.name)
                .join(Person, Interaction.person_id == Person.id)
                .where(Interaction.event_date.between(start_dt, end_dt))
            )
        ).all()
        for inter, name in rows:
            items.append({
                "date": _as_date(inter.event_date).isoformat(),
                "type": "interaction",
                "title": f"{inter.summary or inter.type} with {name}",
                "source": "relationship.interactions",
            })

        # Reminders due (skip dismissed ones).
        rows = (
            await db.execute(
                select(Reminder, Person.name)
                .join(Person, Reminder.person_id == Person.id, isouter=True)
                .where(
                    Reminder.due_at.between(start_dt, end_dt),
                    Reminder.is_dismissed.is_(False),
                )
            )
        ).all()
        for rem, name in rows:
            title = rem.title
            if name:
                title = f"{title} ({name})"
            items.append({
                "date": _as_date(rem.due_at).isoformat(),
                "type": "reminder",
                "title": title,
                "source": "relationship.reminders",
            })

        # Life events (join Person for the contact name).
        rows = (
            await db.execute(
                select(LifeEvent, Person.name)
                .join(Person, LifeEvent.person_id == Person.id)
                .where(LifeEvent.event_date.between(start_dt, end_dt))
            )
        ).all()
        for le, name in rows:
            title = le.title
            if name:
                title = f"{title} ({name})"
            items.append({
                "date": _as_date(le.event_date).isoformat(),
                "type": "life_event",
                "title": title,
                "source": "relationship.life_events",
            })

        # Study exam/test dates.
        tests = (
            await db.execute(
                select(Test).where(
                    Test.target_date.is_not(None),
                    Test.target_date.between(start_dt, end_dt),
                )
            )
        ).scalars().all()
        for t in tests:
            items.append({
                "date": _as_date(t.target_date).isoformat(),
                "type": "exam",
                "title": f"{t.name} exam",
                "source": "study.tests",
            })

    items.sort(key=lambda x: (x["date"], x["type"], x["title"]))
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "events": items,
        "count": len(items),
    }


async def birthdays() -> dict[str, Any]:
    """Contacts with a birthday in the next 30 days, sorted by date."""
    today = date.today()
    end = today + timedelta(days=30)

    async with session_factory()() as db:
        persons = (
            await db.execute(select(Person).where(Person.is_archived.is_(False)))
        ).scalars().all()

    results: list[dict[str, Any]] = []
    for p in persons:
        bday = _as_date(p.birthday)
        if not bday:
            continue
        occs = birthday_occurrences(bday, today, end)
        if occs:
            results.append({
                "person_id": p.id,
                "name": p.name,
                "birthday": bday.isoformat(),
                "next": occs[-1].isoformat(),
            })
    results.sort(key=lambda x: (x["next"], x["name"]))
    return {
        "window": f"{today.isoformat()}..{end.isoformat()}",
        "birthdays": results,
        "count": len(results),
    }
