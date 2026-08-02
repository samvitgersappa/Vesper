"""add diary complete and hermes events

Additive migration on top of e379c81cabf3 (plan.md §12.1, addendum §2):
- journal.diary_entries.complete (boolean, default False) — the Daily Journal
  Questionnaire marks the day complete when all fixed questions are answered or
  the 23:55 placeholder is written.

Revision ID: a3f7b29d4c01
Revises: e379c81cabf3
Create Date: 2026-08-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f7b29d4c01'
down_revision: Union[str, None] = 'e379c81cabf3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'diary_entries',
        sa.Column('complete', sa.Boolean(), nullable=False, server_default=sa.false()),
        schema='journal',
    )


def downgrade() -> None:
    op.drop_column('diary_entries', 'complete', schema='journal')
