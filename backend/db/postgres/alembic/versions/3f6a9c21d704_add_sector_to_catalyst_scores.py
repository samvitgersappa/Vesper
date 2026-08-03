"""add sector column to catalyst_scores

Revision ID: 3f6a9c21d704
Revises: b7e2c5d91a03
Create Date: 2026-08-03 12:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f6a9c21d704'
down_revision: Union[str, None] = 'b7e2c5d91a03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('catalyst_scores', sa.Column('sector', sa.String(length=50), nullable=True), schema='finance')


def downgrade() -> None:
    op.drop_column('catalyst_scores', 'sector', schema='finance')
