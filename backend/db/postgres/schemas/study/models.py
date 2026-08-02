"""Study schema (plan.md §13) — ported from ProjectVesper unchanged.

`tests` and `mock_tests` move from ProjectVesper's default schema to `study`.
Table definitions otherwise unchanged.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import String, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, _now, new_uuid

SCHEMA = "study"


class Test(Base):
    __tablename__ = "tests"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    target_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    mock_tests: Mapped[List["MockTest"]] = relationship(
        back_populates="test", cascade="all, delete-orphan"
    )


class MockTest(Base):
    __tablename__ = "mock_tests"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    test_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("study.tests.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[datetime] = mapped_column(DateTime, default=_now)
    total_score: Mapped[float] = mapped_column(Float)
    subject_scores: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    test: Mapped["Test"] = relationship(back_populates="mock_tests")
