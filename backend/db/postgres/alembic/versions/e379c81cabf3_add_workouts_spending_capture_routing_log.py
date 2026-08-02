"""add workouts spending capture_routing_log

Additive migration on top of c2525e68347f (plan.md §4.1 / §7, addendum §2.4):
- journal.workouts   (date, activity, muscle_groups[], raw_text)
- journal.spending   (date, amount, category, raw_text)
- hermes.capture_routing_log (utterance routing audit trail)

Revision ID: e379c81cabf3
Revises: c2525e68347f
Create Date: 2026-08-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e379c81cabf3'
down_revision: Union[str, None] = 'c2525e68347f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'workouts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('activity', sa.String(length=200), nullable=True),
        sa.Column('muscle_groups', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='journal',
    )
    op.create_index('ix_workouts_date', 'workouts', ['date'], unique=False, schema='journal')
    op.create_index('ix_workouts_created_at', 'workouts', ['created_at'], unique=False, schema='journal')

    op.create_table(
        'spending',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='journal',
    )
    op.create_index('ix_spending_date', 'spending', ['date'], unique=False, schema='journal')
    op.create_index('ix_spending_category', 'spending', ['category'], unique=False, schema='journal')
    op.create_index('ix_spending_created_at', 'spending', ['created_at'], unique=False, schema='journal')

    op.create_table(
        'capture_routing_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ts', sa.DateTime(), nullable=False),
        sa.Column('utterance', sa.Text(), nullable=True),
        sa.Column('conversation_context', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('stored_in', sa.String(length=50), nullable=False),
        sa.Column('ref_id', sa.String(length=200), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('rule_fired', sa.String(length=50), nullable=True),
        sa.Column('raw_json', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='hermes',
    )
    op.create_index('ix_capture_routing_log_ts', 'capture_routing_log', ['ts'], unique=False, schema='hermes')


def downgrade() -> None:
    op.drop_index('ix_capture_routing_log_ts', table_name='capture_routing_log', schema='hermes')
    op.drop_table('capture_routing_log', schema='hermes')
    op.drop_index('ix_spending_created_at', table_name='spending', schema='journal')
    op.drop_index('ix_spending_category', table_name='spending', schema='journal')
    op.drop_index('ix_spending_date', table_name='spending', schema='journal')
    op.drop_table('spending', schema='journal')
    op.drop_index('ix_workouts_created_at', table_name='workouts', schema='journal')
    op.drop_index('ix_workouts_date', table_name='workouts', schema='journal')
    op.drop_table('workouts', schema='journal')
