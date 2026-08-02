"""Finance schema (plan.md §13) — ported from Quiver's SQLite state.

Ports Quiver's `backend/data/sqlite_client.py` schema into SQLAlchemy models in
the `finance` Postgres schema. Preserves the composite keys documented in
Quiver's README/INVENTORY:
- `paper_holdings`: composite PK (trader_id, ticker)
- `paper_nav_history`: composite PK (trader_id, date)

The DuckDB/Parquet feature store stays in DuckDB unchanged (see
`backend/db/duckdb_client.py`); only the mutable transactional state moves here.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, JSON,
    PrimaryKeyConstraint, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, _now

SCHEMA = "finance"


class PaperAccount(Base):
    """Per-trader account balance + pending settlements."""
    __tablename__ = "paper_account"
    __table_args__ = {"schema": SCHEMA}

    trader_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    available_cash: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    settled_cash: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    blocked_cash: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pending_settlements: Mapped[Optional[str]] = mapped_column(Text, default="[]")


class PaperHolding(Base):
    """Current holdings per trader. Composite PK (trader_id, ticker)."""
    __tablename__ = "paper_holdings"
    __table_args__ = (
        PrimaryKeyConstraint("trader_id", "ticker", name="pk_paper_holdings"),
        {"schema": SCHEMA},
    )

    trader_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ticker: Mapped[str] = mapped_column(String(50), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_price: Mapped[Optional[float]] = mapped_column(Float)
    buy_date: Mapped[Optional[str]] = mapped_column(String(20), default="")


class PaperTrade(Base):
    """Append-only trade log."""
    __tablename__ = "paper_trades"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    trader_id: Mapped[str] = mapped_column(String(100), nullable=False)
    trade_date: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_price: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    slippage_bps: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    cost_total: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    cost_breakdown: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    reason: Mapped[Optional[str]] = mapped_column(Text, default="")
    realized_pnl: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    tax_type: Mapped[Optional[str]] = mapped_column(String(20), default="")
    order_status: Mapped[Optional[str]] = mapped_column(String(20), default="EXECUTED")


class PaperNavHistory(Base):
    """Daily NAV snapshots. Composite PK (trader_id, date)."""
    __tablename__ = "paper_nav_history"
    __table_args__ = (
        PrimaryKeyConstraint("trader_id", "date", name="pk_paper_nav_history"),
        {"schema": SCHEMA},
    )

    trader_id: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    holdings_value: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    n_positions: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    day_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    cumulative_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    unrealized_stcg: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    unrealized_ltcg: Mapped[Optional[float]] = mapped_column(Float, default=0.0)


class JobRun(Base):
    """Scheduler job-run history."""
    __tablename__ = "job_runs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    finished_at: Mapped[Optional[str]] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    rows_processed: Mapped[Optional[int]] = mapped_column(Integer, default=0)


class DashboardSummary(Base):
    """Precomputed daily dashboard snapshot."""
    __tablename__ = "dashboard_summary"
    __table_args__ = {"schema": SCHEMA}

    date: Mapped[str] = mapped_column(String(20), primary_key=True)
    macro_snapshot: Mapped[Optional[str]] = mapped_column(Text)
    last_updated: Mapped[Optional[str]] = mapped_column(String(40))


class ExperimentIndex(Base):
    """Experiment tracking (Phase 1 §3.2)."""
    __tablename__ = "experiments_index"
    __table_args__ = {"schema": SCHEMA}

    experiment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(String(40))
    sharpe: Mapped[Optional[float]] = mapped_column(Float)
    cagr: Mapped[Optional[float]] = mapped_column(Float)


class ResearchExperiment(Base):
    """Permanent experiment records (Phase 5 research DB)."""
    __tablename__ = "research_experiments"
    __table_args__ = {"schema": SCHEMA}

    experiment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[Optional[str]] = mapped_column(String(100), default="")
    params_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    metrics_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    git_commit: Mapped[Optional[str]] = mapped_column(String(100), default="")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[Optional[str]] = mapped_column(String(30), default="active")
    decision: Mapped[Optional[str]] = mapped_column(String(30), default="pending")
    decision_rationale: Mapped[Optional[str]] = mapped_column(Text, default="")
    superseded_by: Mapped[Optional[str]] = mapped_column(String(100), default="")
    validation_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    paper_days: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    manual_approved: Mapped[Optional[int]] = mapped_column(Integer, default=0)


class FreezeVersion(Base):
    """Freeze/promotion audit trail."""
    __tablename__ = "freeze_versions"
    __table_args__ = (
        PrimaryKeyConstraint("strategy_id", "version", name="pk_freeze_versions"),
        {"schema": SCHEMA},
    )

    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    frozen_date: Mapped[str] = mapped_column(String(40), nullable=False)
    git_commit: Mapped[str] = mapped_column(String(100), nullable=False)
    experiment_id: Mapped[Optional[str]] = mapped_column(String(100), default="")
    rationale: Mapped[Optional[str]] = mapped_column(Text, default="")
    manual_approved: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    created_at: Mapped[Optional[str]] = mapped_column(String(40))


class ModelRegistryEntry(Base):
    """Permanent strategy-version identity (model registry)."""
    __tablename__ = "model_registry"
    __table_args__ = {"schema": SCHEMA}

    uuid: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_uuid: Mapped[Optional[str]] = mapped_column(String(100), default="")
    created_at: Mapped[Optional[str]] = mapped_column(String(40))
    promoted_at: Mapped[Optional[str]] = mapped_column(String(40), default="")
    status: Mapped[Optional[str]] = mapped_column(String(30), default="research")
    validation_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    paper_perf_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    git_commit: Mapped[Optional[str]] = mapped_column(String(100), default="")
    notes: Mapped[Optional[str]] = mapped_column(Text, default="")
    params_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    frozen: Mapped[Optional[int]] = mapped_column(Integer, default=0)


class ModelHistory(Base):
    """Model-registry status transitions."""
    __tablename__ = "model_history"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_uuid: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[Optional[str]] = mapped_column(String(30), default="")
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    at: Mapped[Optional[str]] = mapped_column(String(40))
    reason: Mapped[Optional[str]] = mapped_column(Text, default="")
    user: Mapped[Optional[str]] = mapped_column(String(100), default="system")


class DatasetRegistryEntry(Base):
    """Immutable dataset version records."""
    __tablename__ = "dataset_registry"
    __table_args__ = {"schema": SCHEMA}

    uuid: Mapped[str] = mapped_column(String(100), primary_key=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(40))
    universe_size: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    nifty500_membership_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    macro_snapshot_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    feature_store_version: Mapped[Optional[str]] = mapped_column(String(100), default="")
    factor_engine_version: Mapped[Optional[str]] = mapped_column(String(100), default="")
    duckdb_version: Mapped[Optional[str]] = mapped_column(String(100), default="")
    parquet_hashes_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    git_commit: Mapped[Optional[str]] = mapped_column(String(100), default="")
    notes: Mapped[Optional[str]] = mapped_column(Text, default="")
    source: Mapped[Optional[str]] = mapped_column(String(30), default="automatic")


class AuditLogEntry(Base):
    """Append-only audit ledger for automated actions."""
    __tablename__ = "audit_log"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40), nullable=False)
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    inputs_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    outputs_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    result: Mapped[Optional[str]] = mapped_column(String(20), default="ok")
    user: Mapped[Optional[str]] = mapped_column(String(100), default="system")
    reason: Mapped[Optional[str]] = mapped_column(Text, default="")


class NotebookEntry(Base):
    """Research notebook — institutional memory of experiments."""
    __tablename__ = "notebook_entries"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text, default="")
    method: Mapped[Optional[str]] = mapped_column(Text, default="")
    params_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    dataset_uuid: Mapped[Optional[str]] = mapped_column(String(100), default="")
    strategy_uuid: Mapped[Optional[str]] = mapped_column(String(100), default="")
    results_json: Mapped[Optional[str]] = mapped_column(Text, default="{}")
    validation: Mapped[Optional[str]] = mapped_column(Text, default="")
    decision: Mapped[Optional[str]] = mapped_column(String(30), default="pending")
    decision_rationale: Mapped[Optional[str]] = mapped_column(Text, default="")
    lessons: Mapped[Optional[str]] = mapped_column(Text, default="")
    final_status: Mapped[Optional[str]] = mapped_column(String(30), default="active")
    tags: Mapped[Optional[str]] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class DivergenceMetric(Base):
    """Live vs backtest divergence observations."""
    __tablename__ = "divergence_metrics"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    as_of: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_json: Mapped[str] = mapped_column(Text, nullable=False)
    actual_json: Mapped[str] = mapped_column(Text, nullable=False)
    tracking_error: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    prediction_error: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    drift: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    alert: Mapped[Optional[str]] = mapped_column(Text, default="")
