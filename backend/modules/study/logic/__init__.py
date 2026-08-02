"""Study module business logic — ported from ProjectVesper `tests` router.

ProjectVesper exposes the Study domain via `/api/v1/tests` (list/create tests,
add/delete mock tests) with no deeper math. This port keeps that CRUD surface
and adds `percentiles` (percentile of each mock test's total_score within that
test's mock tests) and a simple exam-readiness summary against `target_date`.

Reads/writes the `study` Postgres schema (Phase 2) instead of ProjectVesper's
default-schema SQLite tables.
"""

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres.schemas.study.models import MockTest, Test
from backend.modules.db import session_factory


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _test_dict(t: Test) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "target_date": t.target_date.isoformat() if t.target_date else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "mock_test_count": len(t.mock_tests) if t.mock_tests else 0,
    }


def _mock_dict(m: MockTest) -> dict[str, Any]:
    return {
        "id": m.id,
        "test_id": m.test_id,
        "date": m.date.isoformat() if m.date else None,
        "total_score": m.total_score,
        "subject_scores": m.subject_scores or {},
    }


async def list_tests() -> list[dict[str, Any]]:
    """All exams, newest first."""
    async with session_factory()() as db:
        res = await db.execute(
            select(Test).order_by(Test.created_at.desc())
        )
        return [_test_dict(t) for t in res.scalars().all()]


async def get_test(test_id: str) -> Optional[dict[str, Any]]:
    """One exam including its mock tests."""
    async with session_factory()() as db:
        t = await db.get(Test, test_id)
        if not t:
            return None
        return _test_dict(t)


async def create_test(name: str, target_date: Optional[str] = None) -> dict[str, Any]:
    """Create an exam. target_date ISO (YYYY-MM-DD) or empty."""
    t = Test(name=name, target_date=_parse_date(target_date), created_at=_now())
    async with session_factory()() as db:
        db.add(t)
        await db.commit()
        await db.refresh(t)
        return _test_dict(t)


async def delete_test(test_id: str) -> bool:
    """Delete an exam (cascades to its mock tests)."""
    async with session_factory()() as db:
        t = await db.get(Test, test_id)
        if not t:
            return False
        await db.delete(t)
        await db.commit()
        return True


async def list_mock_tests(test_id: str) -> list[dict[str, Any]]:
    """All mock tests for an exam, oldest first."""
    async with session_factory()() as db:
        res = await db.execute(
            select(MockTest)
            .where(MockTest.test_id == test_id)
            .order_by(MockTest.date.asc())
        )
        return [_mock_dict(m) for m in res.scalars().all()]


async def add_mock_test(
    test_id: str,
    total_score: float,
    subject_scores: Optional[dict] = None,
    date: Optional[str] = None,
) -> dict[str, Any]:
    """Record a mock test score for an exam."""
    m = MockTest(
        test_id=test_id,
        total_score=total_score,
        subject_scores=subject_scores or {},
        date=_parse_date(date) or _now(),
    )
    async with session_factory()() as db:
        db.add(m)
        await db.commit()
        await db.refresh(m)
        return _mock_dict(m)


async def delete_mock_test(mock_id: str) -> bool:
    """Delete a mock test."""
    async with session_factory()() as db:
        m = await db.get(MockTest, mock_id)
        if not m:
            return False
        await db.delete(m)
        await db.commit()
        return True


async def percentiles(test_id: str) -> dict[str, Any]:
    """Percentile rank of each mock test's total_score within the exam.

    Percentile = fraction of mock tests (including itself) at or below the
    score, scaled to 0-100. Requires >=1 mock test.
    """
    async with session_factory()() as db:
        res = await db.execute(
            select(MockTest)
            .where(MockTest.test_id == test_id)
            .order_by(MockTest.date.asc())
        )
        mocks = res.scalars().all()
        if not mocks:
            return {"test_id": test_id, "mock_tests": [], "message": "No mock tests recorded"}
        scores = [m.total_score for m in mocks]
        rows = []
        for m in mocks:
            # percentile: percentage of scores <= this score
            below = sum(1 for s in scores if s <= m.total_score)
            pct = round(below / len(scores) * 100, 1)
            rows.append({"mock_id": m.id, "total_score": m.total_score, "percentile": pct})
        return {"test_id": test_id, "mock_tests": rows}


async def readiness(test_id: str) -> dict[str, Any]:
    """Exam-readiness summary: latest score trend + days to target date.

    Trend = latest percentile minus first percentile; readiness flag:
    - "on_track" if latest percentile >= 50 and trend >= 0
    - "improving" if trend > 0
    - "needs_attention" otherwise
    """
    async with session_factory()() as db:
        res = await db.execute(
            select(MockTest)
            .where(MockTest.test_id == test_id)
            .order_by(MockTest.date.asc())
        )
        mocks = res.scalars().all()
        t = await db.get(Test, test_id)
        if not mocks:
            return {"test_id": test_id, "readiness": "no_data", "days_to_exam": None,
                    "latest_percentile": None, "trend": None}
        scores = [m.total_score for m in mocks]
        pcts = [round(sum(1 for s in scores if s <= m.total_score) / len(scores) * 100, 1)
                for m in mocks]
        trend = round(pcts[-1] - pcts[0], 1)
        days = None
        if t and t.target_date:
            days = (t.target_date.date() - date.today()).days
        if pcts[-1] >= 50 and trend >= 0:
            flag = "on_track"
        elif trend > 0:
            flag = "improving"
        else:
            flag = "needs_attention"
        return {
            "test_id": test_id,
            "readiness": flag,
            "days_to_exam": days,
            "latest_percentile": pcts[-1],
            "trend": trend,
            "mock_count": len(mocks),
        }


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
