"""Add priority, reporter, sprint, fix_version, story_points, acceptance_criteria to tasks

Revision ID: 002
Revises: 001
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("priority", sa.String(32), nullable=True))
    op.add_column("tasks", sa.Column("reporter", sa.String(256), nullable=True))
    op.add_column("tasks", sa.Column("sprint", sa.String(256), nullable=True))
    op.add_column("tasks", sa.Column("fix_version", sa.String(256), nullable=True))
    op.add_column("tasks", sa.Column("story_points", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("acceptance_criteria", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "acceptance_criteria")
    op.drop_column("tasks", "story_points")
    op.drop_column("tasks", "fix_version")
    op.drop_column("tasks", "sprint")
    op.drop_column("tasks", "reporter")
    op.drop_column("tasks", "priority")
