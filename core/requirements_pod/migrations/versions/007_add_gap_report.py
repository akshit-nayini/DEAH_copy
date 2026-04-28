"""add gap_report to tasks and coverage_gaps to source files

Revision ID: 007
Revises: 006
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "req_agent_tasks",
        sa.Column("gap_report", sa.Text, nullable=True),
    )
    op.add_column(
        "req_agent_input",
        sa.Column("coverage_gaps", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("req_agent_tasks", "gap_report")
    op.drop_column("req_agent_input", "coverage_gaps")
