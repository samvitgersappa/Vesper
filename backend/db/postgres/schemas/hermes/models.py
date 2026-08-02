"""Hermes schema (plan.md §13) — mirror of Hermes Agent's own audit logs.

Hermes Agent's native logs are the source of truth; this schema exists so
cross-module SQL reporting doesn't need to query Hermes Agent's own store
directly. A writer job mirrors tool-call and LLM usage records here.

Phase 2 defines the schema; the mirror writer is wired in Phase 3/4 once the
Hermes Agent instance is configured.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, _now

SCHEMA = "hermes"


class HermesToolCall(Base):
    """Mirror of Hermes Agent tool-call audit records."""
    __tablename__ = "hermes_tool_calls"
    __table_args__ = (
        Index("ix_hermes_tool_calls_ts", "ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    # Hermes Agent's own session/tool identifiers (from its native logs).
    session_id: Mapped[Optional[str]] = mapped_column(String(200))
    agent_tool_id: Mapped[Optional[str]] = mapped_column(String(200))
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    server_name: Mapped[Optional[str]] = mapped_column(String(100))
    inputs_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    outputs_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    is_error: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float)
    channel: Mapped[Optional[str]] = mapped_column(String(50))  # telegram | cli | ...


class HermesLLMUsage(Base):
    """Mirror of Hermes Agent LLM usage/cost records."""
    __tablename__ = "hermes_llm_usage"
    __table_args__ = (
        Index("ix_hermes_llm_usage_ts", "ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(200))
    model: Mapped[Optional[str]] = mapped_column(String(200))
    provider: Mapped[Optional[str]] = mapped_column(String(100))
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float)


class CaptureRoutingLog(Base):
    """Audit trail for knowledge.capture routing decisions (plan.md §4.1 / §7).

    One row per capture utterance: which store won, confidence, which routing
    rule fired, and the resulting ref_id. Makes "where did this actually go"
    auditable in bulk instead of spelunking by hand.
    """
    __tablename__ = "capture_routing_log"
    __table_args__ = (
        Index("ix_capture_routing_log_ts", "ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    utterance: Mapped[Optional[str]] = mapped_column(Text)
    conversation_context: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    # stored_in: "journal" | "vault_note" | "reminder" | "expense" | "workout" |
    #            "image_note" | "persona_only"
    stored_in: Mapped[str] = mapped_column(String(50), nullable=False)
    ref_id: Mapped[Optional[str]] = mapped_column(String(200))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    rule_fired: Mapped[Optional[str]] = mapped_column(String(50))  # e.g. "rule1".."rule8"
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
