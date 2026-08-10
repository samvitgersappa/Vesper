"""Relationship module business logic — ported from ProjectVesper's backend.

Port of ProjectVesper's relationship MCP server (`backend/mcp_server.py`) and
health service (`backend/app/services/health.py`) onto the `relationship`
Postgres schema (Phase 2) and the shared async session factory. Decay formula,
streak tracking, and urgency ratio are copied verbatim from ProjectVesper.

Reads/writes the `relationship` Postgres schema. All returns are plain dicts.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, func, or_

import networkx as nx

try:  # python-louvain
    import community.community_louvain as community_louvain
except ImportError:  # pragma: no cover - graph community tool degrades gracefully
    community_louvain = None

import dateutil.parser

from backend.db.postgres.schemas.relationship.models import (
    Person, Interaction, Relationship, Reminder, Note,
    LifeEvent, GiftIdea, Tag, PersonTag,
)
from backend.modules.common import publish
from backend.modules.db import session_factory
from backend.events.catalog import INTERACTION_LOGGED, PERSON_UPDATED

CATEGORY_FREQUENCY = {
    "FAMILY": 7,
    "NEW_CONTACT": 3,
    "FRIENDS": 14,
    "IMPORTANT": 14,
    "COUSINS": 21,
    "RELATIVES": 30,
    "COLLEAGUES": 30,
    "NETWORK": 90,
}
VALID_CATEGORIES = set(CATEGORY_FREQUENCY)

STRENGTH_WEIGHT = {"STRONG": 1.0, "MEDIUM": 0.6, "WEAK": 0.3}

_TYPE_MAP = {
    "call": "CALL", "meeting": "MEETING", "message": "MESSAGE",
    "email": "EMAIL", "coffee": "MEETING", "lunch": "MEETING",
    "event": "OTHER", "video_call": "CALL", "birthday_wish": "BIRTHDAY_WISH",
    "social": "SOCIAL",
}

_HEALTH_RELEVANT_FIELDS = {"category", "contact_frequency_days", "last_contacted"}

VALID_UPDATE_FIELDS = {
    "name", "company", "occupation", "email", "phone", "bio",
    "linkedin_url", "twitter_handle", "instagram_handle", "github_username",
    "birthday", "anniversary", "contact_frequency_days",
    "city", "country", "meeting_place", "profile_notes", "nickname",
    "category", "relation_type", "last_contacted",
    "topics_of_interest", "hobbies",
}

GROUP_CONTACT_LABELS = {
    "family", "parents", "grandparents", "grandparent", "siblings",
    "brothers", "sisters", "children", "kids", "relatives", "colleagues",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enum_value(x: Any) -> Any:
    return x.value if hasattr(x, "value") else x


def effective_frequency(person: Person) -> int:
    """Expected contact frequency in days for a person (ProjectVesper verbatim)."""
    if person.contact_frequency_days:
        return person.contact_frequency_days
    return CATEGORY_FREQUENCY.get(_enum_value(person.category), 90)


def calculate_health_score(person: Person) -> float:
    """Decay-based health score, ProjectVesper verbatim."""
    if not person.last_contacted:
        days_since = (_now() - person.created_at).days
        freq = effective_frequency(person)
        if days_since <= freq:
            return max(0.0, 1.0 - (days_since / freq) * 0.5)
        overdue = days_since - freq
        return max(0.0, 0.5 * (0.95 ** (overdue / 7)))

    days_since = (_now() - person.last_contacted).days
    freq = effective_frequency(person)

    if days_since <= freq:
        return min(1.0, 1.0 - (days_since / freq) * 0.2)

    overdue = days_since - freq
    return max(0.0, 0.8 * (0.95 ** (overdue / 7)))


def urgency_ratio(person: Person) -> float:
    """Days since contact / expected frequency (ProjectVesper verbatim)."""
    if not person.last_contacted:
        days_since = (_now() - person.created_at).days
    else:
        days_since = (_now() - person.last_contacted).days
    freq = effective_frequency(person)
    return days_since / freq if freq > 0 else 0


def update_streak(person: Person) -> None:
    """Increment streak if contacted within the window, else reset (verbatim)."""
    if not person.last_contacted:
        return
    freq = effective_frequency(person)
    days_since = (_now() - person.last_contacted).days
    if days_since <= freq:
        if (not person.streak_last_updated or
                (_now() - person.streak_last_updated).days >= 7):
            person.streak_weeks += 1
            person.streak_last_updated = _now()
    else:
        person.streak_weeks = 0


# ─── Serializers ────────────────────────────────────────────────────

def _person_dict(p: Person) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "nickname": p.nickname,
        "company": p.company,
        "occupation": p.occupation,
        "category": _enum_value(p.category),
        "relation_type": _enum_value(p.relation_type),
        "health_score": round(p.health_score, 2) if p.health_score is not None else None,
        "last_contacted": p.last_contacted.isoformat() if p.last_contacted else None,
        "birthday": p.birthday.date().isoformat() if p.birthday else None,
        "anniversary": p.anniversary.date().isoformat() if p.anniversary else None,
        "email": p.email,
        "phone": p.phone,
        "bio": p.bio,
        "hobbies": p.hobbies or [],
        "topics_of_interest": p.topics_of_interest or [],
        "linkedin_url": p.linkedin_url,
        "twitter_handle": p.twitter_handle,
        "instagram_handle": p.instagram_handle,
        "github_username": p.github_username,
        "city": p.city,
        "country": p.country,
        "meeting_place": p.meeting_place,
        "profile_notes": p.profile_notes,
        "contact_frequency_days": p.contact_frequency_days,
        "community_id": p.community_id,
        "betweenness_score": round(p.betweenness_score, 4) if p.betweenness_score else None,
        "streak_weeks": p.streak_weeks,
        "is_archived": p.is_archived,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _interaction_dict(i: Interaction) -> dict[str, Any]:
    return {
        "id": i.id,
        "person_id": i.person_id,
        "date": i.event_date.isoformat() if i.event_date else None,
        "type": _enum_value(i.type),
        "summary": i.summary,
        "sentiment": i.sentiment,
        "follow_up_needed": i.follow_up_needed,
        "follow_up_note": i.follow_up_note,
    }


def _note_dict(n: Note) -> dict[str, Any]:
    return {
        "id": n.id,
        "content": n.content,
        "pinned": n.is_pinned,
        "created": n.created_at.isoformat() if n.created_at else None,
    }


def _life_event_dict(e: LifeEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "title": e.title,
        "date": e.event_date.isoformat() if e.event_date else None,
        "description": e.description,
        "icon": e.icon,
    }


def _gift_dict(g: GiftIdea) -> dict[str, Any]:
    return {
        "id": g.id,
        "title": g.title,
        "occasion": g.occasion,
        "url": g.url,
        "price_range": g.price_range,
        "is_given": g.is_given,
    }


def _strength_weight(strength: Any) -> float:
    return STRENGTH_WEIGHT.get(_enum_value(strength), 0.6)


# ─── Graph helpers ──────────────────────────────────────────────────

async def _graph_data(limit: int = 200):
    """Active persons + relationships, with betweenness and communities computed.

    Returns (persons, relationships, betweenness_map, community_map). Network
    math is best-effort: with <2 connected nodes the maps are empty.
    """
    async with session_factory()() as db:
        res = await db.execute(
            select(Person).where(Person.is_archived == False).limit(limit)  # noqa: E712
        )
        persons = res.scalars().all()
        rel_res = await db.execute(select(Relationship))
        relationships = rel_res.scalars().all()

    G = nx.Graph()
    for p in persons:
        G.add_node(p.id)
    for r in relationships:
        if r.person_a_id in G and r.person_b_id in G and r.person_a_id != r.person_b_id:
            G.add_edge(r.person_a_id, r.person_b_id, weight=_strength_weight(r.strength))

    betweenness: dict = {}
    communities: dict = {}
    if G.number_of_nodes() >= 2:
        try:
            betweenness = nx.betweenness_centrality(G, weight="weight")
        except Exception:
            betweenness = {}
        try:
            if community_louvain is not None:
                communities = community_louvain.best_partition(G)
        except Exception:
            communities = {}
    return persons, relationships, betweenness, communities


async def _tag_names_for(db, person_id: str) -> list[str]:
    res = await db.execute(
        select(Tag.name).join(PersonTag).where(PersonTag.person_id == person_id)
    )
    return list(res.scalars().all())


# ─── Read tools ─────────────────────────────────────────────────────

async def relationship_search(query: str, limit: int = 10) -> dict[str, Any]:
    """Search persons by name/company/occupation/bio/city (ILIKE)."""
    q = (query or "").strip()
    async with session_factory()() as db:
        stmt = select(Person).where(Person.is_archived == False)  # noqa: E712
        if q:
            stmt = stmt.where(or_(
                Person.name.ilike(f"%{q}%"),
                Person.company.ilike(f"%{q}%"),
                Person.occupation.ilike(f"%{q}%"),
                Person.bio.ilike(f"%{q}%"),
                Person.city.ilike(f"%{q}%"),
            ))
        res = await db.execute(stmt.order_by(Person.name.asc()).limit(limit))
        return {"found": True, "results": [_person_dict(p) for p in res.scalars().all()]}


async def relationship_person_detail(person_id: str) -> dict[str, Any]:
    """Full profile: fields, recent interactions, tags, notes, life events, gift ideas."""
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No person with id {person_id}"}

        int_res = await db.execute(
            select(Interaction).where(Interaction.person_id == person_id)
            .order_by(Interaction.event_date.desc()).limit(5)
        )
        interactions = int_res.scalars().all()

        note_res = await db.execute(
            select(Note).where(Note.person_id == person_id).order_by(Note.created_at.desc())
        )
        notes = note_res.scalars().all()

        event_res = await db.execute(
            select(LifeEvent).where(LifeEvent.person_id == person_id)
            .order_by(LifeEvent.event_date.desc())
        )
        life_events = event_res.scalars().all()

        gift_res = await db.execute(
            select(GiftIdea).where(GiftIdea.person_id == person_id, GiftIdea.is_given == False)  # noqa: E712
        )
        gifts = gift_res.scalars().all()

        tags = await _tag_names_for(db, person_id)

        person = _person_dict(p)
        person["health_score"] = round(calculate_health_score(p), 2)
        person["urgency_ratio"] = round(urgency_ratio(p), 2)

        return {
            "found": True,
            **person,
            "tags": tags,
            "notes": [_note_dict(n) for n in notes],
            "life_events": [_life_event_dict(e) for e in life_events],
            "gift_ideas": [_gift_dict(g) for g in gifts],
            "recent_interactions": [_interaction_dict(i) for i in interactions],
        }


async def relationship_get_due_today() -> dict[str, Any]:
    """Overdue, cold, birthdays next 7 days, and open follow-ups."""
    now = _now()
    overdue, cold, birthdays, follow_ups = [], [], [], []

    async with session_factory()() as db:
        res = await db.execute(
            select(Person).where(Person.is_archived == False)  # noqa: E712
        )
        persons = res.scalars().all()

        for p in persons:
            freq = effective_frequency(p)
            health = calculate_health_score(p)
            if health < 0.3:
                cold.append({"id": p.id, "name": p.name, "health_score": round(health, 2)})
            if p.last_contacted:
                days_since = (now - p.last_contacted).days
                if days_since >= freq:
                    overdue.append({
                        "id": p.id,
                        "name": p.name,
                        "days_overdue": days_since - freq,
                        "urgency": round(urgency_ratio(p), 2),
                        "health_score": round(health, 2),
                    })
            elif not p.last_contacted:
                days_since = (now - p.created_at).days
                if days_since >= freq:
                    overdue.append({
                        "id": p.id,
                        "name": p.name,
                        "days_overdue": days_since - freq,
                        "urgency": round(urgency_ratio(p), 2),
                        "health_score": round(health, 2),
                    })
            if p.birthday:
                bday = p.birthday.replace(year=now.year)
                if bday < now:
                    bday = bday.replace(year=now.year + 1)
                days_until = (bday - now).days
                if 0 <= days_until <= 7:
                    birthdays.append({"id": p.id, "name": p.name, "days_until": days_until})

        overdue.sort(key=lambda x: x["urgency"], reverse=True)
        overdue = overdue[:10]

        fu_res = await db.execute(
            select(Interaction).where(
                Interaction.follow_up_needed == True,  # noqa: E712
                Interaction.event_date >= now - timedelta(days=7),
            ).order_by(Interaction.event_date.desc()).limit(10)
        )
        for i in fu_res.scalars().all():
            person = await db.get(Person, i.person_id)
            if person:
                follow_ups.append({
                    "person_id": person.id,
                    "person": person.name,
                    "note": i.follow_up_note,
                    "interaction_date": i.event_date.isoformat() if i.event_date else None,
                })

    return {
        "overdue": overdue,
        "cold": cold[:10],
        "birthdays": birthdays,
        "follow_ups": follow_ups,
    }


async def relationship_graph(limit: int = 200) -> dict[str, Any]:
    """Nodes + edges with betweenness and community computed over the graph."""
    persons, relationships, betweenness, communities = await _graph_data(limit)
    by_id = {p.id: p for p in persons}

    nodes = []
    for p in persons:
        node = {
            "id": p.id,
            "name": p.name,
            "company": p.company,
            "occupation": p.occupation,
            "category": _enum_value(p.category),
            "health_score": round(calculate_health_score(p), 2),
            "last_contacted": p.last_contacted.isoformat() if p.last_contacted else None,
            "birthday": p.birthday.date().isoformat() if p.birthday else None,
            "anniversary": p.anniversary.date().isoformat() if p.anniversary else None,
            "contact_frequency_days": effective_frequency(p),
            "streak_weeks": p.streak_weeks,
            "email": p.email,
            "phone": p.phone,
            "profile_notes": p.profile_notes,
            "topics_of_interest": p.topics_of_interest or [],
            "introduced_by_id": getattr(p, "introduced_by_id", None),
            "community_id": communities.get(p.id),
            "betweenness": round(betweenness.get(p.id, 0.0), 4),
        }
        nodes.append(node)

    edges = []
    for r in relationships:
        if r.person_a_id not in by_id or r.person_b_id not in by_id:
            continue
        edges.append({
            "id": r.id,
            "person_a_id": r.person_a_id,
            "person_b_id": r.person_b_id,
            "strength": _enum_value(r.strength),
            "label": r.label,
            "weight": _strength_weight(r.strength),
        })

    return {"nodes": nodes, "edges": edges, "total_nodes": len(nodes), "total_edges": len(edges)}


async def relationship_get_bridge_contacts(limit: int = 5) -> dict[str, Any]:
    """Top persons by betweenness centrality — your information brokers."""
    persons, _, betweenness, _ = await _graph_data(200)
    ranked = sorted(
        ((betweenness.get(p.id, 0.0), p) for p in persons if betweenness.get(p.id, 0.0) > 0),
        key=lambda x: x[0],
        reverse=True,
    )
    return {"bridge_contacts": [
        {
            "id": p.id,
            "name": p.name,
            "company": p.company,
            "occupation": p.occupation,
            "betweenness_score": round(b, 4),
        }
        for b, p in ranked[:limit]
    ]}


async def relationship_get_introduction_candidates(limit: int = 5) -> dict[str, Any]:
    """Pairs not connected but sharing >=1 tag/hobby; score = shared/union."""
    async with session_factory()() as db:
        res = await db.execute(
            select(Person).where(Person.is_archived == False)  # noqa: E712
        )
        persons = res.scalars().all()

        rel_res = await db.execute(select(Relationship))
        existing = set()
        for r in rel_res.scalars().all():
            existing.add((r.person_a_id, r.person_b_id))
            existing.add((r.person_b_id, r.person_a_id))

        interests = {}
        for p in persons:
            tags = set(await _tag_names_for(db, p.id))
            hobbies = set(p.hobbies or [])
            interests[p.id] = (tags, hobbies, p.name)

        candidates = []
        for i, pa in enumerate(persons):
            for pb in persons[i + 1:]:
                if (pa.id, pb.id) in existing:
                    continue
                ta, ha, _ = interests[pa.id]
                tb, hb, _ = interests[pb.id]
                shared = (ta & tb) | (ha & hb)
                if not shared:
                    continue
                union = ta | ha | tb | hb
                score = len(shared) / len(union) if union else 0.0
                candidates.append({
                    "person_a_id": pa.id,
                    "person_a": pa.name,
                    "person_b_id": pb.id,
                    "person_b": pb.name,
                    "shared_interests": sorted(shared)[:8],
                    "score": round(score, 3),
                })
            if len(candidates) >= limit * 3:
                break

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return {"candidates": candidates[:limit]}


async def relationship_get_communities() -> dict[str, Any]:
    """Louvain community groupings [{community_id, member_count, members}]."""
    persons, _, _, communities = await _graph_data(200)
    grouped: dict[str, list] = {}
    for p in persons:
        cid = communities.get(p.id) or "unassigned"
        grouped.setdefault(cid, []).append({
            "id": p.id,
            "name": p.name,
            "category": _enum_value(p.category),
            "occupation": p.occupation,
        })
    return {"communities": [
        {"community_id": cid, "member_count": len(members), "members": members}
        for cid, members in sorted(grouped.items(), key=lambda x: -len(x[1]))
    ]}


async def relationship_get_meeting_prep(person_id: str) -> dict[str, Any]:
    """Full context for meeting someone: profile, last interaction, follow-ups, events, gifts, notes."""
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No person with id {person_id}"}

        last_res = await db.execute(
            select(Interaction).where(Interaction.person_id == person_id)
            .order_by(Interaction.event_date.desc()).limit(1)
        )
        last = last_res.scalar_one_or_none()

        fu_res = await db.execute(
            select(Interaction).where(
                Interaction.person_id == person_id,
                Interaction.follow_up_needed == True,  # noqa: E712
            ).order_by(Interaction.event_date.desc()).limit(5)
        )
        follow_ups = fu_res.scalars().all()

        event_res = await db.execute(
            select(LifeEvent).where(LifeEvent.person_id == person_id)
            .order_by(LifeEvent.event_date.desc()).limit(5)
        )
        life_events = event_res.scalars().all()

        gift_res = await db.execute(
            select(GiftIdea).where(GiftIdea.person_id == person_id, GiftIdea.is_given == False)  # noqa: E712
        )
        gifts = gift_res.scalars().all()

        note_res = await db.execute(
            select(Note).where(Note.person_id == person_id).order_by(Note.created_at.desc()).limit(5)
        )
        notes = note_res.scalars().all()

        person = _person_dict(p)
        person["health_score"] = round(calculate_health_score(p), 2)

        return {
            "found": True,
            "person": person,
            "last_interaction": _interaction_dict(last) if last else None,
            "open_follow_ups": [_interaction_dict(f) for f in follow_ups],
            "life_events": [_life_event_dict(e) for e in life_events],
            "gift_ideas": [_gift_dict(g) for g in gifts],
            "recent_notes": [_note_dict(n) for n in notes],
        }


async def relationship_get_interactions(person_id: str, limit: int = 10) -> dict[str, Any]:
    """Interaction history for a person, newest first."""
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No person with id {person_id}"}
        res = await db.execute(
            select(Interaction).where(Interaction.person_id == person_id)
            .order_by(Interaction.event_date.desc()).limit(limit)
        )
        interactions = res.scalars().all()
        return {
            "found": True,
            "person_id": person_id,
            "person_name": p.name,
            "interactions": [_interaction_dict(i) for i in interactions],
        }


async def relationship_get_recent_activity(limit: int = 20) -> dict[str, Any]:
    """Global feed of recent interactions across all contacts."""
    async with session_factory()() as db:
        res = await db.execute(
            select(Interaction).order_by(Interaction.event_date.desc()).limit(limit)
        )
        interactions = res.scalars().all()
        activity = []
        for i in interactions:
            person = await db.get(Person, i.person_id)
            d = _interaction_dict(i)
            d["person"] = person.name if person else "Unknown"
            activity.append(d)
        return {"activity": activity}


async def relationship_get_stats() -> dict[str, Any]:
    """Dashboard overview: totals, health distribution, top contacts."""
    now = _now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    total = 0
    cold = 0
    upcoming_birthdays = []

    async with session_factory()() as db:
        total_res = await db.execute(
            select(func.count(Person.id)).where(Person.is_archived == False)  # noqa: E712
        )
        total = total_res.scalar() or 0

        weekly_res = await db.execute(
            select(func.count(Interaction.id)).where(Interaction.event_date >= week_ago)
        )
        weekly = weekly_res.scalar() or 0

        cold_res = await db.execute(
            select(func.count(Person.id)).where(
                Person.health_score < 0.3, Person.is_archived == False  # noqa: E712
            )
        )
        cold = cold_res.scalar() or 0

        p_res = await db.execute(
            select(Person).where(Person.is_archived == False)  # noqa: E712
        )
        for p in p_res.scalars().all():
            h = calculate_health_score(p)
            if h < 0.2:
                buckets["0.0-0.2"] += 1
            elif h < 0.4:
                buckets["0.2-0.4"] += 1
            elif h < 0.6:
                buckets["0.4-0.6"] += 1
            elif h < 0.8:
                buckets["0.6-0.8"] += 1
            else:
                buckets["0.8-1.0"] += 1
            if p.birthday:
                bday = p.birthday.replace(year=now.year)
                if bday < now:
                    bday = bday.replace(year=now.year + 1)
                days_until = (bday - now).days
                if 0 <= days_until <= 30:
                    upcoming_birthdays.append({
                        "id": p.id,
                        "name": p.name,
                        "days_until": days_until,
                        "birthday": p.birthday.date().isoformat(),
                    })
        upcoming_birthdays.sort(key=lambda x: x["days_until"])

        top_res = await db.execute(
            select(Interaction.person_id, func.count(Interaction.id).label("cnt"))
            .where(Interaction.event_date >= month_ago)
            .group_by(Interaction.person_id)
            .order_by(func.count(Interaction.id).desc())
            .limit(5)
        )
        top_contacts = []
        for person_id, cnt in top_res.all():
            person = await db.get(Person, person_id)
            if person:
                top_contacts.append({
                    "id": person.id,
                    "name": person.name,
                    "interactions_30d": cnt,
                })

    return {
        "total_contacts": total,
        "interactions_this_week": weekly,
        "cold_contacts": cold,
        "upcoming_birthdays": upcoming_birthdays,
        "health_distribution": buckets,
        "top_contacts": top_contacts,
    }


# ─── Write tools ────────────────────────────────────────────────────

async def relationship_log_interaction(
    person_id: str,
    type: str,
    summary: str,
    date: str = "",
    sentiment: str = "",
    follow_up_needed: bool = False,
    follow_up_note: str = "",
) -> dict[str, Any]:
    """Record an interaction; update person health/streak/last_contacted."""
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No person with id {person_id}"}

        interaction_type = _TYPE_MAP.get((type or "").lower(), (type or "").upper())
        event_date = _parse_datetime(date) or _now()

        interaction = Interaction(
            person_id=person_id,
            type=interaction_type,
            summary=summary,
            sentiment=sentiment or None,
            follow_up_needed=follow_up_needed,
            follow_up_note=follow_up_note or None,
            event_date=event_date,
        )
        db.add(interaction)

        p.last_contacted = event_date
        p.health_score = calculate_health_score(p)
        update_streak(p)
        p.updated_at = _now()

        await db.commit()
        await db.refresh(interaction)

        result = {
            "success": True,
            "interaction": _interaction_dict(interaction),
            "person_id": person_id,
            "person": p.name,
            "new_health_score": round(p.health_score, 2),
            "streak_weeks": p.streak_weeks,
        }
    publish(INTERACTION_LOGGED, {
        "interaction_id": interaction.id,
        "person_id": person_id,
        "person_name": p.name,
        "type": interaction_type,
        "event_date": event_date.isoformat(),
    })
    return result


async def relationship_create_person(
    name: str,
    company: str = "",
    occupation: str = "",
    category: str = "NETWORK",
    email: str = "",
    phone: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Create a person (health_score=1.0); optional initial note."""
    clean_name = (name or "").strip()
    normalized_name = re.sub(r"[^a-z0-9]+", " ", clean_name.lower()).strip()
    if not clean_name:
        return {"success": False, "message": "A person's individual name is required"}
    if normalized_name in GROUP_CONTACT_LABELS:
        return {
            "success": False,
            "needs_individual_names": True,
            "message": f"'{clean_name}' describes a group. Provide each person's name separately.",
        }
    cat = (category or "NETWORK").upper()
    if cat not in VALID_CATEGORIES:
        cat = "NETWORK"

    async with session_factory()() as db:
        existing = await db.execute(
            select(Person).where(Person.name.ilike(clean_name))
        )
        if existing.scalar_one_or_none():
            return {"success": False, "message": f"'{clean_name}' already exists"}

        person = Person(
            name=clean_name,
            company=company or None,
            occupation=occupation or None,
            category=cat,
            email=email or None,
            phone=phone or None,
            health_score=1.0,
        )
        db.add(person)
        await db.flush()

        if notes and notes.strip():
            db.add(Note(person_id=person.id, content=notes.strip()))

        await db.commit()

        result = {
            "success": True,
            "id": person.id,
            "name": person.name,
            "category": cat,
            "health_score": 1.0,
        }
    publish(PERSON_UPDATED, {
        "person_id": result["id"],
        "name": person.name,
        "action": "create",
    })
    return result


async def relationship_update_person(person_id: str, field: str, value: str) -> dict[str, Any]:
    """Update a single field on a person; recompute health if health-relevant."""
    field_lower = (field or "").strip().lower()
    if field_lower not in VALID_UPDATE_FIELDS:
        return {
            "success": False,
            "message": f"Unknown field '{field}'. Valid fields: {', '.join(sorted(VALID_UPDATE_FIELDS))}",
        }

    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No person with id {person_id}"}

        new_value: Any = value

        if field_lower == "name":
            new_value = (value or "").strip()
            normalized_name = re.sub(r"[^a-z0-9]+", " ", new_value.lower()).strip()
            if not new_value:
                return {"success": False, "message": "Name cannot be empty"}
            if normalized_name in GROUP_CONTACT_LABELS:
                return {"success": False, "needs_individual_names": True, "message": "Use an individual name, not a group label"}
            duplicate = await db.execute(select(Person).where(Person.name.ilike(new_value), Person.id != person_id))
            if duplicate.scalar_one_or_none():
                return {"success": False, "message": f"'{new_value}' already exists"}
        elif field_lower in ("birthday", "anniversary", "last_contacted"):
            parsed = _parse_datetime(value.strip())
            if not parsed:
                return {"success": False, "message": f"Invalid date for {field}. Use ISO format."}
            new_value = parsed
        elif field_lower == "contact_frequency_days":
            try:
                new_value = int(value)
            except (TypeError, ValueError):
                return {"success": False, "message": "contact_frequency_days must be a number"}
        elif field_lower in ("category", "relation_type"):
            new_value = value.upper()
        elif field_lower in ("topics_of_interest", "hobbies"):
            new_value = [item.strip() for item in re.split(r"[,\n]", value or "") if item.strip()]

        setattr(p, field_lower, new_value)
        if field_lower in _HEALTH_RELEVANT_FIELDS:
            p.health_score = calculate_health_score(p)
        p.updated_at = _now()

        await db.commit()

        result = {
            "success": True,
            "person_id": person_id,
            "person": p.name,
            "field": field_lower,
            "value": new_value.date().isoformat() if isinstance(new_value, datetime) else str(new_value),
            "health_score": round(p.health_score, 2),
        }
    publish(PERSON_UPDATED, {
        "person_id": person_id,
        "name": p.name,
        "action": "update",
        "field": field_lower,
    })
    return result


async def relationship_add_note(person_id: str, content: str) -> dict[str, Any]:
    """Append a note to a person."""
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No person with id {person_id}"}
        note = Note(person_id=person_id, content=content)
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return {"success": True, "note": _note_dict(note), "person": p.name}


async def relationship_add_reminder(
    person_id: str,
    title: str,
    due_at: str,
    reminder_type: str = "custom",
    body: str = "",
) -> dict[str, Any]:
    """Schedule a reminder. due_at accepts ISO or relative ('tomorrow 9am', 'in 2 hours')."""
    pid = person_id or None
    parsed = _parse_due_at(due_at)
    if not parsed:
        return {
            "success": False,
            "message": f"Could not parse due_at='{due_at}'. Use ISO ('2026-08-01', '2026-08-01T09:00') or relative ('tomorrow 9am', 'in 2 hours').",
        }

    async with session_factory()() as db:
        person_name = None
        if pid:
            p = await db.get(Person, pid)
            if p:
                person_name = p.name
        reminder = Reminder(
            person_id=pid,
            title=title,
            due_at=parsed,
            reminder_type=reminder_type or "custom",
            body=body or None,
        )
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)
        return {
            "success": True,
            "reminder_id": reminder.id,
            "person_id": pid,
            "person": person_name or "(none)",
            "title": title,
            "due_at": reminder.due_at.isoformat(),
            "reminder_type": reminder.reminder_type,
        }


async def relationship_delete_person(person_id: str) -> dict[str, Any]:
    """Soft-delete a person (is_archived=True)."""
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No person with id {person_id}"}
        p.is_archived = True
        p.updated_at = _now()
        await db.commit()
        result = {"success": True, "person_id": person_id, "person": p.name, "is_archived": True}
    publish(PERSON_UPDATED, {
        "person_id": person_id,
        "name": p.name,
        "action": "archive",
    })
    return result


# ─── Draft message composer (Part D) ─────────────────────────────────

_DRAFT_PURPOSE_ALIASES = {
    "reconnect": "reconnect",
    "follow_up": "follow_up",
    "followup": "follow_up",
    "congrats": "congrats",
    "congratulate": "congrats",
    "celebration": "congrats",
    "check_in": "check_in",
    "checkin": "check_in",
    "custom": "custom",
    "freeform": "custom",
}
VALID_DRAFT_PURPOSES = {"reconnect", "follow_up", "congrats", "check_in", "custom"}


async def relationship_draft_message(
    person_id: str,
    purpose: str = "reconnect",
    context: str = "",
) -> dict[str, Any]:
    """Compose a draft message for a person WITHOUT sending anything.

    Deterministic template composer (no LLM), using the person's real CRM
    context (last interaction, open follow-ups, recent life events).

    `purpose` picks the angle:
    - ``reconnect``  — rekindle after a gap, referencing the last interaction.
    - ``follow_up``  — chase an open follow-up from a prior interaction.
    - ``congrats``   — congratulate on the most recent life event.
    - ``check_in``   — light, no-pretext touch.
    - ``custom``     — free-form; ``context`` is embedded verbatim.

    This tool NEVER sends anything. The returned draft is marked
    ``requires_approval: true`` — a real send is a separate, human-mediated
    action outside this module (approvals-style, cf. Hermes
    ``destructive_slash_confirm``).
    """
    raw = (purpose or "").strip().lower()
    purpose = _DRAFT_PURPOSE_ALIASES.get(raw, raw)
    if purpose not in VALID_DRAFT_PURPOSES:
        return {
            "found": False,
            "error": "invalid_purpose",
            "message": "purpose must be one of: reconnect, follow_up, congrats, check_in, custom",
        }

    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No person with id {person_id}"}

        last = (
            await db.execute(
                select(Interaction).where(Interaction.person_id == person_id)
                .order_by(Interaction.event_date.desc()).limit(1)
            )
        ).scalar_one_or_none()
        open_fu = (
            await db.execute(
                select(Interaction).where(
                    Interaction.person_id == person_id,
                    Interaction.follow_up_needed == True,  # noqa: E712
                ).order_by(Interaction.event_date.desc()).limit(1)
            )
        ).scalar_one_or_none()
        recent_events = (
            await db.execute(
                select(LifeEvent).where(LifeEvent.person_id == person_id)
                .order_by(LifeEvent.event_date.desc()).limit(1)
            )
        ).scalars().all()

    first = (p.name or "there").split(" ")[0].strip() or "there"
    recent_event = recent_events[0] if recent_events else None

    if purpose == "custom":
        if not (context or "").strip():
            return {
                "found": False,
                "error": "context_required",
                "message": "purpose 'custom' requires a non-empty `context` to embed in the draft.",
            }
        body = f"Hey {first},\n\n{context.strip()}"
    elif purpose == "follow_up" and open_fu and (open_fu.follow_up_note or open_fu.summary):
        subject = open_fu.follow_up_note or open_fu.summary
        date_str = open_fu.event_date.strftime("%b %d, %Y")
        body = (
            f"Hey {first}, following up on our conversation on {date_str} — "
            f"you mentioned: {subject.strip()}. I'd love to close the loop on that. "
            f"Let me know what works for you."
        )
    elif purpose == "follow_up":
        body = (
            f"Hey {first}, I wanted to follow up — nothing specific flagged on my end, "
            f"just checking in to see how you're doing."
        )
    elif purpose == "congrats" and recent_event:
        body = (
            f"Hey {first}, congratulations on {recent_event.title.strip()}! "
            f"That's fantastic news. Would love to hear all about it when you have a moment."
        )
    elif purpose == "congrats":
        body = (
            f"Hey {first}, just wanted to send a quick note of congratulations — "
            f"whatever you've got going on, I'm cheering for you."
        )
    elif purpose == "check_in":
        body = (
            f"Hey {first}, just checking in — no reason in particular. "
            f"Hope everything's going well on your end. Would be great to catch up soon."
        )
    else:  # reconnect
        if last and last.event_date:
            date_str = last.event_date.strftime("%b %d, %Y")
            topic = (last.summary or "our last chat").strip()
            body = (
                f"Hey {first}, it's been a while since we last caught up "
                f"({date_str}) — I was thinking about {topic}. "
                f"How have you been? Would love to reconnect soon."
            )
        else:
            body = (
                f"Hey {first}, it's been too long since we last talked. "
                f"I'd love to catch up and hear what you've been up to. How are things?"
            )

    return {
        "found": True,
        "draft": body,
        "person": {"id": p.id, "name": p.name},
        "purpose": purpose,
        "context_used": {
            "last_interaction": (
                {"date": last.event_date.strftime("%Y-%m-%d"), "summary": last.summary}
                if last else None
            ),
            "open_follow_up": (
                {"date": open_fu.event_date.strftime("%Y-%m-%d"), "note": open_fu.follow_up_note}
                if open_fu else None
            ),
            "recent_life_event": (
                {"date": recent_event.event_date.strftime("%Y-%m-%d"), "title": recent_event.title}
                if recent_event else None
            ),
        },
        "requires_approval": True,
        "status": "draft_only",
        "note": "Draft only — nothing was sent. Sending requires human approval outside this module.",
    }


# ─── Date parsing helpers ───────────────────────────────────────────

def _parse_datetime(s: str) -> Optional[datetime]:
    """Parse an ISO-ish datetime string to timezone-naive UTC."""
    if not s or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return dateutil.parser.parse(s.strip()).replace(tzinfo=None)
    except (ValueError, OverflowError, TypeError):
        return None


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_TIME_MAP = {
    "morning": (9, 0), "noon": (12, 0), "afternoon": (13, 0),
    "evening": (19, 0), "night": (21, 0), "midnight": (0, 0),
}


def _parse_due_at(s: str) -> Optional[datetime]:
    """Parse relative/absolute due times. Accepts 'tomorrow 9am', 'in 2 hours', ISO."""
    raw = (s or "").strip()
    if not raw:
        return None
    low = raw.lower()

    # Relative: "in N hours/minutes/days/weeks"
    m = re.match(r"^in\s+(\d+)\s+(hour|minute|day|week)s?$", low)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        now = _now()
        if unit == "hour":
            return now + timedelta(hours=n)
        if unit == "minute":
            return now + timedelta(minutes=n)
        if unit == "day":
            return now + timedelta(days=n)
        if unit == "week":
            return now + timedelta(weeks=n)

    now = _now()

    # Weekday: "monday", "next monday", "friday 9am"
    m = re.match(r"^(next\s+)?([a-z]+?)(\s+.*)?$", low)
    if m:
        day = m.group(2)
        if day in _WEEKDAYS:
            target = _WEEKDAYS.index(day)
            days_ahead = target - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            due = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
            tail = (m.group(3) or "").strip()
            if tail:
                t = _apply_time(tail, due)
                if t:
                    return t
            return due

    # "tomorrow", "tomorrow 9am", "today 5pm"
    if low.startswith("tomorrow"):
        base = now + timedelta(days=1)
        return _apply_time(raw[len("tomorrow"):], base) or base.replace(hour=9, minute=0, second=0, microsecond=0)
    if low.startswith("today"):
        return _apply_time(raw[len("today"):], now) or now

    # ISO / absolute
    parsed = _parse_datetime(raw)
    if parsed:
        return parsed
    return None


def _apply_time(spec: str, base: datetime) -> Optional[datetime]:
    """Apply a time spec ('9am', '9:30', 'evening') onto a base datetime."""
    if not spec:
        return None
    s = spec.strip().lower()
    if s in _TIME_MAP:
        h, mnt = _TIME_MAP[s]
        return base.replace(hour=h, minute=mnt, second=0, microsecond=0)
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if m.group(3) == "pm" and hour < 12:
            hour += 12
        if m.group(3) == "am" and hour == 12:
            hour = 0
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return None
