"""Rename source_files→req_agent_input, tasks→req_agent_tasks; replace gcs_path with file_path+storage_location

Revision ID: 004
Revises: 003
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create new req_agent_input table (replaces source_files)
    op.create_table(
        "req_agent_input",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("storage_location", sa.String(64), nullable=False, server_default="gcs"),
        sa.Column("uploaded_by", sa.String(256), nullable=True),
        sa.Column("upload_time", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(256), nullable=True),
    )

    # 2. Create new req_agent_tasks table (replaces tasks)
    op.create_table(
        "req_agent_tasks",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False, unique=True),
        sa.Column("task_heading", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_type", sa.String(32), nullable=False, server_default="task"),
        sa.Column("user_name", sa.String(256), nullable=True),
        sa.Column("task_source", sa.String(512), nullable=True),
        sa.Column("source_file_id", sa.String(36), sa.ForeignKey("req_agent_input.id"), nullable=True),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="extracted"),
        sa.Column("jira_id", sa.String(64), nullable=True),
        sa.Column("jira_url", sa.String(1024), nullable=True),
        sa.Column("raw_llm_json", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(32), nullable=True),
        sa.Column("reporter", sa.String(256), nullable=True),
        sa.Column("sprint", sa.String(256), nullable=True),
        sa.Column("fix_version", sa.String(256), nullable=True),
        sa.Column("story_points", sa.Integer(), nullable=True),
        sa.Column("acceptance_criteria", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
    )

    # 3. Drop old tables (empty — no data to migrate)
    op.drop_table("tasks")
    op.drop_table("source_files")


def downgrade() -> None:
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
        sa.Column("source_file_id", sa.String(36), sa.ForeignKey("source_files.id"), nullable=True),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="extracted"),
        sa.Column("jira_id", sa.String(64), nullable=True),
        sa.Column("jira_url", sa.String(1024), nullable=True),
        sa.Column("raw_llm_json", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(32), nullable=True),
        sa.Column("reporter", sa.String(256), nullable=True),
        sa.Column("sprint", sa.String(256), nullable=True),
        sa.Column("fix_version", sa.String(256), nullable=True),
        sa.Column("story_points", sa.Integer(), nullable=True),
        sa.Column("acceptance_criteria", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
    )
    op.drop_table("req_agent_tasks")
    op.drop_table("req_agent_input")
