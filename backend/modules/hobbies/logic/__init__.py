"""hobbies module business logic.

Hobbies is a JSON list column on `persons` (ProjectVesper models). This module
exposes read/update over that column plus a simple tracker rollup (which
hobbies are most common across contacts). No dedicated hobbies schema — the
plan.md §13 data layer has no hobbies table; the column stays in relationship.
"""

from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres.schemas.relationship.models import Person
from backend.modules.db import session_factory


def _person_hobbies(p: Person) -> list[str]:
    return [str(h) for h in (p.hobbies or [])]


async def list_all() -> dict[str, Any]:
    """Every hobby across active contacts + a count of people sharing it."""
    async with session_factory()() as db:
        res = await db.execute(
            select(Person).where(Person.is_archived.is_(False))
        )
        persons = res.scalars().all()
    hobby_counts: dict[str, int] = {}
    by_person = []
    for p in persons:
        hs = _person_hobbies(p)
        for h in hs:
            hobby_counts[h] = hobby_counts.get(h, 0) + 1
        if hs:
            by_person.append({"person_id": p.id, "name": p.name, "hobbies": hs})
    return {
        "hobbies": [{"name": name, "person_count": cnt}
                    for name, cnt in sorted(hobby_counts.items(), key=lambda kv: (-kv[1], kv[0]))],
        "by_person": by_person,
    }


async def get_person_hobbies(person_id: str) -> dict[str, Any]:
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No contact found for '{person_id}'"}
        return {"found": True, "person_id": p.id, "name": p.name, "hobbies": _person_hobbies(p)}


async def add_hobby(person_id: str, hobby: str) -> dict[str, Any]:
    hobby = hobby.strip()
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No contact found for '{person_id}'"}
        hs = p.hobbies or []
        if hobby and hobby not in hs:
            hs.append(hobby)
            p.hobbies = hs
            await db.commit()
        return {"found": True, "person_id": p.id, "name": p.name, "hobbies": _person_hobbies(p)}


async def remove_hobby(person_id: str, hobby: str) -> dict[str, Any]:
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No contact found for '{person_id}'"}
        hs = [h for h in (p.hobbies or []) if h.lower() != hobby.lower()]
        p.hobbies = hs
        await db.commit()
        return {"found": True, "person_id": p.id, "name": p.name, "hobbies": _person_hobbies(p)}


async def set_hobbies(person_id: str, hobbies: list[str]) -> dict[str, Any]:
    cleaned = [h.strip() for h in hobbies if h.strip()]
    async with session_factory()() as db:
        p = await db.get(Person, person_id)
        if not p:
            return {"found": False, "message": f"No contact found for '{person_id}'"}
        p.hobbies = cleaned
        await db.commit()
        return {"found": True, "person_id": p.id, "name": p.name, "hobbies": _person_hobbies(p)}
