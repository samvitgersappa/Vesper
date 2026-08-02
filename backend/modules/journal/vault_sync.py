"""Vault sync handler — `diary_entries` metadata over Obsidian vault notes.

plan.md §8.3: content lives in the vault file at `vault_path`; this handler
keeps the `diary_entries` row (mood/tags/word_count/calendar) in sync with the
file. Invoked by the vault watcher, or on `KnowledgeIndexed` events, for any
changed vault path that lives under `<vault>/00 Journal/` (or the legacy
`<vault>/journal/` layout).

Metadata is derived deterministically from the markdown file (first line title,
YAML frontmatter mood/tags if present); the row is upserted, or removed when the
file was deleted. Emits `JournalCreated` on the bus for new entries.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import delete, select

from backend.db.postgres.schemas.journal.models import DiaryEntry
from backend.events.catalog import JOURNAL_CREATED
from backend.modules.common import publish
from backend.modules.db import session_factory
from backend.modules.journal.vault import vault_root

# Current layout: <vault>/00 Journal/YYYY/YYYY-MM-DD.md
# Legacy layout:  <vault>/journal/YYYY/MM/YYYY-MM-DD.md (kept for reads).
_JOURNAL_DIRS = ("00 Journal", "journal")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_MOOD_RE = re.compile(r"^mood\s*[:=]\s*['\"]?([^'\"]+?)['\"]?\s*$", re.MULTILINE)
_TAGS_RE = re.compile(r"^tags\s*[:=]\s*\[([^\]]*)\]\s*$", re.MULTILINE)


def _is_journal_path(root: Path, path: Path) -> bool:
    try:
        rp = str(path.resolve())
        return any(
            rp.startswith(str((root / d).resolve()))
            for d in _JOURNAL_DIRS
        )
    except OSError:  # pragma: no cover - defensive
        return False


def _date_from_path(path: Path) -> datetime | None:
    """Date from a journal filename like YYYY-MM-DD.md (any layout)."""
    try:
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})\.md$", path.name)
        if not match:
            return None
        y, m, d = (int(x) for x in match.groups())
        return datetime(y, m, d)
    except ValueError:
        return None


def _parse_frontmatter(text: str) -> tuple[str, list[str]]:
    """Return (mood, tags) from a note's YAML frontmatter, empty when absent."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return "", []
    fm = match.group(1)
    mood_m = _MOOD_RE.search(fm)
    mood = mood_m.group(1).strip() if mood_m else ""
    tags_m = _TAGS_RE.search(fm)
    tags: list[str] = []
    if tags_m:
        raw = tags_m.group(1)
        tags = [t.strip().strip("'\"") for t in raw.split(",") if t.strip()]
    return mood, tags


def _first_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
        if line:
            return line.strip()
    return ""


async def _upsert(d: datetime, path: str, title: str, mood: str, tags: list[str], word_count: int) -> bool:
    """Upsert the `diary_entries` row for the entry date; return created."""
    try:
        async with session_factory()() as db:
            res = await db.execute(
                select(DiaryEntry)
                .where(DiaryEntry.entry_date >= datetime(d.year, d.month, d.day),
                       DiaryEntry.entry_date < datetime(d.year, d.month, d.day + 1))
                .order_by(DiaryEntry.created_at.desc())
            )
            e = res.scalars().first()
            created = False
            if e is None:
                e = DiaryEntry(
                    title=title or None,
                    vault_path=path,
                    mood=mood or None,
                    tags=list(tags) or None,
                    word_count=word_count,
                    entry_date=d,
                )
                db.add(e)
                created = True
            else:
                e.title = title or e.title
                e.vault_path = path
                if mood:
                    e.mood = mood
                if tags:
                    e.tags = list(tags)
                e.word_count = word_count
            await db.commit()
            return created
    except Exception as exc:  # pragma: no cover - defensive
        return False


async def _remove(d: datetime) -> None:
    try:
        async with session_factory()() as db:
            res = await db.execute(
                delete(DiaryEntry)
                .where(DiaryEntry.entry_date >= datetime(d.year, d.month, d.day),
                       DiaryEntry.entry_date < datetime(d.year, d.month, d.day + 1))
            )
            await db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        pass


async def sync_vault_changes(changed_paths: Iterable[str]) -> dict:
    """Upsert/remove `diary_entries` metadata for changed vault paths.

    Only paths under `<vault>/journal/` are journal entries; everything else is
    ignored (a note owned by the Knowledge module).
    """
    root = vault_root()
    if not root.exists():
        return {"handler": "journal.vault_sync", "status": "vault_missing"}

    created = 0
    updated = 0
    removed = 0
    ignored = 0
    for raw in changed_paths:
        p = Path(raw)
        if not _is_journal_path(root, p):
            ignored += 1
            continue
        d = _date_from_path(p)
        if d is None:
            ignored += 1
            continue
        if not p.exists():
            await _remove(d)
            removed += 1
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            ignored += 1
            continue
        mood, tags = _parse_frontmatter(text)
        title = _first_title(text)
        word_count = len(text.split())
        was_created = await _upsert(d, str(p), title, mood, tags, word_count)
        if was_created:
            created += 1
            publish(JOURNAL_CREATED, {"entry_id": None, "date": d.strftime("%Y-%m-%d"), "path": str(p)})
        else:
            updated += 1

    return {
        "handler": "journal.vault_sync",
        "status": "ok",
        "created": created,
        "updated": updated,
        "removed": removed,
        "ignored": ignored,
    }
