"""Universal graph write adapter (plan.md §10).

Every domain table gets a thin adapter that registers/updates its rows as graph
nodes on write, driven by the event bus (PersonUpdated / InteractionLogged /
KnowledgeIndexed / TaskUpdated). This is what populates `graph.graph_nodes` and
`graph.graph_edges` — the Intelligence Graph read by the frontend, the graph
module's MCP server, and the nightly analytics job.

This adapter builds a **knowledge graph**, not just a CRM graph:

- person nodes      — a profile per person (introduced_by → parent edge)
- interaction nodes — one node per logged interaction (participated edges)
- journal nodes     — daily entries become nodes (chronology edges to the day
                       before/after, linking the whole timeline spine)
- note nodes        — every vault markdown file becomes a node; Obsidian
                       `[[wikilinks]]` become `links_to` edges, so the vault's
                       own structure IS the graph
- topic nodes       — a node per tag/frontmatter tag (`tagged_with` edges)
- area nodes        — a node per top-level vault folder (knowledge, projects,
                       learning, finance, people, …) that notes belong to
- person mentions   — when a note or journal links `[[Person Name]]`, an edge
                       is drawn to the matching person profile node

Subscriber contract: `graph_subscriber(event, payload)` is called by the worker's
event-bus subscription thread (backend/automation/scheduler.py). Each handler is
best-effort: an upstream module write already committed; this adapter is a
downstream projection and must never raise across the loop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from backend.modules.db import session_factory
from backend.db.postgres.schemas.graph.models import GraphNode, GraphEdge
from backend.db.postgres.schemas.relationship.models import Person, Interaction

logger = logging.getLogger("vesper.graph.adapter")

_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+?)(?:#[^\[\]|]*?)?(?:\[[^\]]*?\])?\]\]")
_FRONTMATTER_TAGS_RE = re.compile(r"^tags\s*[:=]\s*\[([^\]]*)\]\s*$", re.MULTILINE)
_INLINE_TAG_RE = re.compile(r"(?<!\w)#([a-zA-Z0-9][a-zA-Z0-9_/\-]*)")
_TOP_LEVEL_DIRS = ("00 Journal", "01 Inbox", "02 Projects", "03 Knowledge",
                   "04 Learning", "05 People", "06 Finance", "07 Health",
                   "08 Career", "09 Archive")

# Persons who appear in the 05 People/ folder are projected as both a
# relationship `person` node (DB-backed) and a `note` node for their vault file.
_PEOPLE_DIR = "05 People"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _node_id(entity_type: str, ref_id: str) -> str:
    """Deterministic graph node id from (entity_type, domain ref_id)."""
    return hashlib.md5(f"{entity_type}:{ref_id}".encode()).hexdigest()


async def _upsert_node(
    db,
    entity_type: str,
    ref_id: str,
    label: str,
    node_metadata: dict,
) -> GraphNode:
    node = (await db.execute(
        select(GraphNode).where(GraphNode.id == _node_id(entity_type, ref_id))
    )).scalar_one_or_none()
    if node is None:
        node = GraphNode(
            id=_node_id(entity_type, ref_id),
            entity_type=entity_type,
            ref_table=entity_type,
            ref_id=ref_id,
            label=label,
            node_metadata=node_metadata,
        )
        db.add(node)
    else:
        node.label = label
        node.node_metadata = node_metadata
        node.updated_at = _now()
    return node


async def _upsert_edge(db, source: GraphNode, target: GraphNode, edge_type: str, weight: float = 1.0) -> None:
    edge = (await db.execute(
        select(GraphEdge).where(
            GraphEdge.source_id == source.id,
            GraphEdge.target_id == target.id,
            GraphEdge.edge_type == edge_type,
        )
    )).scalar_one_or_none()
    if edge is None:
        db.add(GraphEdge(
            source_id=source.id,
            target_id=target.id,
            edge_type=edge_type,
            weight=weight,
        ))
    else:
        edge.weight = weight


async def _on_person(person_id: str) -> None:
    """PersonUpdated — upsert a person node + its introduced_by edge."""
    try:
        async with session_factory()() as db:
            person = (await db.execute(
                select(Person).where(Person.id == person_id)
            )).scalar_one_or_none()
            if person is None:
                return
            node = await _upsert_node(
                db,
                "person",
                person.id,
                person.name or person.nickname or "person",
                {
                    "category": person.category if hasattr(person.category, "value") else person.category,
                    "health_score": person.health_score,
                    "company": person.company,
                    "occupation": person.occupation,
                },
            )
            # Link the person profile to their People-note in the vault, if any,
            # so the CRM graph and the knowledge graph share the same entity.
            name = (person.name or person.nickname or "").strip()
            if name:
                people_note = _resolve_people_note(name)
                if people_note:
                    note_node = await _upsert_node(
                        db,
                        "note",
                        _vault_rel(str(people_note)),
                        people_note.stem,
                        {"vault_path": _vault_rel(str(people_note))},
                    )
                    await _upsert_edge(db, node, note_node, "profile", weight=1.0)
            if person.introduced_by_id:
                intro = (await db.execute(
                    select(Person).where(Person.id == person.introduced_by_id)
                )).scalar_one_or_none()
                if intro is not None:
                    intro_node = await _upsert_node(
                        db, "person", intro.id, intro.name or "person", {}
                    )
                    await _upsert_edge(intro_node, node, "introduced_by", weight=1.0)
            await db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("graph person adapter failed: %s", exc)


async def _on_interaction(interaction_id: str) -> None:
    """InteractionLogged — edge from person to a shared 'interaction' node."""
    try:
        async with session_factory()() as db:
            interaction = (await db.execute(
                select(Interaction).where(Interaction.id == interaction_id)
            )).scalar_one_or_none()
            if interaction is None:
                return
            person = (await db.execute(
                select(Person).where(Person.id == interaction.person_id)
            )).scalar_one_or_none()
            if person is None:
                return
            person_node = await _upsert_node(
                db, "person", person.id, person.name or "person", {}
            )
            event_node = await _upsert_node(
                db,
                "interaction",
                interaction.id,
                f"interaction {interaction.event_date.date().isoformat() if interaction.event_date else ''}".strip(),
                {"type": interaction.type if hasattr(interaction.type, "value") else interaction.type,
                 "summary": interaction.summary},
            )
            await _upsert_edge(db, person_node, event_node, "participated", weight=1.0)
            await db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("graph interaction adapter failed: %s", exc)


def _vault_root() -> Path:
    try:
        from backend.modules.knowledge.logic import vault_root
        return vault_root()
    except Exception:  # pragma: no cover - defensive
        return Path(os.environ.get("HERMES_VAULT_PATH", "~/Documents/KnowledgeVault")).expanduser().resolve()


def _resolve_people_note(name: str) -> Path | None:
    """Find a 05 People/<name>.md vault note for a person profile (best-effort)."""
    root = _vault_root()
    base = root / _PEOPLE_DIR
    if not base.exists():
        return None
    from difflib import get_close_matches

    candidates = sorted(
        p for p in base.rglob("*.md")
        if not p.name.startswith(".")
    )
    if not candidates:
        return None
    stems = {p.stem for p in candidates}
    if name.casefold() in {s.casefold() for s in stems}:
        return next(p for p in candidates if p.stem.casefold() == name.casefold())
    hits = get_close_matches(name, stems, n=1, cutoff=0.6)
    if hits:
        return next(p for p in candidates if p.stem == hits[0])
    return None


def _vault_rel(path: str, root: Path | None = None) -> str:
    """Vault-relative path for a note (falls back to the raw path)."""
    root = root or _vault_root()
    try:
        return str(Path(path).resolve().relative_to(root))
    except Exception:
        return str(path)


def _stem_to_note_paths(root: Path) -> dict[str, list[Path]]:
    """Map a vault note's lowercased stem -> the note's relative paths.

    Obsidian `[[wikilinks]]` resolve by filename stem (independent of folder),
    so this index turns `[[Alpha]]` into the actual `03 Knowledge/alpha.md`.
    """
    index: dict[str, list[Path]] = {}
    if not root.exists():
        return index
    for file in root.rglob("*.md"):
        if any(part.startswith(".") for part in file.parts):
            continue
        index.setdefault(file.stem.casefold(), []).append(file)
    return index


# Vault index cache — building it walks the whole tree; worth ~30 s TTL.
_index_lock = threading.Lock()
_index_cache: dict[str, dict[str, list[Path]]] = {}
_index_ts = 0.0


def _note_index() -> dict[str, list[Path]]:
    global _index_ts, _index_cache
    root = _vault_root()
    key = str(root)
    now = time.monotonic()
    with _index_lock:
        if _index_cache.get(key) is not None and now - _index_ts < 30.0:
            return _index_cache[key]
        fresh = _stem_to_note_paths(root)
        _index_cache[key] = fresh
        _index_ts = now
        return fresh


def _resolve_wikilink(target: str, root: Path) -> Path | None:
    """Resolve an Obsidian `[[target]]` stem to a vault note path."""
    t = (target or "").strip().casefold().removesuffix(".md")
    if not t:
        return None
    for candidate in _note_index().get(t, []):
        return candidate
    return None


def _extract_tags(content: str) -> list[str]:
    """Frontmatter `tags: [...]` plus `#inline` tags in the body (dedup, order)."""
    out: list[str] = []
    m = _FRONTMATTER_TAGS_RE.search(content or "")
    if m:
        for raw in m.group(1).split(","):
            tag = raw.strip().strip("'\"")
            if tag and tag not in out:
                out.append(tag)
    for raw in _INLINE_TAG_RE.findall(content or ""):
        tag = raw.strip().lstrip("#")
        if tag and tag not in out:
            out.append(tag)
    return out


def _extract_wikilinks(content: str) -> list[str]:
    """Obsidian `[[...]]` targets, deduplicated, in order (alias stripped)."""
    out: list[str] = []
    for raw in _WIKILINK_RE.findall(content or ""):
        target = raw.strip()
        if target and target not in out:
            out.append(target)
    return out


def _date_from_journal_path(rel: str) -> str | None:
    """The `YYYY-MM-DD` of a journal note path, else None."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})\.md$", rel)
    return m.group(1) if m else None


async def _project_note(
    db,
    root: Path,
    rel: str,
    content: str,
    mentioned_names: list[str] | None = None,
) -> GraphNode:
    """Upsert a note/topic/area projection for one vault file (and its links).

    - the note node (entity_type "note")
    - `links_to` edges to every other note an Obsidian `[[wikilink]]` resolves
    - `tagged_with` edges to `topic` nodes (one per tag)
    - `belongs_to` edge to the top-level `area` node (folder)
    - journal entries additionally get `chronology` edges to the previous/next
      day's entry (the daily timeline spine)
    """
    stem = Path(rel).stem
    node = await _upsert_node(
        db,
        "note",
        rel,
        stem,
        {"vault_path": rel},
    )

    # Top-level area node this note lives in.
    top = rel.split("/", 1)[0] if "/" in rel else ""
    if top and top in _TOP_LEVEL_DIRS:
        area = await _upsert_node(db, "area", top, top, {})
        await _upsert_edge(db, node, area, "belongs_to", weight=1.0)

    # wikilinks -> links_to edges
    for target in _extract_wikilinks(content):
        dest = _resolve_wikilink(target, root)
        if dest is None:
            continue
        dest_rel = _vault_rel(str(dest), root)
        dest_node = await _upsert_node(
            db,
            "note",
            dest_rel,
            dest.stem,
            {"vault_path": dest_rel},
        )
        await _upsert_edge(db, node, dest_node, "links_to", weight=1.0)

    # tags -> topic nodes
    for tag in _extract_tags(content):
        topic = await _upsert_node(db, "topic", tag.casefold(), tag, {})
        await _upsert_edge(db, node, topic, "tagged_with", weight=1.0)

    # Journal/knowledge mention ingestion promotes names to relationship.Person
    # rows; connect the source note to those same person nodes in the universal
    # graph so People OS, the relationship graph, and the vault share identity.
    if mentioned_names:
        people = (await db.execute(select(Person))).scalars().all()
        by_name = {p.name.casefold(): p for p in people}
        for name in mentioned_names:
            person = by_name.get(name.casefold())
            if person is None:
                continue
            person_node = await _upsert_node(
                db,
                "person",
                person.id,
                person.name,
                {"category": person.category, "source": "relationship.person"},
            )
            await _upsert_edge(db, node, person_node, "mentioned_in", weight=1.0)

    # journal chronology spine
    day = _date_from_journal_path(rel)
    if day:
        prefix = rel.split("/")[0]
        if prefix == "00 Journal":
            await _upsert_journal_chronology(db, node, day)

    return node


async def _upsert_journal_chronology(db, journal_node: GraphNode, day: str) -> None:
    """Link a journal entry to the notes for the previous and next calendar day."""
    from datetime import timedelta

    d = date.fromisoformat(day)
    for offset in (-1, 1):
        other_day = (d + timedelta(days=offset)).isoformat()
        other_rel = f"00 Journal/{other_day[:4]}/{other_day}.md"
        other_path = _vault_root() / other_rel
        if not other_path.exists():
            continue
        other_node = await _upsert_node(
            db, "note", other_rel, other_day, {"vault_path": other_rel}
        )
        await _upsert_edge(db, journal_node, other_node, "chronology", weight=1.0)


async def _on_knowledge(payload: dict) -> None:
    """KnowledgeIndexed — project a vault note into the graph and its links."""
    try:
        path = payload.get("file_path") or payload.get("path") or ""
        if not path:
            return
        root = _vault_root()
        # Backfill passes vault-relative paths ("03 Knowledge/foo.md"); resolve
        # them against the vault root so the file can be read for link parsing.
        p = Path(path)
        if not p.is_absolute():
            p = root / p
        rel = _vault_rel(str(p), root)
        content = ""
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
        if not content:
            content = payload.get("content") or ""
        from backend.modules.relationship.logic import relationship_ingest_mentions

        known_people = [Path(rel).stem] if rel.startswith(f"{_PEOPLE_DIR}/") else []
        mentions = await relationship_ingest_mentions(content, source=rel, known_people=known_people)
        async with session_factory()() as db:
            await _project_note(db, root, rel, content, mentions.get("names", []))
            await db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("graph knowledge adapter failed: %s", exc)

    # Reactive garden refresh: after any note write, rebuild the Quartz garden
    # (debounced) so new notes appear promptly instead of only at the nightly
    # vault_backup_publish job. Cheap no-op when QUARTZ_TRIGGER_URL is unset.
    _schedule_garden_rebuild()


async def _on_diary(date_iso: str) -> None:
    """JournalCreated/DailyJournalCompleted — refresh the day's note node,
    re-project its links and reattach the chronology spine."""
    if not date_iso:
        return
    root = _vault_root()
    rel = f"00 Journal/{date_iso[:4]}/{date_iso}.md"
    p = root / rel
    if not p.exists():
        return
    content = ""
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        content = ""
    try:
        from backend.modules.relationship.logic import relationship_ingest_mentions

        mentions = await relationship_ingest_mentions(content, source=rel)
        async with session_factory()() as db:
            await _project_note(db, root, rel, content, mentions.get("names", []))
            await db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("graph journal adapter failed: %s", exc)


# ── Reactive Quartz garden rebuild (debounced) ────────────────────────────
_QUARTZ_LOCK = threading.Lock()
_QUARTZ_PENDING = False
_QUARTZ_SCHEDULED_AT = 0.0
_QUARTZ_DEBOUNCE_SECONDS = 30.0


def _schedule_garden_rebuild() -> None:
    """Schedule a debounced POST /rebuild to the Quartz trigger server."""
    global _QUARTZ_PENDING, _QUARTZ_SCHEDULED_AT
    trigger = os.environ.get("QUARTZ_TRIGGER_URL", "").strip()
    if not trigger:
        return
    with _QUARTZ_LOCK:
        _QUARTZ_PENDING = True
        _QUARTZ_SCHEDULED_AT = time.monotonic()
    threading.Thread(target=_quartz_rebuild_worker, args=(trigger,), daemon=True).start()


def _quartz_rebuild_worker(trigger: str) -> None:
    """Wait out the debounce window, then fire one rebuild if still pending."""
    global _QUARTZ_PENDING, _QUARTZ_SCHEDULED_AT
    # Debounce: wait up to the window; if another note landed meanwhile, keep
    # waiting so burst captures coalesce into a single rebuild.
    while True:
        with _QUARTZ_LOCK:
            elapsed = time.monotonic() - _QUARTZ_SCHEDULED_AT
        if elapsed >= _QUARTZ_DEBOUNCE_SECONDS:
            break
        time.sleep(2.0)
    with _QUARTZ_LOCK:
        if not _QUARTZ_PENDING:
            return
        _QUARTZ_PENDING = False
    try:
        req = urllib.request.Request(
            trigger, data=b"{}", method="POST", headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read() or b"{}")
        if body.get("ok"):
            logger.info("quartz garden rebuilt (reactive, %.0fs)", body.get("durationMs", 0))
        else:
            logger.warning("quartz garden rebuild failed: %s", body.get("output", "")[-300:])
    except Exception as exc:  # pragma: no cover - never let this break writes
        logger.warning("quartz garden rebuild trigger failed: %s", exc)


async def graph_subscriber(event: str, payload: dict) -> None:
    """Event-bus subscriber entrypoint (plan §10 / §6)."""
    try:
        if event == "PersonUpdated":
            pid = payload.get("person_id") or payload.get("id")
            if pid:
                await _on_person(pid)
        elif event == "InteractionLogged":
            iid = payload.get("interaction_id") or payload.get("id")
            if iid:
                await _on_interaction(iid)
        elif event == "KnowledgeIndexed":
            await _on_knowledge(payload)
        elif event in ("JournalCreated", "DailyJournalCompleted"):
            await _on_diary(payload.get("date", ""))
        elif event == "TaskUpdated":
            # Task nodes land in the calendar/planning graph; nothing to project
            # here yet — reserved for finite-task graph integration.
            pass
    except Exception as exc:  # pragma: no cover
        logger.warning("graph_subscriber(%s) failed: %s", event, exc)
