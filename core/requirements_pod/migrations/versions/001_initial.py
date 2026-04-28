"""Initial schema: source_files and tasks tables

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_files",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("gcs_path", sa.String(1024), nullable=False),
        sa.Column("uploaded_by", sa.String(256), nullable=True),
        sa.Column("upload_time", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(256), nullable=True),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False, unique=True),
        sa.Column("task_heading", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_type", sa.String(32), nullable=False, server_default="task"),
        sa.Column("user_name", sa.String(256), nullable=True),
        sa.Column("task_source", sa.String(512), nullable=True),
        sa.Column(
            "source_file_id",
            sa.String(36),
            sa.ForeignKey("source_files.id"),
            nullable=True,
        ),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="extracted"),
        sa.Column("jira_id", sa.String(64), nullable=True),
        sa.Column("jira_url", sa.String(1024), nullable=True),
        sa.Column("raw_llm_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("source_files")
