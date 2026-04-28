"""add schedule_interval to req_agent_tasks

Revision ID: 005
Revises: 004
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "req_agent_tasks",
        sa.Column("schedule_interval", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("req_agent_tasks", "schedule_interval")
