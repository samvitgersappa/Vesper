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

from backend.db.base import Base, _now, new_uuid

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


# ── Catalyst Swing Trader (Part E) ─────────────────────────────────────
# Trader 6 ("catalyst_swing"). Storage tables for the data-acquisition
# pipeline (NSE bhavcopy/delivery, FII/DII, index PCR, sector indices,
# breadth) plus the Layer 1/2/3 scoring, LLM catalyst funnel, cost gate and
# swing-position state. All writes go through the worker/scheduler jobs —
# the Finance MCP/API layer stays read-only (plan §16).


class DeliveryStats(Base):
    """NSE Common Bhavcopy delivery data (delivery_stats)."""
    __tablename__ = "delivery_stats"
    __table_args__ = (
        PrimaryKeyConstraint("date", "symbol", name="pk_delivery_stats"),
        {"schema": SCHEMA},
    )

    date: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    total_qty: Mapped[Optional[int]] = mapped_column(Integer)
    total_val: Mapped[Optional[float]] = mapped_column(Float)
    delivery_qty: Mapped[Optional[int]] = mapped_column(Integer)
    delivery_pct: Mapped[Optional[float]] = mapped_column(Float)  # DELIV_PER


class MarketSentimentDaily(Base):
    """FII/DII provisional net flows (market_sentiment_daily)."""
    __tablename__ = "market_sentiment_daily"
    __table_args__ = (
        PrimaryKeyConstraint("date", "actor", name="pk_market_sentiment_daily"),
        {"schema": SCHEMA},
    )

    date: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)  # FII | DII
    buy: Mapped[Optional[float]] = mapped_column(Float)
    sell: Mapped[Optional[float]] = mapped_column(Float)
    net: Mapped[Optional[float]] = mapped_column(Float)


class IndexOptionsSentiment(Base):
    """Nifty/BankNifty index put-call ratio (index_options_sentiment)."""
    __tablename__ = "index_options_sentiment"
    __table_args__ = (
        PrimaryKeyConstraint("date", "index_name", name="pk_index_options_sentiment"),
        {"schema": SCHEMA},
    )

    date: Mapped[str] = mapped_column(String(20), nullable=False)
    index_name: Mapped[str] = mapped_column(String(20), nullable=False)  # NIFTY | BANKNIFTY
    pcr: Mapped[Optional[float]] = mapped_column(Float)
    ce_oi: Mapped[Optional[float]] = mapped_column(Float)
    pe_oi: Mapped[Optional[float]] = mapped_column(Float)


class MarketBreadthDaily(Base):
    """Breadth computed from equity_daily (market_breadth_daily)."""
    __tablename__ = "market_breadth_daily"
    __table_args__ = {"schema": SCHEMA}

    date: Mapped[str] = mapped_column(String(20), primary_key=True)
    advance: Mapped[Optional[int]] = mapped_column(Integer)
    decline: Mapped[Optional[int]] = mapped_column(Integer)
    pct_above_50dma: Mapped[Optional[float]] = mapped_column(Float)
    pct_above_200dma: Mapped[Optional[float]] = mapped_column(Float)
    highs_52w: Mapped[Optional[int]] = mapped_column(Integer)
    lows_52w: Mapped[Optional[int]] = mapped_column(Integer)


class SectorScoreDaily(Base):
    """Per-sector momentum/trend scores (sector_scores_daily)."""
    __tablename__ = "sector_scores_daily"
    __table_args__ = (
        PrimaryKeyConstraint("date", "sector", name="pk_sector_scores_daily"),
        {"schema": SCHEMA},
    )

    date: Mapped[str] = mapped_column(String(20), nullable=False)
    sector: Mapped[str] = mapped_column(String(50), nullable=False)
    ret_20d: Mapped[Optional[float]] = mapped_column(Float)
    dma_50: Mapped[Optional[float]] = mapped_column(Float)
    momentum: Mapped[Optional[float]] = mapped_column(Float)
    score: Mapped[Optional[float]] = mapped_column(Float)  # 0..1 normalized


class CatalystScore(Base):
    """Layer 1/2/3 + composite + LLM catalyst per symbol/day (catalyst_scores)."""
    __tablename__ = "catalyst_scores"
    __table_args__ = (
        PrimaryKeyConstraint("date", "symbol", name="pk_catalyst_scores"),
        {"schema": SCHEMA},
    )

    date: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(50))
    market_score: Mapped[Optional[float]] = mapped_column(Float)
    sector_score: Mapped[Optional[float]] = mapped_column(Float)
    stock_score: Mapped[Optional[float]] = mapped_column(Float)
    composite_score: Mapped[Optional[float]] = mapped_column(Float)
    rank: Mapped[Optional[int]] = mapped_column(Integer)
    catalyst_json: Mapped[Optional[str]] = mapped_column(Text)
    catalyst_signal: Mapped[Optional[str]] = mapped_column(String(20))  # positive | negative | none
    llm_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)


class CatalystCandidate(Base):
    """Watchlist-funnel log entry (catalyst_candidates)."""
    __tablename__ = "catalyst_candidates"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    date: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)  # market|sector|stock|llm|entered|rejected|expired
    reason: Mapped[Optional[str]] = mapped_column(Text)
    score: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="open")


class CatalystLlmUsage(Base):
    """Daily LLM-call counter (catalyst_llm_usage), capped per day."""
    __tablename__ = "catalyst_llm_usage"
    __table_args__ = {"schema": SCHEMA}

    date: Mapped[str] = mapped_column(String(20), primary_key=True)
    calls_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CatalystLlmCall(Base):
    """Per-call audit log (catalyst_llm_calls)."""
    __tablename__ = "catalyst_llm_calls"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40), nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(100))
    response_json: Mapped[Optional[str]] = mapped_column(Text)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)


class CatalystPosition(Base):
    """Swing-position state for exits (catalyst_positions)."""
    __tablename__ = "catalyst_positions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    entry_date: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    atr: Mapped[Optional[float]] = mapped_column(Float)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float)
    trailing_stop: Mapped[Optional[float]] = mapped_column(Float)
    target: Mapped[Optional[float]] = mapped_column(Float)
    days_held: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    exit_reason: Mapped[Optional[str]] = mapped_column(Text)
    exit_date: Mapped[Optional[str]] = mapped_column(String(20))


class CatalystCostEstimate(Base):
    """Per-candidate cost estimates for the cost gate (catalyst_cost_estimates)."""
    __tablename__ = "catalyst_cost_estimates"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    notional: Mapped[Optional[float]] = mapped_column(Float)
    expected_slippage_bps: Mapped[Optional[float]] = mapped_column(Float)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float)
    target_pnl: Mapped[Optional[float]] = mapped_column(Float)
    cost_target_ratio: Mapped[Optional[float]] = mapped_column(Float)
    gate_passed: Mapped[Optional[bool]] = mapped_column(Boolean)
