# data_model/agent.py
"""
Data Model Agent
Reads source schema (from CSV or live database), designs target BigQuery
schema, produces a summary JSON, a Mermaid ER diagram, and a CSV mapping doc.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Ensure DEAH root is on sys.path so core.utilities is importable
_DEAH_ROOT = Path(__file__).resolve().parents[4]
if str(_DEAH_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEAH_ROOT))

from core.utilities.llm import create_llm_client

from core.utilities.db_tools.base_db import get_schema as get_schema_from_source
from .prompts import SYSTEM_PROMPT, schema_design_prompt


# ── Output schema ─────────────────────────────────────────────────────────────

@dataclass
class DataModelOutput:
    project_name: str
    source_tables: list[str]
    target_schema: list[dict]           # list of target table definitions
    relationships: list[dict]           # FK / join relationships
    er_diagram: str                     # Mermaid ER diagram string
    partitioning: dict                  # {table: partition_config}
    clustering: dict                    # {table: [cluster_columns]}
    cardinality: list[dict]             # [{from, to, type}]
    mapping: list[dict]                 # source→target column mapping rows
    summary: dict                       # full summary for downstream agents
    output_dir: Path

    def write(self, requirements):
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
        jira_id = requirements.get('ticket_id')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Summary JSON
        (self.output_dir / f"model_{jira_id}_{run_id}_summary.json").write_text(
            json.dumps(self.summary, indent=2), encoding="utf-8"
        )
        # ER diagram
        (self.output_dir / f"model_{jira_id}_{run_id}_er_diagram.mmd").write_text(
            self.er_diagram, encoding="utf-8"
        )
        # Mapping CSV
        mapping_path = self.output_dir / f"model_{jira_id}_{run_id}_mapping.csv"
        if self.mapping:
            with mapping_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "source_system", "source_table", "source_column", "source_data_type",
                    "target_table", "target_column", "target_data_type",
                    "transformation_logic", "is_partition_column", "is_cluster_column",
                    "notes"
                ])
                writer.writeheader()
                writer.writerows(self.mapping)


# ── Agent ─────────────────────────────────────────────────────────────────────

class DataModelAgent:
    """
    1. Load source schema from CSV or connect to source via registry.
    2. Call Claude to design target schema, ER diagram, and mapping.
    3. Write summary JSON, ER diagram, and mapping CSV to disk.
    """

    COLUMN_CEILING = 1000

    def __init__(self, config: dict):
        self.llm = create_llm_client("claude-code-sdk")
        self.output_root = Path(config.get("output_root", "output"))

    # ── public entry point ───────────────────────────────────────────────────

    def run(
        self,
        requirements: dict,
        schema_csv: Optional[str | Path] = None,
    ) -> DataModelOutput:
        """
        requirements: RequirementsOutput.to_dict()
        schema_csv:   optional path to a CSV containing source schema
        """
        source_connections = requirements.get("source_connections", [])
        source_tables = self._target_tables(source_connections)
        project_name = requirements.get("project_name", "").strip()

        if not project_name:
            raise ValueError("requirements.project_name is empty or missing.")

        # Step 1 — get source schema
        if schema_csv:
            source_schema = self._load_schema_csv(schema_csv, source_tables)
        else:
            source_schema = get_schema_from_source(source_connections, source_tables)

        self._validate_schema_size(source_schema)

        if not source_schema:
            raise ValueError(
                "Source schema is empty — no columns found for the specified "
                "source_tables. Check that table names match exactly and the "
                "database connection is scoped to the correct schema."
            )

        # Step 2 — design target schema via Claude
        data = self._design(requirements, source_schema)

        # Step 3 — build output
        output_dir = self.output_root

        summary = {
            "agent": "data_model",
            "project_name": project_name,
            "request_type": requirements.get("request_type"),
            "ticket_id": requirements.get("ticket_id"),
            "source_tables": source_tables,
            "source_connections": requirements.get("source_connections", []),
            "target_schema": data.get("target_schema", []),
            "relationships": data.get("relationships", []),
            "partitioning": data.get("partitioning", {}),
            "clustering": data.get("clustering", {}),
            "cardinality": data.get("cardinality", []),
        }

        output = DataModelOutput(
            project_name=project_name,
            source_tables=source_tables,
            target_schema=data.get("target_schema", []),
            relationships=data.get("relationships", []),
            er_diagram=data.get("er_diagram", ""),
            partitioning=data.get("partitioning", {}),
            clustering=data.get("clustering", {}),
            cardinality=data.get("cardinality", []),
            mapping=data.get("mapping", []),
            summary=summary,
            output_dir=output_dir,
        )
        output.write(requirements)
        return output

    # ── internal helpers ─────────────────────────────────────────────────────

    def _validate_schema_size(self, source_schema: list[dict]):
        count = len(source_schema)
        if count > self.COLUMN_CEILING:
            raise ValueError(
                f"Source schema contains {count} columns, exceeding the "
                f"{self.COLUMN_CEILING}-column ceiling. Reduce scope by listing "
                f"fewer tables in source_connections.source_tables."
            )

    def _design(self, requirements: dict, source_schema: list[dict]) -> dict:
        import re
        prompt = schema_design_prompt(requirements, source_schema)
        resp = self.llm.complete(prompt, system=SYSTEM_PROMPT, max_tokens=8096)
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", resp.content)
        clean = match.group(1).strip() if match else resp.content.strip()
        return json.loads(clean)

    def _load_schema_csv(
        self,
        path: str | Path,
        source_tables: list[str],
    ) -> list[dict]:
        """
        Load source schema from CSV. Expected columns:
        table_name, column_name, data_type, is_nullable, column_key, extra
        Filters to only the tables listed in source_connections.source_tables.
        """
        rows = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
            for row in reader:
                if not source_tables or row.get("table_name", "").lower() in [t.lower() for t in source_tables]:
                    data_type = (
                        row.get("column_type", "").strip()
                        or row.get("data_type", "").strip()
                    )
                    rows.append({
                        "table_name":  row.get("table_name", "").strip().lower(),
                        "column_name": row.get("column_name", "").strip(),
                        "data_type":   data_type,
                        "is_nullable": row.get("is_nullable", row.get("nullable", "")).strip(),
                        "column_key":  row.get("column_key", "").strip(),
                        "extra":       row.get("extra", "").strip(),
                    })
        return rows

    @staticmethod
    def _target_tables(source_connections: list[dict]) -> list[str]:
        tables = []
        for conn in source_connections:
            tables.extend(conn.get("source_tables", []))
        return list(dict.fromkeys(tables))  # deduplicate, preserve order

    @staticmethod
    def _slugify(name: str) -> str:
        return name.lower().replace(" ", "_").replace("/", "_")
