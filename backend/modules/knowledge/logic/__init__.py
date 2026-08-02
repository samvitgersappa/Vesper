"""Knowledge module business logic — universal capture & second-brain recall.

Implements plan.md §4.1/§9 and ADDENDUM_SECOND_BRAIN.md §1: a single
capture-routing decision point (`knowledge_capture`) plus vault search, unified
recall fan-out, note correction (update/delete), and entity linking.

All routing is deterministic best-effort heuristics — no LLM here. The
model-escalation / Knowledge Architect pass runs in Hermes skills/workers on
top of these tools. Every capture writes a `hermes.capture_routing_log` row
(rule 8) so "where did this actually go" is always auditable.

Vault writes publish `KnowledgeIndexed` on the event bus; DB writes go through
the shared async session factory. Everything degrades gracefully when the vault
or DB is unavailable.
"""

import asyncio
import logging
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from backend.db.postgres.schemas.hermes.models import CaptureRoutingLog
from backend.db.postgres.schemas.journal.models import DiaryEntry, Spending, Workout
from backend.db.postgres.schemas.relationship.models import Reminder
from backend.events.catalog import KNOWLEDGE_INDEXED
from backend.modules.common import publish
from backend.modules.db import session_factory

logger = logging.getLogger("vesper.knowledge")

# ─── Vault resolution & walking ────────────────────────────────────────────


def vault_root() -> Path:
    """Resolve the vault root from env (default ~/Documents/KnowledgeVault)."""
    raw = os.environ.get("HERMES_VAULT_PATH", "~/Documents/KnowledgeVault")
    return Path(raw).expanduser().resolve()


def _walk_vault_files(root: Path) -> list[Path]:
    """Walk the vault for markdown notes, skipping dot/template/archive/asset dirs."""
    notes: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and "template" not in d.lower()
            and "archive" not in d.lower()
            and "attachment" not in d.lower()
            and "asset" not in d.lower()
        ]
        for f in filenames:
            if f.startswith(".") or not f.endswith(".md"):
                continue
            notes.append(Path(dirpath) / f)
    return notes


def _extract_title(content: str, fallback: str) -> str:
    """Title from YAML frontmatter, else first H1, else filename."""
    fm = re.match(r"^---\s*\n(.*?)\n---\s*", content, re.S)
    if fm:
        m = re.search(r"^title:\s*(.+)$", fm.group(1), re.M | re.I)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    m = re.search(r"^#\s+(.+)$", content, re.M)
    if m:
        return m.group(1).strip()
    return fallback


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _body_only(content: str) -> str:
    m = re.match(r"^---\s*\n.*?\n---\s*\n?", content, re.S)
    if m:
        content = content[m.end():]
    return content.strip()


def _preview(content: str, query: str = "") -> str:
    body = _body_only(content)
    q = query.strip().lower()
    if q:
        idx = body.lower().find(q)
        if idx == -1:
            for tok in _tokens(q):
                i = body.lower().find(tok)
                if i != -1:
                    idx = i
                    break
        if idx > 0:
            body = body[max(0, idx - 80):]
    body = re.sub(r"\s+", " ", body)
    return body[:280] + ("…" if len(body) > 280 else "")


def _rank_notes(notes: list[Path], query: str, top_k: int) -> list[dict[str, Any]]:
    qtokens = _tokens(query)
    scored: list[tuple[float, Path, str, str]] = []
    root = vault_root()
    for path in notes:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(content) > 20000:
            content = content[:20000]
        title = _extract_title(content, path.stem)
        ctext = f"{path.name} {path.stem} {title} {content}".lower()
        ctokens = _tokens(ctext)
        score = float(len(qtokens & ctokens))
        for t in qtokens:
            if t in ctext:
                score += 0.5
        if query.strip().lower() in path.stem.lower():
            score += 2.0
        if score <= 0:
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        scored.append((score, rel, title, _preview(content, query)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"file_path": str(rel), "title": title, "content_preview": preview}
        for _, rel, title, preview in scored[:top_k]
    ]


# ─── Capture routing heuristics (plan.md §4.1) ─────────────────────────────

_CURRENCY_RE = re.compile(
    r"(?:[₹$€£]\s*|Rs\.?\s*|INR\s*)?(\d+(?:[,.]\d{1,2})?)", re.I
)

_EXPENSE_HINTS = [
    "spent", "spend", "spending", "paid", "paying", "cost", "cost me", "costs",
    "bought", "buy", "bill", "bills", "billed", "recharge", "shopping",
    "purchased", "expense", "on lunch", "on dinner", "on food", "on breakfast",
    "on coffee", "on tea", "on the cab", "on a cab", "on the taxi", "on a taxi",
    "on uber", "on ola", "on the auto", "on the metro", "on the bus",
    "on the train", "on fuel", "on petrol", "on grocery", "on groceries",
    "on the bill", "for lunch", "for dinner", "for the cab", "for the taxi",
    "for the bill", "for coffee", "for food",
]
_EXPENSE_RE = re.compile("|".join(re.escape(h) for h in _EXPENSE_HINTS), re.I)

_CATEGORY_RULES = [
    ("Food", ["lunch", "dinner", "breakfast", "food", "eat", "restaurant", "cafe",
              "coffee", "tea", "grocery", "groceries", "zomato", "swiggy", "snack",
              "biryani", "pizza", "burger", "meat", "chicken", "sweets", "cook"]),
    ("Travel/Transport", ["cab", "uber", "ola", "auto", "metro", "bus", "train",
                          "taxi", "fuel", "petrol", "diesel", "toll", "parking",
                          "flight", "travel", "commute", "airfare", "transport"]),
    ("Shopping", ["shopping", "bought", "purchase", "amazon", "flipkart", "shirt",
                  "jeans", "shoes", "clothes", "watch", "phone", "laptop", "gadget",
                  "furniture", "new"]),
    ("Bills/Utilities", ["bill", "bills", "electricity", "internet", "wifi", "rent",
                         "emi", "subscription", "recharge", "mobile", "utilities",
                         "water", "cable", "dth"]),
    ("Health", ["health", "medicine", "doctor", "gym", "pharmacy", "hospital",
                "medical", "dentist", "clinic", "vitamin", "protein"]),
    ("Entertainment", ["movie", "movies", "tickets", "netflix", "spotify", "gaming",
                       "game", "games", "concert", "show", "books", "prime", "ott"]),
]

_WORKOUT_VERBS = [
    "workout", "worked out", "work out", "gym", "training", "trained", "ran",
    "running", "run", "jog", "jogging", "sprint", "lifting", "lifted", "lift",
    "squat", "squats", "bench", "deadlift", "deadlifts", "cardio", "swim",
    "swimming", "yoga", "pilates", "zumba", "cycling", "cycle", "spin", "hike",
    "hiking", "pull-up", "pullups", "push-up", "pushups", "plank", "planks",
    "exercise", "exercising", "stretch", "stretching", "walk", "walking",
]
_WORKOUT_MUSCLE_PHRASES = [
    "leg day", "chest day", "back day", "shoulder day", "arm day", "abs day",
    "did legs", "did chest", "did back", "did arms", "did shoulders", "hit legs",
    "hit chest", "hit back", "hit arms", "hit shoulders", "trained legs",
    "trained chest", "trained back", "trained arms", "worked legs", "worked chest",
    "worked back", "worked arms", "leg press", "squat rack", "push day", "pull day",
]
_MUSCLE_WORDS = [
    "legs", "chest", "back", "shoulders", "shoulder", "arms", "biceps", "triceps",
    "abs", "core", "glutes", "hamstrings", "quads", "calves", "lats", "traps",
    "forearms",
]

_JOURNAL_WORDS = [
    "today", "tonight", "mood", "feeling", "feel", "felt", "day was", "my day",
    "tired", "exhausted", "happy", "sad", "anxious", "excited", "stressed",
    "meh", "great day", "bad day", "good day", "rough", "lazy", "productive",
    "busy day", "reflect", "reflection", "thoughts", "journal", "grateful",
    "thankful", "sleep", "slept", "insomnia", "long day", "what a day",
]

_IDEA_WORDS = [
    "idea", "a book", "book called", "book titled", "book title", "the book",
    "an article", "article", "a paper", "paper", "a podcast", "podcast",
    "a fact", "fact", "did you know", "a concept", "concept", "a quote", "quote",
    "recipe", "a reference", "reference", "remember this fact", "noted",
    "found out", "learned that", "read that", "came across", "a thought",
    "standalone", "a note", "note this", "an idea", "remember this idea",
]

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}
_MONTH_RE = "|".join(_MONTHS.keys())
_MONTH_DAY_RE = re.compile(rf"\b({_MONTH_RE})[a-z]*\.?\s+(\d{{1,2}})\b", re.I)
_DAY_MONTH_RE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_RE})[a-z]*\.?\b", re.I)
_TIME_PATTERNS = [
    (r"\b(in|within)\s+(\d+)\s*(minute|minutes|min|hour|hours|hr|hrs|day|days|week|weeks|month|months)\b", "rel"),
    (r"\btomorrow\b", "tomorrow"),
    (r"\btonight\b", "tonight"),
    (r"\bnext\s+week\b", "nextweek"),
    (r"\bnext\s+month\b", "nextmonth"),
    (r"\bon\s+the\s+(\d{1,2})(st|nd|rd|th)?\b", "monthday"),
    (r"\b(\d{1,2})(st|nd|rd|th)\b", "ordinal"),
    (r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "weekday"),
    (r"\b(at|by)\s+(\d{1,2})(:\d{2})?\s*(am|pm)?\b", "time"),
]
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _now() -> datetime:
    """Offset-naive UTC now (Postgres TIMESTAMP WITHOUT TIME ZONE compat)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _monthday_dt(day: int, now: datetime) -> Optional[datetime]:
    """Next occurrence of `day` (this month if still ahead, else next month) at 09:00."""
    if day < 1 or day > 31:
        return None
    try:
        cand = datetime(now.year, now.month, day, 9, 0)
    except ValueError:
        return None
    if cand <= now:
        try:
            if now.month == 12:
                cand = datetime(now.year + 1, 1, day, 9, 0)
            else:
                cand = datetime(now.year, now.month + 1, day, 9, 0)
        except ValueError:
            return None
    return cand


def _named_month_dt(month: int, day: int, now: datetime) -> Optional[datetime]:
    """Next occurrence of a named month/day (this year if still ahead, else next)."""
    if month < 1 or month > 12 or day < 1 or day > 31:
        return None
    try:
        cand = datetime(now.year, month, day, 9, 0)
    except ValueError:
        return None
    if cand <= now:
        try:
            cand = datetime(now.year + 1, month, day, 9, 0)
        except ValueError:
            return None
    return cand


def _parse_due(utterance: str) -> Optional[datetime]:
    """Parse an explicit date/time out of the utterance, else None (rule 1)."""
    now = datetime.now()
    low = utterance.lower()
    for pat, kind in _TIME_PATTERNS:
        m = re.search(pat, low)
        if not m:
            continue
        if kind == "rel":
            n = int(m.group(2))
            unit = m.group(3)
            if unit.startswith("minute") or unit == "min":
                return now + timedelta(minutes=n)
            if unit.startswith("hour") or unit.startswith("hr"):
                return now + timedelta(hours=n)
            if unit.startswith("day"):
                return now + timedelta(days=n)
            if unit.startswith("week"):
                return now + timedelta(weeks=n)
            return now + timedelta(days=30 * n)
        if kind == "tomorrow":
            d = now.date() + timedelta(days=1)
            return datetime(d.year, d.month, d.day, 9, 0)
        if kind == "tonight":
            return datetime(now.year, now.month, now.day, 21, 0)
        if kind == "nextweek":
            d = now.date() + timedelta(days=7)
            return datetime(d.year, d.month, d.day, 9, 0)
        if kind == "nextmonth":
            d = now.date() + timedelta(days=30)
            return datetime(d.year, d.month, d.day, 9, 0)
        if kind == "monthday":
            return _monthday_dt(int(m.group(1)), now)
        if kind == "ordinal":
            return _monthday_dt(int(m.group(1)), now)
        if kind == "weekday":
            target = _WEEKDAYS[m.group(1)]
            delta = (target - now.weekday()) % 7
            if delta == 0:
                delta = 7
            d = now.date() + timedelta(days=delta)
            return datetime(d.year, d.month, d.day, 9, 0)
        if kind == "time":
            hour = int(m.group(2))
            ampm = m.group(4)
            minute = int(m.group(3)[1:]) if m.group(3) else 0
            if ampm:
                ampm = ampm.lower()
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
            t = datetime(now.year, now.month, now.day, hour, minute)
            if t <= now:
                t += timedelta(days=1)
            return t
    m = _MONTH_DAY_RE.search(utterance)
    if m:
        return _named_month_dt(_MONTHS[m.group(1).lower()[:3]], int(m.group(2)), now)
    m = _DAY_MONTH_RE.search(utterance)
    if m:
        return _named_month_dt(_MONTHS[m.group(2).lower()[:3]], int(m.group(1)), now)
    return None


def _reminder_title(utterance: str) -> str:
    """Title for a Reminder row: the "to <do X>" clause or stripped utterance."""
    low = utterance.lower()
    m = re.search(r"\b(?:remind me to|remember to|don'?t let me forget to|dont let me forget to)\s+(.+)$", low)
    if m:
        title = m.group(1)
    else:
        title = re.sub(
            r"^(remind me|remind|remember|don'?t let me forget|dont let me forget)[,:]?\s*",
            "", utterance, flags=re.I,
        )
    title = re.sub(
        r"\s*(in|within)\s+\d+\s*(minute|hour|day|week|month)s?\b.*$", "", title, flags=re.I
    )
    title = re.sub(r"\bon\s+the\s+\d{1,2}(st|nd|rd|th)?\b.*$", "", title, flags=re.I)
    title = re.sub(r"\btomorrow\b.*$", "", title, flags=re.I)
    title = re.sub(r"^\s*to\s+", "", title)
    return title.strip()[:200] or utterance.strip()[:200]


def _amounts(utterance: str) -> list[str]:
    """Currency-like amounts that sit near an expense signal."""
    out: list[str] = []
    for m in _CURRENCY_RE.finditer(utterance):
        num = m.group(1).replace(",", "")
        if not re.search(r"[₹$€£]|Rs\.?|INR", m.group(0)) and num.isdigit():
            if 1900 <= int(num) <= 2100:
                continue  # year-like number, not an amount
        start = max(0, m.start() - 25)
        end = min(len(utterance), m.end() + 25)
        window = utterance[start:end]
        has_signal = (
            bool(re.search(r"[₹$€£]|Rs\.?|INR", window, re.I))
            or bool(re.search(
                r"\b(spent|spend|paid|paying|cost|bought|buy|bill|billed|recharge|shopping|purchased|expense)\b",
                window, re.I,
            ))
            or bool(re.search(r"\bon\s+(the\s+)?[a-z]", window, re.I))
        )
        if has_signal:
            out.append(num)
    return out


def _looks_like_expense(utterance: str) -> bool:
    if not _amounts(utterance):
        return False
    return bool(_EXPENSE_RE.search(utterance)) or bool(
        re.search(r"[₹$€£]|Rs\.?\s|INR\s", utterance, re.I)
    )


def _categorize_spending(utterance: str) -> str:
    low = utterance.lower()
    for category, words in _CATEGORY_RULES:
        for w in words:
            if re.search(r"\b" + re.escape(w) + r"\b", low):
                return category
    return "Other"


def _workout_word(utterance: str) -> Optional[str]:
    low = utterance.lower()
    for w in _WORKOUT_VERBS:
        if re.search(r"\b" + re.escape(w) + r"\b", low):
            return w
    for w in _WORKOUT_MUSCLE_PHRASES:
        if w in low:
            return w
    for w in ["legs", "chest", "back", "shoulders", "arms", "biceps", "triceps", "abs", "core", "glutes", "quads", "hamstrings", "calves"]:
        if re.search(r"\b(did|hit|trained|worked|work)\s+" + re.escape(w) + r"\b", low):
            return w
    return None


def _muscle_groups(utterance: str) -> list[str]:
    low = utterance.lower()
    found: list[str] = []
    for w in _MUSCLE_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", low) and w not in found:
            found.append(w)
    return found


def _has_journal_signal(utterance: str) -> bool:
    low = utterance.lower()
    return any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in _JOURNAL_WORDS)


def _has_idea_signal(utterance: str) -> bool:
    low = utterance.lower()
    if "no idea" in low:
        return False
    if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in _IDEA_WORDS):
        return True
    return bool(re.search(r"[\"“'‘][^\"”'‘]{3,60}[\"”'‘]", utterance))


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "note"


def _title_from_utterance(utterance: str) -> str:
    q = re.search(r"[\"“'‘]([^\"”'‘]{3,60})[\"”'‘]", utterance)
    if q:
        return q.group(1).strip()
    m = re.search(
        r"\b(?:a book|book called|book titled|an article|a paper|a podcast|a fact|a concept|an idea)\s+(?:called |titled |about )?(.+)$",
        utterance, re.I,
    )
    if m:
        t = m.group(1).strip().rstrip(".!")
        if len(t) <= 60:
            return t
    return utterance.strip().rstrip(".!")[:60]


# ─── DB writes (rule 1-3, 8) ───────────────────────────────────────────────


async def _insert_reminder(utterance: str, due: datetime) -> Optional[str]:
    title = _reminder_title(utterance)
    try:
        async with session_factory()() as db:
            r = Reminder(title=title, body=utterance, due_at=due, reminder_type="capture")
            db.add(r)
            await db.commit()
            return r.id
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("reminder insert failed: %s", exc)
        return None


async def _insert_spending(utterance: str) -> Optional[str]:
    amounts = _amounts(utterance) or ["0"]
    category = _categorize_spending(utterance)
    try:
        async with session_factory()() as db:
            rows = []
            for amt in amounts:
                s = Spending(
                    date=datetime.now(),
                    amount=float(amt),
                    category=category,
                    raw_text=utterance,
                )
                db.add(s)
                rows.append(s)
            await db.commit()
            return rows[0].id if rows else None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("spending insert failed: %s", exc)
        return None


async def _insert_workout(utterance: str) -> Optional[str]:
    activity = _workout_word(utterance) or "workout"
    muscles = _muscle_groups(utterance)
    try:
        async with session_factory()() as db:
            w = Workout(date=datetime.now(), activity=activity, muscle_groups=muscles, raw_text=utterance)
            db.add(w)
            await db.commit()
            return w.id
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("workout insert failed: %s", exc)
        return None


async def _log_routing(
    utterance: str,
    ctx: dict,
    stored_in: str,
    ref_id: Optional[str],
    confidence: float,
    rule: Optional[str],
) -> None:
    """Rule 8 — mirror every capture decision to hermes.capture_routing_log."""
    try:
        async with session_factory()() as db:
            row = CaptureRoutingLog(
                ts=_now(),
                utterance=utterance,
                conversation_context=ctx or {},
                stored_in=stored_in,
                ref_id=ref_id,
                confidence=confidence,
                rule_fired=rule,
                raw_json={"stored_in": stored_in, "rule_fired": rule, "ref_id": ref_id},
            )
            db.add(row)
            await db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("capture routing log write failed: %s", exc)


# ─── Vault writes (rules 4-6) ──────────────────────────────────────────────


def _today_journal_path(root: Path) -> Path:
    today = date.today()
    return root / "00 Journal" / str(today.year) / f"{today.isoformat()}.md"


async def _append_journal(utterance: str, flagged: bool = False) -> Optional[str]:
    """Rule 4/7 — append a timestamped line to today's vault journal entry."""
    root = vault_root()
    if not root.exists():
        return None
    path = _today_journal_path(root)

    def _write() -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H:%M")
        line = f"- **{stamp}** {utterance.strip()}"
        if flagged:
            line += " *(flagged: ambiguous — consider refiling)*"
        if path.exists():
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n" + line + "\n")
        else:
            today = date.today()
            content = (
                "---\n"
                f"title: {today.isoformat()}\n"
                "type: journal\n"
                "status: draft\n"
                "tags: []\n"
                "confidence: 1.0\n"
                "---\n\n"
                f"# {today.strftime('%B %d, %Y')}\n\n"
                f"{line}\n"
            )
            path.write_text(content, encoding="utf-8")
        return str(path.relative_to(root))

    try:
        rel = await asyncio.to_thread(_write)
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("journal append failed: %s", exc)
        return None
    publish(KNOWLEDGE_INDEXED, {"path": str(path), "action": "journal_append"})
    return rel


async def _create_vault_note(utterance: str) -> Optional[str]:
    """Rule 5 — new note under 03 Knowledge/ with frontmatter + body."""
    root = vault_root()
    if not root.exists():
        return None
    title = _title_from_utterance(utterance)
    slug = _slugify(title)
    path = root / "03 Knowledge" / f"{slug}.md"
    if path.exists():
        path = root / "03 Knowledge" / f"{slug}-{date.today().isoformat()}.md"
    body = utterance.strip()

    def _write() -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "---\n"
            f"title: {title}\n"
            f"slug: {slug}\n"
            "type: note\n"
            "status: draft\n"
            "tags: []\n"
            "confidence: 1.0\n"
            "---\n\n"
            f"## The Idea\n\n{body}\n\n"
            "## Related\n\n\n"
            "## Notes\n\n"
            f"- Captured via knowledge.capture on {date.today().isoformat()}.\n"
        )
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(root))

    try:
        rel = await asyncio.to_thread(_write)
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("vault note create failed: %s", exc)
        return None
    publish(KNOWLEDGE_INDEXED, {"path": str(path), "action": "vault_note"})
    return rel


async def _create_image_note(utterance: str, image_path: str) -> Optional[str]:
    """Rule 6 — copy image into the vault and create a linked note."""
    root = vault_root()
    if not root.exists():
        return None
    src = Path(image_path)
    image_dir = root / "99 Assets" / "images"
    title = _title_from_utterance(utterance) if utterance.strip() else f"Image {datetime.now():%Y%m%d-%H%M%S}"
    slug = _slugify(title)
    note_path = root / "03 Knowledge" / f"{slug}.md"
    if note_path.exists():
        note_path = root / "03 Knowledge" / f"{slug}-{date.today().isoformat()}.md"

    def _write() -> str:
        image_dir.mkdir(parents=True, exist_ok=True)
        fname = src.name if src.name else f"{slug}.png"
        dest = image_dir / fname
        if src.exists() and src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        content = (
            "---\n"
            f"title: {title}\n"
            f"slug: {slug}\n"
            "type: image_note\n"
            "status: draft\n"
            "tags: [image]\n"
            "confidence: 1.0\n"
            "---\n\n"
            f"![[{fname}]]\n\n"
            f"## Description\n\n{utterance.strip()}\n"
        )
        note_path.write_text(content, encoding="utf-8")
        return str(note_path.relative_to(root))

    try:
        rel = await asyncio.to_thread(_write)
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("image note create failed: %s", exc)
        return None
    publish(KNOWLEDGE_INDEXED, {"path": str(note_path), "action": "image_note"})
    return rel


# ─── Public tools (async, exactly `knowledge_*` names) ─────────────────────


async def knowledge_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """Full-text search across the vault markdown files. No DB needed."""
    root = vault_root()
    if not root.exists():
        return {"query": query, "results": []}
    try:
        notes = await asyncio.to_thread(_walk_vault_files, root)
    except OSError:
        return {"query": query, "results": []}
    k = max(1, min(int(top_k), 20))
    results = await asyncio.to_thread(_rank_notes, notes, query, k)
    return {"query": query, "results": results}


async def knowledge_note_content(path: str) -> dict[str, Any]:
    """Return the full content of a vault note by path."""
    root = vault_root()
    if not root.exists():
        return {"file_path": path, "content": None, "exists": False, "message": "vault missing"}
    try:
        p = _resolve_note_path(path)
    except ValueError as exc:
        return {"file_path": path, "content": None, "exists": False, "message": str(exc)}
    if not p.exists() or not p.is_file():
        return {"file_path": path, "content": None, "exists": False}
    try:
        content = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - defensive
        return {"file_path": path, "content": None, "exists": False, "message": str(exc)}
    return {"file_path": str(p.relative_to(root)), "content": content, "exists": True}


async def knowledge_capture(
    utterance: str, conversation_context: Optional[dict] = None
) -> dict[str, Any]:
    """Universal capture-routing decision point (plan.md §4.1, rules 1-8).

    Deterministic heuristics, no LLM. Always mirrors the decision to
    hermes.capture_routing_log (rule 8).
    """
    ctx = conversation_context or {}
    rule: Optional[str] = None
    stored_in = "journal"
    confidence = 0.0
    ref_id: Optional[str] = None
    message = ""

    due = _parse_due(utterance)
    if due is not None:
        rule, stored_in = "rule1", "reminder"
        confidence = 0.9
        ref_id = await _insert_reminder(utterance, due)
        message = f"Saved reminder (due {due.isoformat(sep=' ', timespec='minutes')})."
    elif _looks_like_expense(utterance):
        rule, stored_in = "rule2", "expense"
        confidence = 0.9
        ref_id = await _insert_spending(utterance)
        message = f"Logged spending as {_categorize_spending(utterance)}."
    elif _workout_word(utterance) is not None:
        rule, stored_in = "rule3", "workout"
        confidence = 0.85
        ref_id = await _insert_workout(utterance)
        message = "Logged workout."
    else:
        image_path = ctx.get("image_path") or ctx.get("image") or ctx.get("imagePath")
        journal_signal = _has_journal_signal(utterance)
        idea_signal = _has_idea_signal(utterance)
        if journal_signal and not idea_signal:
            rule, stored_in = "rule4", "journal"
            confidence = 0.8
            ref_id = await _append_journal(utterance)
            message = "Appended to today's journal entry."
        elif idea_signal and not journal_signal:
            rule, stored_in = "rule5", "vault_note"
            confidence = 0.8
            ref_id = await _create_vault_note(utterance)
            message = "Created a vault note under 03 Knowledge/."
        elif image_path:
            rule, stored_in = "rule6", "image_note"
            confidence = 0.85
            ref_id = await _create_image_note(utterance, str(image_path))
            message = "Saved image and created a linked note."
        else:
            rule, stored_in = "rule7", "journal"
            confidence = 0.5
            ref_id = await _append_journal(utterance, flagged=True)
            message = (
                "Ambiguous between journal and vault note — appended to today's "
                "journal and flagged for the nightly Knowledge Architect pass."
            )

    await _log_routing(utterance, ctx, stored_in, ref_id, confidence, rule)

    return {
        "stored_in": stored_in,
        "ref_id": ref_id,
        "confidence": confidence,
        "rule_fired": rule,
        "message": message,
    }


async def knowledge_recall_everything(query: str) -> dict[str, Any]:
    """Fan-out recall: vault search + capture_routing_log + journal entries."""
    query = query or ""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        vault = await knowledge_search(query, top_k=5)
        for r in vault.get("results", []):
            key = r.get("file_path", "")
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "source": "vault",
                "content": r.get("content_preview", ""),
                "file_path": key,
                "title": r.get("title"),
            })
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("vault recall failed: %s", exc)

    # LanceDB semantic fan-out (addendum §3; degraded to empty without the index).
    try:
        from backend.db.lancedb_client import search as _lancedb_search

        for r in _lancedb_search(query, top_k=5, vault_root=str(vault_root())):
            key = r.get("file_path", "")
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "source": "lancedb",
                "content": r.get("title", ""),
                "file_path": key,
                "title": r.get("title"),
                "score": r.get("score"),
            })
    except Exception as exc:  # pragma: no cover
        logger.debug("lancedb recall failed: %s", exc)

    try:
        async with session_factory()() as db:
            res = await db.execute(
                select(CaptureRoutingLog)
                .where(CaptureRoutingLog.utterance.ilike(f"%{query}%"))
                .order_by(CaptureRoutingLog.ts.desc())
                .limit(10)
            )
            for row in res.scalars().all():
                results.append({
                    "source": "capture_log",
                    "content": row.utterance or "",
                    "stored_in": row.stored_in,
                    "ts": row.ts.isoformat() if row.ts else None,
                })
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("capture log recall failed: %s", exc)

    try:
        async with session_factory()() as db:
            res = await db.execute(
                select(DiaryEntry)
                .where(DiaryEntry.title.ilike(f"%{query}%"))
                .order_by(DiaryEntry.entry_date.desc())
                .limit(10)
            )
            for e in res.scalars().all():
                content = " ".join(
                    str(x) for x in [e.title, e.mood, f"tags={e.tags or []}"] if x
                ).strip()
                results.append({
                    "source": "journal",
                    "content": content,
                    "entry_date": e.entry_date.isoformat() if e.entry_date else None,
                })
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("journal recall failed: %s", exc)

    return {"query": query, "results": results}


async def knowledge_update_note(path: str, new_content: str) -> dict[str, Any]:
    """Overwrite a vault note atomically (temp file + rename)."""
    root = vault_root()
    if not root.exists():
        return {"ok": False, "file_path": path, "message": "vault missing"}
    try:
        p = _resolve_note_path(path)
    except ValueError as exc:
        return {"ok": False, "file_path": path, "message": str(exc)}
    if not p.parent.exists():
        return {"ok": False, "file_path": path, "message": "parent directory missing"}

    def _atomic_write() -> None:
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".vesper-tmp-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    try:
        await asyncio.to_thread(_atomic_write)
    except OSError as exc:  # pragma: no cover - defensive
        return {"ok": False, "file_path": path, "message": str(exc)}
    publish(KNOWLEDGE_INDEXED, {"path": str(p), "action": "update_note"})
    return {"ok": True, "file_path": str(p.relative_to(root)), "message": "note updated"}


async def knowledge_delete_note(path: str) -> dict[str, Any]:
    """Delete a vault note (refuses paths outside the vault root)."""
    root = vault_root()
    if not root.exists():
        return {"ok": False, "file_path": path, "message": "vault missing"}
    try:
        p = _resolve_note_path(path)
    except ValueError as exc:
        return {"ok": False, "file_path": path, "message": str(exc)}
    if not p.exists() or not p.is_file():
        return {"ok": False, "file_path": path, "message": "note not found"}
    try:
        await asyncio.to_thread(p.unlink)
    except OSError as exc:  # pragma: no cover - defensive
        return {"ok": False, "file_path": path, "message": str(exc)}
    publish(KNOWLEDGE_INDEXED, {"path": str(p), "action": "delete_note"})
    return {"ok": True, "file_path": str(p.relative_to(root)), "message": "note deleted"}


async def knowledge_link_entity(
    entity_name: str, note_path: Optional[str] = None
) -> dict[str, Any]:
    """Record a person/entity reference (persona_only log). Does not require existence."""
    ctx = {"note_path": note_path} if note_path else {}
    ref_id: Optional[str] = None
    try:
        async with session_factory()() as db:
            row = CaptureRoutingLog(
                ts=_now(),
                utterance=f"[[{entity_name}]]",
                conversation_context=ctx,
                stored_in="persona_only",
                ref_id=None,
                confidence=1.0,
                rule_fired="entity_link",
                raw_json={"entity": entity_name, "note_path": note_path},
            )
            db.add(row)
            await db.commit()
            ref_id = str(row.id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("entity link log write failed: %s", exc)
    return {
        "ok": True,
        "entity": entity_name,
        "stored_in": "persona_only",
        "ref_id": ref_id,
        "message": f"Recorded reference to entity '{entity_name}'.",
    }


# ─── Path safety helpers ───────────────────────────────────────────────────


def _resolve_note_path(path: str) -> Path:
    """Resolve a relative path against the vault root; reject paths outside it."""
    root = vault_root().resolve()
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise ValueError(f"path outside vault root: {path}")
    return p
