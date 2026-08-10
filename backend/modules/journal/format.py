"""Journal markdown formatting & enrichment (Obsidian/Quartz graph-first).

The vault journal note at `<vault>/00 Journal/YYYY/YYYY-MM-DD.md` is the source
of truth for a day. Everything here is deterministic — no LLM — and is written
so every entry is a rich, linked node in the Obsidian/Quartz graph:

- **Rich YAML frontmatter** (`title`, `aliases`, `date`, `type`, `category`,
  `mood`, `tags`, `confidence`, `created`, `updated`) so the note shows up in
  graph view, tag pages and Dataview queries.
- **Chronological nav links** — every entry links the previous and next day via
  `[[YYYY-MM-DD|prev]]`/`[[YYYY-MM-DD|next]]`, producing one long connected
  timeline spine in the graph.
- **Explicit section headings** (`## Mood`, … `## Connected`) so Quartz TOC and
  the Obsidian outline render cleanly.
- **A `## Connected` block** that collects every `[[wikilink]]` the entry
  already contains plus resolvable topic/people notes, so backlinks grow.
- **Auto-linking** of persons and topics that already have vault notes when
  their title appears verbatim in the entry body.

All helpers are idempotent: enriching a note that is already enriched is a
no-op that reports `changed: False`.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# Canonical section headings in the order a *complete* daily entry uses them.
# Kept in sync with plan.md §12.1 / ADDENDUM_SECOND_BRAIN.md §2.2.
JOURNAL_SECTIONS = [
    "Mood",
    "Highlights",
    "Accomplishments",
    "Learning",
    "Workout",
    "Expenses",
    "Reminders",
    "People",
    "Connected",
    "Tomorrow",
]

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_TAG_LINE_RE = re.compile(r"^tags\s*[:=]\s*\[([^\]]*)\]\s*$", re.MULTILINE)
_ALIAS_LINE_RE = re.compile(r"^aliases\s*[:=]\s*\[([^\]]*)\]\s*$", re.MULTILINE)
_MOOD_LINE_RE = re.compile(r"^mood\s*[:=]\s*['\"]?([^'\"\n]+?)['\"]?\s*$", re.MULTILINE)


def weekday_name(d: date) -> str:
    return _WEEKDAYS[d.weekday()]


def prev_day(d: date) -> date:
    return d - timedelta(days=1)


def next_day(d: date) -> date:
    return d + timedelta(days=1)


def journal_aliases(d: date) -> list[str]:
    """Aliases Obsidian should resolve this entry as: date, full date, weekday."""
    return [f"{d:%Y-%m-%d}", f"{d:%B %d, %Y}", f"{d:%d %B %Y}"]


def default_tags() -> list[str]:
    return ["journal", "daily"]


def _quote_yaml(value: str) -> str:
    v = str(value)
    if (
        not v
        or v[0] in "!&*-?|>%@`\"'#[]{}"
        or ": " in v
        or v.endswith(":")
        or " #" in v
    ):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def render_frontmatter(
    d: date,
    mood: str = "",
    tags: Optional[list[str]] = None,
    category: str = "GENERAL",
    title: Optional[str] = None,
    confidence: Optional[float] = None,
    aliases: Optional[list[str]] = None,
) -> str:
    """Render a rich graph-friendly YAML frontmatter block for a journal day."""
    if mood == "None":
        mood = ""
    t = title or f"{d:%Y-%m-%d}"
    tags = list(dict.fromkeys([*(tags or []), *default_tags()]))
    aliases = list(dict.fromkeys([*(aliases or []), *journal_aliases(d)]))
    lines = ["---", f"title: {_quote_yaml(t)}", "type: journal"]
    if category:
        lines.append(f"category: {_quote_yaml(category)}")
    if mood:
        lines.append(f"mood: {_quote_yaml(mood)}")
    tags_rendered = ", ".join(_quote_yaml(x) for x in tags)
    lines.append(f"tags: [{tags_rendered}]")
    aliases_rendered = ", ".join(_quote_yaml(x) for x in aliases)
    lines.append(f"aliases: [{aliases_rendered}]")
    lines.append(f"date: {d.isoformat()}")
    lines.append(f"confidence: {confidence if confidence is not None else 1.0}")
    lines.append(f"created: {d.isoformat()}")
    lines.append(f"updated: {d.isoformat()}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def extract_wikilinks(content: str) -> list[str]:
    """Return the raw `[[target]]` targets as written (deduplicated, in order).

    `[[target]]`, `[[target|alias]]` and `[[target#heading]]` all yield
    `target`; the alias/heading parts are dropped.
    """
    out: list[str] = []
    for raw in _WIKILINK_RE.findall(content or ""):
        target = re.split(r"[|#]", raw, maxsplit=1)[0].strip()
        if target and target not in out:
            out.append(target)
    return out


def parse_frontmatter(content: str) -> Optional[dict]:
    """Best-effort parse of the note's frontmatter (mood/tags/aliases)."""
    m = _FRONTMATTER_RE.match(content or "")
    if not m:
        return None
    fm = m.group(1)
    mood_m = _MOOD_LINE_RE.search(fm)
    tags_m = _TAG_LINE_RE.search(fm)
    aliases_m = _ALIAS_LINE_RE.search(fm)

    def _list(raw: str) -> list[str]:
        return [x.strip().strip("'\"") for x in raw.split(",") if x.strip()]

    mood = mood_m.group(1).strip() if mood_m else ""
    tags = _list(tags_m.group(1)) if tags_m else []
    aliases = _list(aliases_m.group(1)) if aliases_m else []
    return {"mood": mood, "tags": tags, "aliases": aliases}


def render_nav(d: date) -> str:
    """Chronological prev/next wikilink line for a journal day."""
    return (
        f"[[{prev_day(d).isoformat()}|← prev]] · "
        f"[[{next_day(d).isoformat()}|next →]]"
    )


def render_new_note(
    d: date,
    mood: str = "",
    tags: Optional[list[str]] = None,
    category: str = "GENERAL",
    body: str = "",
) -> str:
    """Full markdown for a new journal entry (frontmatter + skeleton + body).

    When `body` already carries `##` sections (e.g. a structured questionnaire
    write), it is used as-is; otherwise a complete section skeleton is rendered
    so the note opens as a readable, partially-filled template.
    """
    if body.strip():
        content_body = body.strip()
    else:
        content_body = "\n\n".join(f"## {name}\n\n" for name in JOURNAL_SECTIONS)

    return (
        f"{render_frontmatter(d, mood=mood, tags=tags, category=category)}\n"
        f"# {d:%Y-%m-%d} — {weekday_name(d)}\n\n"
        f"{render_nav(d)}\n\n"
        f"{content_body}\n\n"
        f"## Connected\n\n{render_nav(d)}\n"
    )


def _person_and_topic_stems(vault_root: Path) -> dict[str, list[Path]]:
    """Map lowercased note stem -> matching vault note paths.

    Used to auto-link persons/topics whose note already exists. Skips the
    journal folder itself (chronology links are handled by `render_nav`).
    """
    index: dict[str, list[Path]] = {}
    if not vault_root.exists():
        return index
    for p in vault_root.rglob("*.md"):
        if ".git" in p.parts or p.name.startswith("."):
            continue
        if "00 Journal" in p.parts:
            continue
        index.setdefault(p.stem.lower(), []).append(p)
    return index


def enrich_markdown(content: str, d: date, vault_root: Optional[Path] = None) -> tuple[str, bool]:
    """Idempotently upgrade a journal note for Obsidian/Quartz graph use.

    Guarantees (any missing element is added; existing ones are preserved):

    1. Rich frontmatter (title/aliases/date/type/tags/mood/category) exists.
    2. Chronological prev/next nav wikilinks are present after the H1.
    3. A `## Connected` block exists listing the entry's wikilinks plus any
       resolvable person/topic notes whose titles appear verbatim in the body.

    Returns ``(content, changed)``.
    """
    if not content:
        return content, False
    changed = False
    fm = parse_frontmatter(content)

    # 1. Ensure frontmatter.
    if fm is None:
        body_only = _FRONTMATTER_RE.sub("", content).lstrip("\n")
        body_only = re.sub(r"^#\s+[^\n]*\n+", "", body_only)
        content = (
            f"{render_frontmatter(d)}\n"
            f"# {d:%Y-%m-%d} — {weekday_name(d)}\n\n"
            f"{body_only}"
        )
        changed = True
    else:
        new_block = render_frontmatter(
            d,
            mood=fm["mood"],
            tags=fm["tags"],
            category="GENERAL",
            aliases=fm.get("aliases") or [],
        )
        old_block = _FRONTMATTER_RE.match(content).group(0)
        if old_block.strip() != new_block.strip():
            content = _FRONTMATTER_RE.sub(new_block, content, count=1)
            changed = True

    # 2. Ensure chronological nav links are present near the top (after the H1).
    nav = render_nav(d)
    if nav not in content:
        # Insert after the first H1 heading line (or after frontmatter if none).
        h1 = re.search(r"^#\s+[^\n]*$", content, re.M)
        if h1:
            body_start = h1.end()
        else:
            body_start = content.find("\n\n")
        if body_start != -1:
            insert_at = body_start
            if content[insert_at:insert_at + 2] == "\n\n":
                insert_at += 2
            content = content[:insert_at] + nav + "\n\n" + content[insert_at:]
        else:
            content = content.rstrip() + "\n\n" + nav + "\n"
        changed = True

    # 3. Ensure a Connected block exists.
    connected_idx = content.find("## Connected")
    links = extract_wikilinks(content)
    auto = _auto_targets(content, d, vault_root)
    resolved = list(dict.fromkeys([*links, *auto]))
    connected_block = (
        f"## Connected\n\n"
        f"`{render_nav(d)}`\n\n"
        f"{f'- Linked elsewhere: ' + ' · '.join(f'[[{t}]]' for t in resolved) if resolved else '_No wikilinks yet — link people, topics and projects as you journal._'}\n"
    )
    if connected_idx != -1:
        end = _section_end(content, connected_idx)
        old = content[connected_idx:end]
        if old.strip() != connected_block.strip():
            content = content[:connected_idx] + connected_block + content[end:].lstrip("\n")
            changed = True
    else:
        content = content.rstrip() + "\n\n" + connected_block
        changed = True

    return content, changed


def related_links(content: str, vault_root: Optional[Path], limit: int = 8) -> list[str]:
    """Public wrapper over the auto-link scan: vault note stems that appear
    verbatim in `content` (longer stems first). Used by the Knowledge module to
    seed the `## Related` block of new vault notes, tying the graph together."""
    if vault_root is None:
        return []
    return _auto_targets(content, date.today(), vault_root)[:limit]


def _auto_targets(content: str, d: date, vault_root: Optional[Path]) -> list[str]:
    """Notes to auto-link: person/topic notes whose title appears verbatim."""
    if vault_root is None:
        return []
    index = _person_and_topic_stems(vault_root)
    body = _FRONTMATTER_RE.sub("", content).lower()
    out: list[str] = []
    # Prefer longer stems first so "machine learning" wins over "learning".
    for stem in sorted(index, key=len, reverse=True):
        if stem in body and len(stem) >= 3 and stem not in out:
            out.append(index[stem][0].stem)
            if len(out) >= 8:
                break
    return out


def _section_end(content: str, start: int) -> int:
    """Index past the end of the `##` section beginning at `start`."""
    next_marker = content.find("\n## ", start + 2)
    if next_marker == -1:
        return len(content)
    return next_marker