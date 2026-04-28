import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _build_metadata_engine():
    """Build and return a SQLAlchemy engine for the metadata DB."""
    from core.utilities.db_tools.base_db import load_db_config, build_engine
    cfg = load_db_config("metadata_db")
    return build_engine(
        cfg.get("db_type") or os.environ.get("DB_TYPE", "mysql"),
        cfg.get("host")     or os.environ.get("DB_HOST", "34.70.79.163"),
        str(cfg.get("port") or os.environ.get("DB_PORT", "3306")),
        cfg.get("user")     or os.environ.get("DB_USER", "sa"),
        cfg.get("password") or os.environ.get("DB_PASSWORD", "sa"),
        (cfg.get("database") or os.environ.get("DB_NAME", "agentichub")).lower(),
    )


def log_agent_op(
    identifier: str,
    agent: str,
    artifact: str,
    request_type: str,
    filename: str,
    path: str,
) -> None:
    """
    Insert one row into AGENT_OUTPUT_METADATA after a successful agent run.
    Silently logs a warning and continues if the DB is unreachable.

    Connection details are read from db_config.yaml [metadata_db].
    Each key falls back to the corresponding environment variable if absent.

    Args:
        identifier:   Ticket ID or document stem  (e.g. "SCRUM-5")
        agent:        Agent name                  (e.g. "Requirements", "Architecture")
        artifact:     Output file destination      (e.g. "GITHUB")
        request_type: Detected request type       (e.g. "New Development", "Bug")
        filename:     Output filename             (e.g. "req_SCRUM-5_20260413_10.md")
        path:         Output directory path
    """
    try:
        from sqlalchemy import text
        engine = _build_metadata_engine()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_output_metadata (IDENTIFIER, AGENT, ARTIFACT, REQUEST_TYPE, FILENAME, FILE_TYPE, PATH) "
                    "VALUES (:identifier, :agent, :artifact, :request_type, :filename, :file_type, :path)"
                ),
                {
                    "identifier":   identifier[:50],
                    "agent":        agent[:50],
                    "artifact":     artifact[:20],
                    "request_type": (request_type or "")[:20].title(),
                    "filename":     filename[:50],
                    "file_type":    os.path.splitext(filename)[1][1:].upper(),
                    "path":         path[:100],
                },
            )
        return True
    except Exception as exc:
        print(f"\n⚠️  Could not write to metadata DB: {exc}")
        print(f"    Output file available at: {path}/{filename}")
        print(f"    Fix the DB connection and re-run to register it.")
        return False


def get_latest_output(ticket_id: str, agent: str, file_type: str, repo_root: Path) -> Path:
    """
    Query AGENT_OUTPUT_METADATA for the latest output file for a given ticket and agent.

    Args:
        ticket_id:  Jira ticket ID (e.g. "SCRUM-5")
        agent:      Agent name (e.g. "Requirements", "Architecture", "DataModel")
        file_type:  File extension without dot (e.g. "json", "md")
        repo_root:  Path to the DEAH repo root (REPO_ROOT in test scripts)

    Returns:
        Full absolute path to the latest matching output file.

    Raises:
        FileNotFoundError: If no matching record is found in the metadata table.
    """
    from sqlalchemy import text

    engine = _build_metadata_engine()

    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT PATH, FILENAME FROM agent_output_metadata
                WHERE IDENTIFIER = :ticket_id
                  AND AGENT      = :agent
                  AND FILE_TYPE  = :file_type
                ORDER BY CREATED_TS DESC
                LIMIT 1
            """),
            {"ticket_id": ticket_id, "agent": agent, "file_type": file_type.upper()},
        ).fetchone()

    if not row:
        raise FileNotFoundError(
            f"No {agent} {file_type.upper()} output found for ticket {ticket_id!r} in AGENT_OUTPUT_METADATA. "
            f"Run the {agent} agent for this ticket first."
        )

    return Path(repo_root).parent / row.PATH / row.FILENAME
