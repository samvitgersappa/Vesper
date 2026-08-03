"""add catalyst swing trader tables (Part E)

Revision ID: b7e2c5d91a03
Revises: 6c1a4b9f2e77
Create Date: 2026-08-03 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2c5d91a03'
down_revision: Union[str, None] = '6c1a4b9f2e77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_catalyst_tables(op) -> None:
    op.create_table(
        'delivery_stats',
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('total_qty', sa.Integer(), nullable=True),
        sa.Column('total_val', sa.Float(), nullable=True),
        sa.Column('delivery_qty', sa.Integer(), nullable=True),
        sa.Column('delivery_pct', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('date', 'symbol', name='pk_delivery_stats'),
        schema='finance',
    )
    op.create_table(
        'market_sentiment_daily',
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('actor', sa.String(length=20), nullable=False),
        sa.Column('buy', sa.Float(), nullable=True),
        sa.Column('sell', sa.Float(), nullable=True),
        sa.Column('net', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('date', 'actor', name='pk_market_sentiment_daily'),
        schema='finance',
    )
    op.create_table(
        'index_options_sentiment',
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('index_name', sa.String(length=20), nullable=False),
        sa.Column('pcr', sa.Float(), nullable=True),
        sa.Column('ce_oi', sa.Float(), nullable=True),
        sa.Column('pe_oi', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('date', 'index_name', name='pk_index_options_sentiment'),
        schema='finance',
    )
    op.create_table(
        'market_breadth_daily',
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('advance', sa.Integer(), nullable=True),
        sa.Column('decline', sa.Integer(), nullable=True),
        sa.Column('pct_above_50dma', sa.Float(), nullable=True),
        sa.Column('pct_above_200dma', sa.Float(), nullable=True),
        sa.Column('highs_52w', sa.Integer(), nullable=True),
        sa.Column('lows_52w', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('date'),
        schema='finance',
    )
    op.create_table(
        'sector_scores_daily',
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('sector', sa.String(length=50), nullable=False),
        sa.Column('ret_20d', sa.Float(), nullable=True),
        sa.Column('dma_50', sa.Float(), nullable=True),
        sa.Column('momentum', sa.Float(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('date', 'sector', name='pk_sector_scores_daily'),
        schema='finance',
    )
    op.create_table(
        'catalyst_scores',
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('market_score', sa.Float(), nullable=True),
        sa.Column('sector_score', sa.Float(), nullable=True),
        sa.Column('stock_score', sa.Float(), nullable=True),
        sa.Column('composite_score', sa.Float(), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('catalyst_json', sa.Text(), nullable=True),
        sa.Column('catalyst_signal', sa.String(length=20), nullable=True),
        sa.Column('llm_analyzed', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('date', 'symbol', name='pk_catalyst_scores'),
        schema='finance',
    )
    op.create_table(
        'catalyst_candidates',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('stage', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='finance',
    )
    op.create_index('ix_catalyst_candidates_date', 'catalyst_candidates', ['date'], schema='finance')
    op.create_table(
        'catalyst_llm_usage',
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('calls_used', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('date'),
        schema='finance',
    )
    op.create_table(
        'catalyst_llm_calls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ts', sa.String(length=40), nullable=False),
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('response_json', sa.Text(), nullable=True),
        sa.Column('ok', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='finance',
    )
    op.create_index('ix_catalyst_llm_calls_date', 'catalyst_llm_calls', ['date'], schema='finance')
    op.create_table(
        'catalyst_positions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('entry_date', sa.String(length=20), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('atr', sa.Float(), nullable=True),
        sa.Column('stop_loss', sa.Float(), nullable=True),
        sa.Column('trailing_stop', sa.Float(), nullable=True),
        sa.Column('target', sa.Float(), nullable=True),
        sa.Column('days_held', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('exit_reason', sa.Text(), nullable=True),
        sa.Column('exit_date', sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='finance',
    )
    op.create_table(
        'catalyst_cost_estimates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('notional', sa.Float(), nullable=True),
        sa.Column('expected_slippage_bps', sa.Float(), nullable=True),
        sa.Column('estimated_cost', sa.Float(), nullable=True),
        sa.Column('target_pnl', sa.Float(), nullable=True),
        sa.Column('cost_target_ratio', sa.Float(), nullable=True),
        sa.Column('gate_passed', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='finance',
    )


def upgrade() -> None:
    _create_catalyst_tables(op)


def downgrade() -> None:
    for table in [
        'catalyst_cost_estimates', 'catalyst_positions', 'catalyst_llm_calls',
        'catalyst_llm_usage', 'catalyst_candidates', 'catalyst_scores',
        'sector_scores_daily', 'market_breadth_daily', 'index_options_sentiment',
        'market_sentiment_daily', 'delivery_stats',
    ]:
        op.drop_table(table, schema='finance')
