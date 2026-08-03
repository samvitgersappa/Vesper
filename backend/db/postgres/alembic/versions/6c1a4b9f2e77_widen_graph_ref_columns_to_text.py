"""widen graph ref columns to text

Revision ID: 6c1a4b9f2e77
Revises: a3f7b29d4c01
Create Date: 2026-08-02 10:25:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c1a4b9f2e77'
down_revision: Union[str, None] = 'a3f7b29d4c01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('graph_nodes', 'ref_id', existing_type=sa.String(length=100),
                    type_=sa.Text(), existing_nullable=True, schema='graph')
    op.alter_column('graph_nodes', 'ref_table', existing_type=sa.String(length=100),
                    type_=sa.Text(), existing_nullable=True, schema='graph')


def downgrade() -> None:
    op.alter_column('graph_nodes', 'ref_id', existing_type=sa.Text(),
                    type_=sa.String(length=100), existing_nullable=True, schema='graph')
    op.alter_column('graph_nodes', 'ref_table', existing_type=sa.Text(),
                    type_=sa.String(length=100), existing_nullable=True, schema='graph')
