"""add assignee, start_date, due_date to req_agent_tasks

Revision ID: 006
Revises: 005
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "req_agent_tasks",
        sa.Column("assignee", sa.String(256), nullable=True),
    )
    op.add_column(
        "req_agent_tasks",
        sa.Column("start_date", sa.DateTime, nullable=True),
    )
    op.add_column(
        "req_agent_tasks",
        sa.Column("due_date", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("req_agent_tasks", "due_date")
    op.drop_column("req_agent_tasks", "start_date")
    op.drop_column("req_agent_tasks", "assignee")
