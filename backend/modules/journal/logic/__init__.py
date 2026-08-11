"""journal module business logic (plan.md §4.1, §8.3, §13).

Journal is vault-backed: the markdown note at
`<vault>/journal/YYYY/MM/YYYY-MM-DD.md` is the source of truth and
`diary_entries` is a metadata layer over it (mood, tags, word_count, streak).

Exposes the Hermes journal.skill contract:
- `get_entry(date)` / `read_entry(date)` — read the vault note (+ metadata)
- `write_entry(text, mood, date, source)` — append today's vault note, upsert row
- `update_entry(date, new_content)` — rewrite the vault note
- `resolve(date)` — the "forget / scratch that" tool (plan §4.1 correction):
  removes the entry (vault note + metadata row). With the current schema there
  is no pending-item store or resolved flag, so resolve = remove.
- `log_expense(...)` / `log_workout(...)` — lightweight daily logs (§4.1)
- `get_mood_streak()` — consecutive days with a diary entry+mood from today back

All logic is deterministic — no LLM. Every DB write degrades gracefully to a
warn when Postgres is unavailable (the vault file is the system of record).
"""

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from backend.db.postgres.schemas.journal.models import DiaryEntry, Spending, Workout
from backend.modules.common import publish
from backend.modules.db import session_factory
from backend.modules.journal.format import enrich_markdown, render_new_note
from backend.modules.journal.vault import (
    entry_path,
    read_entry_file,
    vault_root,
    write_entry_file,
)
from backend.events.catalog import DAILY_JOURNAL_COMPLETED, JOURNAL_CREATED, KNOWLEDGE_INDEXED

logger = logging.getLogger("vesper.journal")

# Fixed spending taxonomy (plan.md §4.1 rule 2) — best-effort, default "Other".
SPENDING_CATEGORIES = [
    "Food",
    "Travel/Transport",
    "Shopping",
    "Bills/Utilities",
    "Health",
    "Entertainment",
    "Other",
]

_CATEGORY_ALIASES = {
    "travel": "Travel/Transport",
    "transport": "Travel/Transport",
    "transit": "Travel/Transport",
    "uber": "Travel/Transport",
    "cab": "Travel/Transport",
    "petrol": "Travel/Transport",
    "fuel": "Travel/Transport",
    "lunch": "Food",
    "dinner": "Food",
    "breakfast": "Food",
    "groceries": "Food",
    "groceries ": "Food",
    "food": "Food",
    "eat": "Food",
    "coffee": "Food",
    "bills": "Bills/Utilities",
    "utilities": "Bills/Utilities",
    "electricity": "Bills/Utilities",
    "rent": "Bills/Utilities",
    "internet": "Bills/Utilities",
    "shopping": "Shopping",
    "shop": "Shopping",
    "clothes": "Shopping",
    "medical": "Health",
    "health": "Health",
    "gym": "Health",
    "doctor": "Health",
    "pharmacy": "Health",
    "movie": "Entertainment",
    "entertainment": "Entertainment",
    "fun": "Entertainment",
    "subscription": "Entertainment",
}

_DIARY_CATEGORIES = ("STUDY", "HOBBY", "GENERAL")


# ─── helpers ────────────────────────────────────────────────────────────────


def _today() -> date:
    return date.today()


def _parse_date(value: Any) -> date:
    """Best-effort date parsing: date/datetime/ISO string, else today."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    return _today()


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)


def _normalize_spending_category(cat: str) -> str:
    c = (cat or "").strip()
    if not c:
        return "Other"
    low = re.sub(r"[^a-z0-9]+", " ", c.lower()).strip()
    for valid in SPENDING_CATEGORIES:
        if re.sub(r"[^a-z0-9]+", " ", valid.lower()).strip() == low:
            return valid
    if low in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[low]
    return "Other"


def _normalize_diary_category(cat: str) -> str:
    c = (cat or "").strip().upper()
    return c if c in _DIARY_CATEGORIES else "GENERAL"


def _normalize_muscle_groups(groups: Any) -> list[str]:
    if groups is None:
        return []
    if isinstance(groups, str):
        raw = [g.strip() for g in groups.split(",")]
    else:
        raw = [str(g).strip() for g in groups]
    return [g for g in raw if g]


def _derive_title(text: str, source: str, d: date) -> str:
    if source and source.strip():
        return source.strip()[:300]
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if lines:
        first = re.sub(r"^#+\s*", "", lines[0]).strip()
        if first:
            return first[:300]
    return f"Journal {d.isoformat()}"


def _build_content(d: date, body: str, append: bool) -> str:
    if append:
        return body
    # New (non-today) entries get the full graph-optimised template: rich
    # frontmatter, chronological nav links and a section skeleton — Obsidian/Quartz
    # graph nodes need more than flat text appended at the end of the file.
    return render_new_note(d, body=body)


def _entry_meta(e: DiaryEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "title": e.title,
        "category": e.category,
        "vault_path": e.vault_path,
        "mood": e.mood,
        "tags": e.tags or [],
        "word_count": e.word_count,
        "is_pinned": e.is_pinned,
        "entry_date": e.entry_date.isoformat() if e.entry_date else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


# ─── vault note + metadata ──────────────────────────────────────────────────


async def _get_entry_metadata(d: date) -> Optional[dict[str, Any]]:
    try:
        async with session_factory()() as db:
            start, end = _day_bounds(d)
            res = await db.execute(
                select(DiaryEntry)
                .where(DiaryEntry.entry_date >= start, DiaryEntry.entry_date < end)
                .order_by(DiaryEntry.created_at.desc())
            )
            e = res.scalars().first()
            return _entry_meta(e) if e is not None else None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("diary metadata read failed: %s", exc)
        return None


async def _upsert_entry_metadata(
    d: date,
    path: str,
    title: str,
    mood: str,
    category: str,
    tags: Optional[list],
    word_count: int,
) -> dict[str, Any]:
    try:
        async with session_factory()() as db:
            start, end = _day_bounds(d)
            res = await db.execute(
                select(DiaryEntry)
                .where(DiaryEntry.entry_date >= start, DiaryEntry.entry_date < end)
                .order_by(DiaryEntry.created_at.desc())
            )
            e = res.scalars().first()
            if e is None:
                e = DiaryEntry(
                    title=title,
                    category=category,
                    vault_path=path,
                    mood=mood or None,
                    tags=list(tags or []),
                    word_count=word_count,
                    entry_date=datetime(d.year, d.month, d.day),
                )
                db.add(e)
                created = True
            else:
                created = False
                e.title = title
                e.category = category
                e.vault_path = path
                if mood:
                    e.mood = mood
                if tags is not None:
                    e.tags = list(tags)
                e.word_count = word_count
            await db.commit()
            return {"entry_id": e.id, "created": created}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("diary metadata upsert failed: %s", exc)
        return {"entry_id": None, "created": False, "error": str(exc)}


async def _update_entry_word_count(d: date, word_count: int) -> None:
    try:
        async with session_factory()() as db:
            start, end = _day_bounds(d)
            res = await db.execute(
                select(DiaryEntry)
                .where(DiaryEntry.entry_date >= start, DiaryEntry.entry_date < end)
                .order_by(DiaryEntry.created_at.desc())
            )
            e = res.scalars().first()
            if e is not None:
                e.word_count = word_count
                await db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("diary word_count update failed: %s", exc)


# ─── tools ──────────────────────────────────────────────────────────────────


async def get_entry(date: str = "") -> dict[str, Any]:
    """Read a journal entry: the vault note plus `diary_entries` metadata."""
    d = _parse_date(date or "")
    file_res = read_entry_file(d)
    meta = await _get_entry_metadata(d)
    if not file_res["ok"] and not meta:
        return {
            "found": False,
            "date": d.isoformat(),
            "message": f"No journal entry for {d.isoformat()}",
        }
    result: dict[str, Any] = {
        "found": True,
        "date": d.isoformat(),
        "content": file_res.get("content"),
        "path": file_res.get("path"),
        "word_count": file_res.get("word_count", (meta or {}).get("word_count", 0)),
        "meta": meta,
    }
    if not file_res["ok"]:
        result["message"] = file_res["message"]
    return result


async def read_entry(date: str = "") -> dict[str, Any]:
    """Read just the vault note for `date` (no DB metadata)."""
    d = _parse_date(date or "")
    res = read_entry_file(d)
    if not res["ok"]:
        return {"found": False, "date": d.isoformat(), "message": res["message"]}
    return {
        "found": True,
        "date": d.isoformat(),
        "content": res["content"],
        "path": res["path"],
        "word_count": res["word_count"],
    }


async def write_entry(
    text: str,
    mood: str = "",
    date: str = "",
    source: str = "",
    category: str = "GENERAL",
    tags: Optional[list] = None,
) -> dict[str, Any]:
    """Append to today's vault journal note and upsert the metadata row."""
    d = _parse_date(date or "")
    body = text.strip()
    if not body:
        return {"ok": False, "message": "empty journal text"}
    append = d == _today()
    file_res = write_entry_file(
        d,
        _build_content(d, body, append and entry_path(d).exists()),
        append=append,
    )
    if not file_res["ok"]:
        return file_res
    meta = await _upsert_entry_metadata(
        d=d,
        path=file_res["path"],
        title=_derive_title(body, source, d),
        mood=(mood or "").strip(),
        category=_normalize_diary_category(category),
        tags=tags,
        word_count=file_res["word_count"],
    )
    from backend.modules.relationship.logic import relationship_ingest_mentions

    mentions = await relationship_ingest_mentions(
        body,
        source=file_res.get("path") or f"journal/{d.isoformat()}",
    )
    formatting = await enrich_entry(d.isoformat())
    publish(JOURNAL_CREATED, {
        "entry_id": meta.get("entry_id"),
        "date": d.isoformat(),
        "path": file_res["path"],
        "appended": file_res["appended"],
        "mood": (mood or "").strip(),
        "word_count": file_res["word_count"],
    })
    # Reactive garden rebuild: every vault write triggers a KnowledgeIndexed
    # event so the Quartz Second Brain picks up new journal entries immediately.
    # `write_entry_file` returns an absolute path; keep event publication
    # defensive so a successful journal write is never reported as a failure.
    indexed_path = str(Path(file_res["path"] or "").resolve()) if file_res.get("path") else ""
    publish(KNOWLEDGE_INDEXED, {"path": indexed_path, "action": "journal_entry"})
    return {
        "ok": True,
        "entry_id": meta.get("entry_id"),
        "date": d.isoformat(),
        "path": file_res["path"],
        "appended": file_res["appended"],
        "mood": (mood or "").strip(),
        "word_count": file_res["word_count"],
        "people_created": mentions.get("created", []),
        "people_matched": mentions.get("matched", []),
        "formatted": formatting.get("enriched", False),
        "metadata": meta,
    }

async def update_entry(date: str, new_content: str) -> dict[str, Any]:
    """Rewrite the vault journal note for `date` and refresh its word count."""
    d = _parse_date(date or "")
    root = vault_root()
    if not root.exists():
        return {"ok": False, "message": "vault missing"}
    p = entry_path(d)
    if not p.exists():
        return {
            "ok": False,
            "date": d.isoformat(),
            "path": str(p),
            "message": f"No journal entry for {d.isoformat()}",
        }
    res = write_entry_file(d, new_content, append=False)
    if not res["ok"]:
        return res
    await _update_entry_word_count(d, res["word_count"])
    return {
        "ok": True,
        "date": d.isoformat(),
        "path": res["path"],
        "word_count": res["word_count"],
        "message": "journal entry updated",
    }


async def enrich_entry(date: str = "") -> dict[str, Any]:
    """Idempotently upgrade a vault journal note for Obsidian/Quartz graphing.

    Uses `journal.format.enrich_markdown`: ensures rich YAML frontmatter,
    chronological prev/next navigation wikilinks and a `## Connected` block
    listing the entry's wikilinks plus resolvable people/topics. No-op when the
    note is already enriched; never raises against a missing entry.
    """
    d = _parse_date(date or "")
    res = read_entry_file(d)
    if not res["ok"]:
        return {
            "ok": False,
            "date": d.isoformat(),
            "path": str(entry_path(d)),
            "message": res["message"],
            "enriched": False,
        }
    # A completed questionnaire can contain several answers and named people;
    # re-ingest the whole note so late Q8 additions reach People OS and graph.
    from backend.modules.relationship.logic import relationship_ingest_mentions

    await relationship_ingest_mentions(res["content"], source=res["path"])
    content, changed = enrich_markdown(res["content"], d, vault_root())
    if not changed:
        return {
            "ok": True,
            "date": d.isoformat(),
            "path": res["path"],
            "enriched": False,
            "message": "journal entry already graph-optimised",
        }
    wres = write_entry_file(d, content, append=False)
    if not wres["ok"]:
        return {**wres, "enriched": False}
    await _update_entry_word_count(d, wres["word_count"])
    publish(KNOWLEDGE_INDEXED, {"path": wres["path"], "action": "journal_enrich"})
    return {
        "ok": True,
        "date": d.isoformat(),
        "path": wres["path"],
        "enriched": True,
        "word_count": wres["word_count"],
        "message": "journal entry enriched for the Obsidian graph",
    }


async def resolve(date: str = "") -> dict[str, Any]:
    """Forget/scratch a journal entry (plan §4.1 correction).

    Removes the vault note and the `diary_entries` metadata row for `date`.
    Returns what was actually removed; missing entry -> ok: False.
    """
    d = _parse_date(date or "")
    root = vault_root()
    p = entry_path(d)
    removed_file = False
    if root.exists() and p.exists():
        try:
            p.unlink()
            removed_file = True
        except OSError as exc:  # pragma: no cover - defensive
            return {"ok": False, "date": d.isoformat(), "message": str(exc)}

    removed_metadata = False
    try:
        async with session_factory()() as db:
            start, end = _day_bounds(d)
            res = await db.execute(
                select(DiaryEntry)
                .where(DiaryEntry.entry_date >= start, DiaryEntry.entry_date < end)
                .order_by(DiaryEntry.created_at.desc())
            )
            for e in res.scalars().all():
                await db.delete(e)
                removed_metadata = True
            await db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("resolve metadata delete failed: %s", exc)

    if not removed_file and not removed_metadata:
        return {
            "ok": False,
            "found": False,
            "date": d.isoformat(),
            "message": f"No journal entry for {d.isoformat()}",
        }
    return {
        "ok": True,
        "found": True,
        "date": d.isoformat(),
        "removed_file": removed_file,
        "removed_metadata": removed_metadata,
        "message": "journal entry resolved (removed)",
    }


async def log_expense(
    amount: float,
    category: str = "",
    date: str = "",
    raw_text: str = "",
) -> dict[str, Any]:
    """Log a spending row against the fixed taxonomy (default "Other")."""
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return {"ok": False, "message": f"invalid amount: {amount!r}"}
    if amt < 0:
        return {"ok": False, "message": "amount cannot be negative"}
    d = _parse_date(date or "")
    cat = _normalize_spending_category(category)
    try:
        async with session_factory()() as db:
            s = Spending(
                date=datetime(d.year, d.month, d.day),
                amount=amt,
                category=cat,
                raw_text=raw_text or None,
            )
            db.add(s)
            await db.commit()
            return {
                "ok": True,
                "spending_id": s.id,
                "date": d.isoformat(),
                "amount": amt,
                "category": cat,
            }
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("spending insert failed: %s", exc)
        return {"ok": False, "message": str(exc)}


async def log_workout(
    activity: str = "workout",
    muscle_groups: Any = None,
    date: str = "",
    raw_text: str = "",
) -> dict[str, Any]:
    """Log a workout row (activity + muscle_groups[])."""
    act = (activity or "workout").strip() or "workout"
    muscles = _normalize_muscle_groups(muscle_groups)
    d = _parse_date(date or "")
    try:
        async with session_factory()() as db:
            w = Workout(
                date=datetime(d.year, d.month, d.day),
                activity=act,
                muscle_groups=muscles,
                raw_text=raw_text or None,
            )
            db.add(w)
            await db.commit()
            return {
                "ok": True,
                "workout_id": w.id,
                "date": d.isoformat(),
                "activity": act,
                "muscle_groups": muscles,
            }
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("workout insert failed: %s", exc)
        return {"ok": False, "message": str(exc)}


async def delete_expense(spending_id: str) -> dict[str, Any]:
    """Remove a specific spending row by id (self-correction for accidental logs)."""
    if not spending_id or not spending_id.strip():
        return {"ok": False, "message": "spending_id is required"}
    try:
        async with session_factory()() as db:
            r = await db.execute(select(Spending).where(Spending.id == spending_id.strip()))
            row = r.scalar_one_or_none()
            if row is None:
                return {"ok": False, "message": f"no spending row with id {spending_id}"}
            await db.delete(row)
            await db.commit()
            return {"ok": True, "deleted": spending_id, "amount": row.amount, "category": row.category}
    except Exception as exc:  # pragma: no cover
        logger.warning("delete expense failed: %s", exc)
        return {"ok": False, "message": str(exc)}


async def delete_workout(workout_id: str) -> dict[str, Any]:
    """Remove a specific workout row by id (self-correction for accidental logs)."""
    if not workout_id or not workout_id.strip():
        return {"ok": False, "message": "workout_id is required"}
    try:
        async with session_factory()() as db:
            r = await db.execute(select(Workout).where(Workout.id == workout_id.strip()))
            row = r.scalar_one_or_none()
            if row is None:
                return {"ok": False, "message": f"no workout row with id {workout_id}"}
            await db.delete(row)
            await db.commit()
            return {"ok": True, "deleted": workout_id, "activity": row.activity}
    except Exception as exc:  # pragma: no cover
        logger.warning("delete workout failed: %s", exc)
        return {"ok": False, "message": str(exc)}


async def get_mood_streak() -> dict[str, Any]:
    """Consecutive days with a diary entry+mood from today backwards."""
    try:
        async with session_factory()() as db:
            res = await db.execute(
                select(DiaryEntry.entry_date).where(
                    DiaryEntry.entry_date.is_not(None),
                    DiaryEntry.mood.is_not(None),
                )
            )
            dated = {row[0].date() for row in res.all()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("mood streak query failed: %s", exc)
        return {"ok": False, "message": str(exc), "streak": 0}

    streak = 0
    d = _today()
    while d in dated:
        streak += 1
        d = d - timedelta(days=1)
    return {
        "ok": True,
        "streak": streak,
        "current_streak": streak,
        "today": _today().isoformat(),
    }


async def get_streak_calendar(days: int = 84) -> dict[str, Any]:
    """Return a compact day-by-day journal heatmap for the frontend."""
    days = max(28, min(int(days), 366))
    today = _today()
    start = today - timedelta(days=days - 1)
    entries: dict[date, dict[str, Any]] = {}
    try:
        async with session_factory()() as db:
            rows = (await db.execute(
                select(DiaryEntry).where(
                    DiaryEntry.entry_date >= datetime(start.year, start.month, start.day),
                    DiaryEntry.entry_date < datetime(today.year, today.month, today.day) + timedelta(days=1),
                )
            )).scalars().all()
            for row in rows:
                if row.entry_date:
                    day = row.entry_date.date() if isinstance(row.entry_date, datetime) else row.entry_date
                    entries[day] = {
                        "mood": row.mood,
                        "complete": bool(row.complete),
                        "word_count": row.word_count or 0,
                    }
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("streak calendar query failed: %s", exc)
    calendar = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        meta = entries.get(day, {})
        file_exists = read_entry_file(day).get("found", False)
        calendar.append({
            "date": day.isoformat(),
            "has_entry": bool(meta or file_exists),
            "mood": meta.get("mood"),
            "complete": meta.get("complete", False),
            "word_count": meta.get("word_count", 0),
        })
    return {"ok": True, "today": today.isoformat(), "days": calendar}


async def complete_day(date_str: str = "", complete: bool = True) -> dict[str, Any]:
    """Mark today's (or `date_str`'s) journal complete (plan.md §12.1).

    The Daily Journal Questionnaire calls this after all fixed questions are
    answered, or when writing the 23:55 placeholder. Sets
    `diary_entries.complete` and publishes `DailyJournalCompleted` (addendum
    §2.7) — Evening Review subscribes to that event.

    If no metadata row exists yet, it is created with complete set (the
    questionnaire's placeholder path, §2.6).

    When completing, the vault note is also enriched into an Obsidian/Quartz
    graph-friendly shape (frontmatter, prev/next navigation, `## Connected`
    block with wikilinks) so the daily entry is a well-linked node.
    """
    d = _parse_date(date_str or "")
    try:
        async with session_factory()() as db:
            start, end = _day_bounds(d)
            entry = (await db.execute(
                select(DiaryEntry)
                .where(DiaryEntry.entry_date >= start, DiaryEntry.entry_date < end)
                .order_by(DiaryEntry.created_at.desc())
            )).scalars().first()
            if entry is None:
                entry = DiaryEntry(
                    title=f"Journal {d.isoformat()}",
                    category="GENERAL",
                    vault_path=str(entry_path(d)),
                    entry_date=datetime(d.year, d.month, d.day),
                    complete=complete,
                )
                db.add(entry)
            else:
                entry.complete = complete
            await db.commit()
            entry_id = entry.id
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("complete_day metadata failed: %s", exc)
        return {"ok": False, "date": d.isoformat(), "message": str(exc)}

    enriched = False
    if complete:
        try:
            enriched = (await enrich_entry(d.isoformat())).get("enriched", False)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("complete_day enrich failed: %s", exc)

    publish(DAILY_JOURNAL_COMPLETED, {
        "date": d.isoformat(),
        "complete": bool(complete),
        "entry_id": entry_id,
    })
    return {
        "ok": True,
        "date": d.isoformat(),
        "complete": bool(complete),
        "entry_id": entry_id,
        "enriched": bool(complete) and enriched,
    }


# ─── spending analytics (read-only, web dashboard) ─────────────────────────

_SPEND_PERIODS = ("day", "week", "month", "year")


def _spend_buckets(period: str, today: date) -> list[tuple[date, date]]:
    """Return [(start, end_exclusive)] buckets for the trailing window of `period`.

    day   -> last 14 days (today..today-13)
    week  -> last 12 ISO weeks (Mon..Sun)
    month -> last 12 months (1st..1st of next)
    year  -> last 5 years
    """
    if period == "day":
        return [
            (today - timedelta(days=i), today - timedelta(days=i) + timedelta(days=1))
            for i in range(13, -1, -1)
        ]
    if period == "week":
        monday = today - timedelta(days=today.weekday())
        buckets = []
        for i in range(11, -1, -1):
            start = monday - timedelta(weeks=i)
            buckets.append((start, start + timedelta(days=7)))
        return buckets
    if period == "month":
        first = today.replace(day=1)
        buckets = []
        for i in range(11, -1, -1):
            y = first.year
            m = first.month - i
            while m <= 0:
                m += 12
                y -= 1
            start = date(y, m, 1)
            ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
            buckets.append((start, date(ny, nm, 1)))
        return buckets
    # year
    buckets = []
    for i in range(4, -1, -1):
        y = today.year - i
        buckets.append((date(y, 1, 1), date(y + 1, 1, 1)))
    return buckets


def _bucket_label(period: str, start: date) -> str:
    if period == "day":
        return start.isoformat()
    if period == "week":
        return start.isoformat()
    if period == "month":
        return start.strftime("%b %Y")
    return str(start.year)


async def spending_summary(period: str = "week") -> dict[str, Any]:
    """Aggregate spending into daily/weekly/monthly/yearly buckets (read-only).

    Returns trailing-window buckets with totals, the current period's total and
    change vs the previous bucket, and overall all-time stats for context.
    """
    period = (period or "week").strip().lower()
    if period not in _SPEND_PERIODS:
        return {"ok": False, "message": f"invalid period: {period!r} (choose day|week|month|year)"}
    today = _today()
    buckets = _spend_buckets(period, today)
    first = buckets[0][0]

    try:
        async with session_factory()() as db:
            rows = (await db.execute(
                select(Spending)
                .where(Spending.date >= datetime(first.year, first.month, first.day))
                .order_by(Spending.date.asc())
            )).scalars().all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("spending summary failed: %s", exc)
        return {"ok": False, "message": str(exc)}

    series = []
    for start, end in buckets:
        total = 0.0
        count = 0
        for s in rows:
            sd = s.date.date() if isinstance(s.date, datetime) else s.date
            if start <= sd < end:
                total += float(s.amount)
                count += 1
        series.append({"label": _bucket_label(period, start), "total": round(total, 2), "count": count})

    current = series[-1]
    previous = series[-2] if len(series) > 1 else None
    change_pct = None
    if previous is not None and previous["total"]:
        change_pct = round((current["total"] - previous["total"]) / previous["total"] * 100, 1)
    elif previous is not None:
        change_pct = 100.0 if current["total"] else 0.0

    total_all = round(sum(s["total"] for s in series), 2)
    count_all = sum(s["count"] for s in series)

    return {
        "ok": True,
        "period": period,
        "buckets": series,
        "current": current,
        "previous": previous,
        "change_pct": change_pct,
        "total": total_all,
        "count": count_all,
        "avg_per_bucket": round(total_all / len(series), 2) if series else 0.0,
    }


async def spending_analysis() -> dict[str, Any]:
    """Category breakdown, trends and spending habits (read-only).

    - categories: totals + share per category (fixed taxonomy)
    - largest: single biggest transaction
    - monthly_trend: last 6 calendar months totals
    - weekday_spend: total by weekday (0=Mon)
    - habits: derived observations (top category, avg txn, repeat frequency)
    """
    try:
        async with session_factory()() as db:
            rows = (await db.execute(select(Spending))).scalars().all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("spending analysis failed: %s", exc)
        return {"ok": False, "message": str(exc)}

    if not rows:
        return {
            "ok": True,
            "total": 0.0,
            "count": 0,
            "avg_transaction": 0.0,
            "categories": [],
            "largest": None,
            "monthly_trend": [],
            "weekday_spend": [],
            "habits": ["No spending logged yet — capture expenses to see trends."],
        }

    total = 0.0
    by_cat: dict[str, dict[str, Any]] = {}
    largest = None
    monthly: dict[str, float] = {}
    weekday: dict[str, float] = {}

    for s in rows:
        amt = float(s.amount)
        sd = s.date.date() if isinstance(s.date, datetime) else s.date
        cat = s.category or "Other"
        total += amt
        c = by_cat.setdefault(cat, {"total": 0.0, "count": 0})
        c["total"] += amt
        c["count"] += 1
        if largest is None or amt > largest["amount"]:
            largest = {"amount": amt, "category": cat, "date": sd.isoformat()}
        monthly[f"{sd.year}-{sd.month:02d}"] = monthly.get(f"{sd.year}-{sd.month:02d}", 0.0) + amt
        wd = sd.strftime("%a")
        weekday[wd] = weekday.get(wd, 0.0) + amt

    categories = sorted(
        [
            {
                "category": k,
                "total": round(v["total"], 2),
                "count": v["count"],
                "share_pct": round(v["total"] / total * 100, 1) if total else 0.0,
            }
            for k, v in by_cat.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )

    monthly_trend = [
        {"month": k, "total": round(v, 2)}
        for k, v in sorted(monthly.items())[-6:]
    ]

    weekday_spend = [
        {"day": d, "total": round(weekday.get(d, 0.0), 2)}
        for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    ]

    count = len(rows)
    avg = total / count if count else 0.0
    top = categories[0] if categories else None

    habits: list[str] = []
    if top and top["share_pct"] >= 30:
        habits.append(f"{top['category']} dominates spending at {top['share_pct']}% of total.")
    if len(categories) >= 3:
        habits.append(f"{len(categories)} categories active; largest is {categories[0]['category']}.")
    habits.append(f"Average transaction is ₹{avg:,.0f} across {count} logged expenses.")
    if largest:
        habits.append(f"Biggest single expense: ₹{largest['amount']:,.0f} on {largest['date']} ({largest['category']}).")
    if monthly_trend:
        first_m = monthly_trend[0]["total"]
        last_m = monthly_trend[-1]["total"]
        if first_m and last_m:
            trend = (last_m - first_m) / first_m * 100
            habits.append(f"Monthly spending moved {trend:+.0f}% across the last 6 months.")
    weekday_sorted = sorted(weekday_spend, key=lambda x: x["total"], reverse=True)
    if weekday_sorted and weekday_sorted[0]["total"] > 0:
        habits.append(f"Highest spending day: {weekday_sorted[0]['day']}.")

    return {
        "ok": True,
        "total": round(total, 2),
        "count": count,
        "avg_transaction": round(avg, 2),
        "categories": categories,
        "largest": largest,
        "monthly_trend": monthly_trend,
        "weekday_spend": weekday_spend,
        "habits": habits,
    }


async def spending_transactions(limit: int = 50) -> dict[str, Any]:
    """Recent spending transactions, newest first (read-only)."""
    limit = max(1, min(int(limit), 500))
    try:
        async with session_factory()() as db:
            rows = (await db.execute(
                select(Spending).order_by(Spending.date.desc()).limit(limit)
            )).scalars().all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("spending transactions failed: %s", exc)
        return {"ok": False, "message": str(exc)}

    return {
        "ok": True,
        "transactions": [
            {
                "id": s.id,
                "date": (s.date.date() if isinstance(s.date, datetime) else s.date).isoformat(),
                "amount": float(s.amount),
                "category": s.category or "Other",
                "raw_text": s.raw_text,
            }
            for s in rows
        ],
    }
