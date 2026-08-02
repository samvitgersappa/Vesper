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
from typing import Any, Optional

from sqlalchemy import select

from backend.db.postgres.schemas.journal.models import DiaryEntry, Spending, Workout
from backend.modules.common import publish
from backend.modules.db import session_factory
from backend.modules.journal.vault import (
    entry_path,
    read_entry_file,
    vault_root,
    write_entry_file,
)
from backend.events.catalog import DAILY_JOURNAL_COMPLETED, JOURNAL_CREATED

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
    return f"# {d.isoformat()}\n\n{body}"


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
    file_res = write_entry_file(d, _build_content(d, body, append), append=append)
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
    publish(JOURNAL_CREATED, {
        "entry_id": meta.get("entry_id"),
        "date": d.isoformat(),
        "path": file_res["path"],
        "appended": file_res["appended"],
        "mood": (mood or "").strip(),
        "word_count": file_res["word_count"],
    })
    return {
        "ok": True,
        "entry_id": meta.get("entry_id"),
        "date": d.isoformat(),
        "path": file_res["path"],
        "appended": file_res["appended"],
        "mood": (mood or "").strip(),
        "word_count": file_res["word_count"],
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


async def complete_day(date_str: str = "", complete: bool = True) -> dict[str, Any]:
    """Mark today's (or `date_str`'s) journal complete (plan.md §12.1).

    The Daily Journal Questionnaire calls this after all fixed questions are
    answered, or when writing the 23:55 placeholder. Sets
    `diary_entries.complete` and publishes `DailyJournalCompleted` (addendum
    §2.7) — Evening Review subscribes to that event.

    If no metadata row exists yet, it is created with complete set (the
    questionnaire's placeholder path, §2.6).
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
    }
