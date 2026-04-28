"""Add confidence_score to tasks

Revision ID: 003
Revises: 002
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("confidence_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "confidence_score")
