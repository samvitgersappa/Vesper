"""add catalyst news capture table (Part E)

Revision ID: a2e5f8c41d90
Revises: 9d4f7c2b10ae
Create Date: 2026-08-03 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2e5f8c41d90'
down_revision: Union[str, None] = '9d4f7c2b10ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'catalyst_news',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('date', sa.String(length=20), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('source', sa.String(length=200), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('published_at', sa.String(length=40), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='finance',
    )
    op.create_index(
        'ix_catalyst_news_date_symbol', 'catalyst_news', ['date', 'symbol'], schema='finance'
    )


def downgrade() -> None:
    op.drop_table('catalyst_news', schema='finance')
