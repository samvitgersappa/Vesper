"""Journal schema (plan.md §13) — vault-backed diary metadata.

`diary_entries` is a metadata layer over vault notes (plan §8.3): content lives
in the Obsidian vault file; this table stores mood/streak/tags/calendar data.
Port of ProjectVesper's `DiaryEntry` model with the vault rework:
- loses `content` (nullable=False Text) — content is in the vault file
- gains `vault_path` — path of the markdown note in the vault
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Boolean, Text, DateTime, JSON, Float,
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, _now, new_uuid

SCHEMA = "journal"


class DiaryCategory(str, enum.Enum):
    STUDY = "STUDY"
    HOBBY = "HOBBY"
    GENERAL = "GENERAL"


class DiaryEntry(Base):
    __tablename__ = "diary_entries"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[Optional[str]] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(
        SAEnum(DiaryCategory, values_callable=lambda x: [e.value for e in x]),
        default=DiaryCategory.GENERAL.value, index=True
    )
    # Vault-backed: content lives in the vault file at vault_path (plan §8.3).
    vault_path: Mapped[Optional[str]] = mapped_column(String(1000))
    mood: Mapped[Optional[str]] = mapped_column(String(10))  # emoji mood
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    entry_date: Mapped[Optional[object]] = mapped_column(DateTime, index=True)  # calendar date
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # §12.1: the Daily Journal Questionnaire marks the day complete when all
    # fixed questions are answered (or the 23:55 placeholder is written).
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[object] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[object] = mapped_column(DateTime, default=_now, onupdate=_now)


class Workout(Base):
    """Lightweight workout log (plan.md §4.1 / addendum §2.4).

    `date, activity, muscle_groups[], raw_text`. Deliberately sparse — some days
    will have nothing; answered via `journal.log_workout` at any time of day.
    """
    __tablename__ = "workouts"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    date: Mapped[object] = mapped_column(DateTime, nullable=False, index=True)
    activity: Mapped[Optional[str]] = mapped_column(String(200))
    muscle_groups: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime, default=_now, index=True)


class Spending(Base):
    """Lightweight spending log (plan.md §4.1 / addendum §2.4).

    `date, amount, category, raw_text`. One row per mentioned amount; category
    against a fixed taxonomy (Food, Travel/Transport, Shopping, Bills/Utilities,
    Health, Entertainment, Other), best-effort default "Other". Deliberately
    allowed to be sparse and inconsistent.
    """
    __tablename__ = "spending"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    date: Mapped[object] = mapped_column(DateTime, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="Other", index=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime, default=_now, index=True)
