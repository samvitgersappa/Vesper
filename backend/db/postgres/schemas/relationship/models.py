"""Relationship OS schema (plan.md §13) — ported from ProjectVesper wholesale.

Port of ProjectVesper's `backend/app/models.py` (21 tables). Schema name changes
from default to `relationship`; table definitions otherwise unchanged. The
journal-specific tables (`diary_entries`) and study tables (`tests`, `mock_tests`)
moved to their own schemas (`journal`, `study`) per plan.md §13 — see those
modules. `cron_runs` and `person_field_history` stay here (extra vs. the
"19 table" README claim — documented in INVENTORY.md).

Foreign keys reference tables by their unqualified name; Postgres resolves them
within the search_path. Set `search_path=relationship` for connections that
operate on these tables.
"""

import enum
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, JSON,
    ForeignKey, Enum as SAEnum, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, _now, new_uuid

SCHEMA = "relationship"


# ─── Enums ──────────────────────────────────────────────────────

class DiaryCategory(str, enum.Enum):
    STUDY = "STUDY"
    HOBBY = "HOBBY"
    GENERAL = "GENERAL"


class Category(str, enum.Enum):
    FAMILY = "FAMILY"
    COUSINS = "COUSINS"
    RELATIVES = "RELATIVES"
    FRIENDS = "FRIENDS"
    COLLEAGUES = "COLLEAGUES"
    NEW_CONTACT = "NEW_CONTACT"
    NETWORK = "NETWORK"
    IMPORTANT = "IMPORTANT"


class RelationType(str, enum.Enum):
    FAMILY = "FAMILY"
    FRIEND = "FRIEND"
    COLLEAGUE = "COLLEAGUE"
    MENTOR = "MENTOR"
    OTHER = "OTHER"


class InteractionType(str, enum.Enum):
    CALL = "CALL"
    MESSAGE = "MESSAGE"
    MEETING = "MEETING"
    EMAIL = "EMAIL"
    SOCIAL = "SOCIAL"
    BIRTHDAY_WISH = "BIRTHDAY_WISH"
    OTHER = "OTHER"


class RelationshipStrength(str, enum.Enum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"


# ─── Models ──────────────────────────────────────────────────────

class Cluster(Base):
    __tablename__ = "clusters"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    color: Mapped[Optional[str]] = mapped_column(String(7), default="#ffffff")

    cx: Mapped[Optional[float]] = mapped_column(Float)
    cy: Mapped[Optional[float]] = mapped_column(Float)
    cz: Mapped[Optional[float]] = mapped_column(Float)
    width: Mapped[Optional[float]] = mapped_column(Float)
    height: Mapped[Optional[float]] = mapped_column(Float)
    depth: Mapped[Optional[float]] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    persons: Mapped[List["Person"]] = relationship(back_populates="cluster")


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(100))
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    occupation: Mapped[Optional[str]] = mapped_column(String(200))
    company: Mapped[Optional[str]] = mapped_column(String(200))
    bio: Mapped[Optional[str]] = mapped_column(Text)
    hobbies: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    gender: Mapped[Optional[str]] = mapped_column(String(50))
    age: Mapped[Optional[int]] = mapped_column(Integer)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500))

    city: Mapped[Optional[str]] = mapped_column(String(100))
    country: Mapped[Optional[str]] = mapped_column(String(100))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    category: Mapped[str] = mapped_column(
        SAEnum(Category, values_callable=lambda x: [e.value for e in x]),
        default=Category.NETWORK.value
    )
    relation_type: Mapped[str] = mapped_column(
        SAEnum(RelationType, values_callable=lambda x: [e.value for e in x]),
        default=RelationType.OTHER.value
    )

    contact_frequency_days: Mapped[Optional[int]] = mapped_column(Integer)
    last_contacted: Mapped[Optional[datetime]] = mapped_column(DateTime)
    health_score: Mapped[float] = mapped_column(Float, default=1.0)

    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    twitter_handle: Mapped[Optional[str]] = mapped_column(String(100))
    instagram_handle: Mapped[Optional[str]] = mapped_column(String(100))
    github_username: Mapped[Optional[str]] = mapped_column(String(100))

    birthday: Mapped[Optional[datetime]] = mapped_column(DateTime)
    anniversary: Mapped[Optional[datetime]] = mapped_column(DateTime)

    introduced_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="SET NULL")
    )
    topics_of_interest: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    meeting_place: Mapped[Optional[str]] = mapped_column(String(200))
    rss_feed_url: Mapped[Optional[str]] = mapped_column(String(500))
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    streak_weeks: Mapped[int] = mapped_column(Integer, default=0)
    streak_last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime)
    betweenness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    community_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    profile_notes: Mapped[Optional[str]] = mapped_column(Text)
    important_events: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("relationship.clusters.id", ondelete="SET NULL")
    )
    fx: Mapped[Optional[float]] = mapped_column(Float)
    fy: Mapped[Optional[float]] = mapped_column(Float)
    fz: Mapped[Optional[float]] = mapped_column(Float)

    cluster: Mapped[Optional["Cluster"]] = relationship(back_populates="persons")
    interactions: Mapped[List["Interaction"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    notes: Mapped[List["Note"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    life_events: Mapped[List["LifeEvent"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    gift_ideas: Mapped[List["GiftIdea"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    rss_entries: Mapped[List["RSSEntry"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    person_tags: Mapped[List["PersonTag"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    introduced_by: Mapped[Optional["Person"]] = relationship(
        remote_side="Person.id", foreign_keys=[introduced_by_id]
    )


class Interaction(Base):
    __tablename__ = "interactions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(
        SAEnum(InteractionType, values_callable=lambda x: [e.value for e in x]),
        default=InteractionType.OTHER.value
    )
    summary: Mapped[Optional[str]] = mapped_column(Text)
    sentiment: Mapped[Optional[str]] = mapped_column(String(20))
    key_topics: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    location: Mapped[Optional[str]] = mapped_column(String(200))
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    follow_up_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    follow_up_note: Mapped[Optional[str]] = mapped_column(Text)

    group_interaction_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("relationship.group_interactions.id", ondelete="SET NULL")
    )

    event_date: Mapped[datetime] = mapped_column(DateTime, default=_now)
    initiated_by: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    client_uuid: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, unique=True, index=True)

    person: Mapped["Person"] = relationship(back_populates="interactions")
    group_interaction: Mapped[Optional["GroupInteraction"]] = relationship(
        back_populates="interactions"
    )


class GroupInteraction(Base):
    __tablename__ = "group_interactions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(300))
    event_date: Mapped[datetime] = mapped_column(DateTime, default=_now)
    location: Mapped[Optional[str]] = mapped_column(String(200))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    person_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    interactions: Mapped[List["Interaction"]] = relationship(
        back_populates="group_interaction"
    )


class Relationship(Base):
    __tablename__ = "relationships"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_a_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    person_b_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[Optional[str]] = mapped_column(String(100))
    strength: Mapped[str] = mapped_column(
        SAEnum(RelationshipStrength, values_callable=lambda x: [e.value for e in x]),
        default=RelationshipStrength.MEDIUM.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    person_a: Mapped["Person"] = relationship(foreign_keys=[person_a_id])
    person_b: Mapped["Person"] = relationship(foreign_keys=[person_b_id])


class Introduction(Base):
    __tablename__ = "introductions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_a_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id"), nullable=False, index=True
    )
    person_b_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id"), nullable=False, index=True
    )
    made_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PersonFieldHistory(Base):
    __tablename__ = "person_field_history"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RelationshipScoreSnapshot(Base):
    __tablename__ = "relationship_scores"
    __table_args__ = (
        UniqueConstraint("relationship_id", "week_of", name="uq_relationship_week"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    relationship_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.relationships.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    week_of: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[Optional[str]] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_type: Mapped[str] = mapped_column(String(50), default="custom")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    person: Mapped[Optional["Person"]] = relationship()


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    color: Mapped[Optional[str]] = mapped_column(String(7))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PersonTag(Base):
    __tablename__ = "person_tags"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.tags.id", ondelete="CASCADE"), index=True
    )

    person: Mapped["Person"] = relationship(back_populates="person_tags")
    tag: Mapped["Tag"] = relationship()


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    person: Mapped["Person"] = relationship(back_populates="notes")


class LifeEvent(Base):
    __tablename__ = "life_events"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    event_date: Mapped[datetime] = mapped_column(DateTime)
    icon: Mapped[Optional[str]] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    person: Mapped["Person"] = relationship(back_populates="life_events")


class GiftIdea(Base):
    __tablename__ = "gift_ideas"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500))
    price_range: Mapped[Optional[str]] = mapped_column(String(50))
    occasion: Mapped[Optional[str]] = mapped_column(String(100))
    is_given: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    person: Mapped["Person"] = relationship(back_populates="gift_ideas")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RSSEntry(Base):
    __tablename__ = "rss_entries"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(500))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    published: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    person: Mapped["Person"] = relationship(back_populates="rss_entries")


class HealthSnapshot(Base):
    __tablename__ = "health_snapshots"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("relationship.persons.id", ondelete="CASCADE"), index=True
    )
    health_score: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CronRun(Base):
    __tablename__ = "cron_runs"
    __table_args__ = {"schema": SCHEMA}

    job_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
