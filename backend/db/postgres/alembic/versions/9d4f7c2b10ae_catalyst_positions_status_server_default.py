"""catalyst positions status server default (open)

Revision ID: 9d4f7c2b10ae
Revises: 3f6a9c21d704
Create Date: 2026-08-03 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d4f7c2b10ae'
down_revision: Union[str, None] = '3f6a9c21d704'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE finance.catalyst_positions SET status = 'open' WHERE status IS NULL"
    ))
    op.alter_column(
        'catalyst_positions', 'status',
        existing_type=sa.String(length=20),
        server_default='open',
        schema='finance',
    )


def downgrade() -> None:
    op.alter_column(
        'catalyst_positions', 'status',
        existing_type=sa.String(length=20),
        server_default=None,
        schema='finance',
    )
