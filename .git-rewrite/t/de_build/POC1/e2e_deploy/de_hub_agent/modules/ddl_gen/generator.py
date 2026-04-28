"""
DDL Generator Module
Generates BigQuery-native CREATE TABLE / CREATE VIEW statements
from parsed TableSpec objects.
"""
import logging
from datetime import datetime, timezone
from core.models import (
    GenerateRequest, TableSpec, ColumnSpec, DDLOutput,
    DDLGenerationResult, PartitionType, LayerType,
)
from modules.input_parser.parser import InputParser

logger = logging.getLogger(__name__)

BIGQUERY_TYPE_MAP = {
    "STRING": "STRING",
    "INT64": "INT64",
    "INTEGER": "INT64",
    "FLOAT64": "FLOAT64",
    "FLOAT": "FLOAT64",
    "NUMERIC": "NUMERIC",
    "BIGNUMERIC": "BIGNUMERIC",
    "BOOL": "BOOL",
    "BOOLEAN": "BOOL",
    "DATE": "DATE",
    "DATETIME": "DATETIME",
    "TIMESTAMP": "TIMESTAMP",
    "TIME": "TIME",
    "BYTES": "BYTES",
    "JSON": "JSON",
    "GEOGRAPHY": "GEOGRAPHY",
    "STRUCT": "STRUCT",
    "ARRAY": "ARRAY",
}


class DDLGenerator:
    """Generates BigQuery DDL from TableSpec objects."""

    def __init__(self, parser: InputParser):
        self.parser = parser
        self.generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def generate(self, request: GenerateRequest) -> DDLGenerationResult:
        ddl_files = []
        grant_statements = []
        warnings = []

        for table in request.data_model.tables:
            try:
                ddl_output = self._generate_table_ddl(table)
                ddl_files.append(ddl_output)

                pii_cols = self.parser.get_pii_columns(table)
                if pii_cols:
                    grants = self._generate_grant_statements(table, pii_cols)
                    grant_statements.extend(grants)

            except Exception as e:
                warnings.append(f"Failed to generate DDL for {table.name}: {str(e)}")
                logger.error("DDL generation failed for %s: %s", table.name, e)

        logger.info("DDL generation complete: %d tables, %d grants, %d warnings",
                     len(ddl_files), len(grant_statements), len(warnings))

        return DDLGenerationResult(
            ddl_files=ddl_files,
            grant_statements=grant_statements,
            warnings=warnings,
        )

    def _generate_table_ddl(self, table: TableSpec) -> DDLOutput:
        qualified_name = self.parser.get_qualified_name(table)
        file_name = f"{qualified_name}.sql"
        pii_columns = self.parser.get_pii_columns(table)

        lines = []

        # File header
        lines.append(f"-- =============================================================================")
        lines.append(f"-- Table: {qualified_name}")
        lines.append(f"-- Description: {table.description}")
        lines.append(f"-- Layer: {table.layer.value}")
        lines.append(f"-- Refresh Strategy: {table.refresh_strategy.value}")
        lines.append(f"-- Source: {table.source_table or 'N/A'}")
        lines.append(f"-- Generated: {self.generated_at}")
        lines.append(f"-- Generator: DE_CodeGen_Optimizer_Agent v1.0")
        lines.append(f"-- =============================================================================")
        lines.append("")

        # CREATE TABLE
        lines.append(f"CREATE TABLE IF NOT EXISTS `${{PROJECT_ID}}.${{DATASET}}.{qualified_name}`")
        lines.append("(")

        # SCD-2 tracking columns (prepend if scd2)
        scd2_cols = []
        if table.refresh_strategy.value == "scd_type_2":
            scd2_cols = [
                ("_surrogate_key", "INT64", False, "Surrogate key generated via FARM_FINGERPRINT", False),
                ("_effective_from", "DATE", False, "SCD-2: record effective start date", False),
                ("_effective_to", "DATE", False, "SCD-2: record effective end date (9999-12-31 for current)", False),
                ("_is_current", "BOOL", False, "SCD-2: true if this is the current active record", False),
                ("_row_hash", "BYTES", False, "SHA256 hash of business columns for change detection", False),
            ]

        all_columns = []

        # Business columns first
        for col in table.columns:
            bq_type = BIGQUERY_TYPE_MAP.get(col.data_type.upper(), col.data_type)
            all_columns.append((col.name, bq_type, col.nullable, col.description, col.is_pii))

        # SCD-2 columns at the end
        for name, dtype, nullable, desc, is_pii in scd2_cols:
            all_columns.append((name, dtype, nullable, desc, is_pii))

        # Audit column
        all_columns.append(("_loaded_at", "TIMESTAMP", False, "ETL load timestamp", False))

        for i, (name, dtype, nullable, desc, is_pii) in enumerate(all_columns):
            null_str = "" if nullable else " NOT NULL"
            desc_escaped = desc.replace("'", "\\'")
            pii_comment = "  -- PII: requires policy tag" if is_pii else ""
            comma = "," if i < len(all_columns) - 1 else ""
            col_def = f"  {name:<30} {dtype}{null_str}"
            options = f"OPTIONS(description='{desc_escaped}')"
            line = f"{col_def:<55} {options}{comma}{pii_comment}"
            lines.append(line)

        lines.append(")")

        # Partition
        partition_type = "NONE"
        if table.partition_config:
            pc = table.partition_config
            if pc.type == PartitionType.RANGE:
                lines.append(f"PARTITION BY RANGE_BUCKET({pc.column}, GENERATE_ARRAY(0, 1000000, 1000))")
            else:
                partition_fn = self._get_partition_function(pc.type)
                # Check if column type needs TIMESTAMP_TRUNC vs DATE_TRUNC
                col_type = next((c.data_type for c in table.columns if c.name == pc.column), "DATE")
                if col_type.upper() in ("TIMESTAMP", "DATETIME"):
                    lines.append(f"PARTITION BY {partition_fn}({pc.column}, {pc.type.value})")
                else:
                    if pc.type == PartitionType.DAY:
                        lines.append(f"PARTITION BY {pc.column}")
                    else:
                        lines.append(f"PARTITION BY DATE_TRUNC({pc.column}, {pc.type.value})")
            partition_type = pc.type.value

        # Clustering
        if table.cluster_columns:
            cols_str = ", ".join(table.cluster_columns[:4])
            lines.append(f"CLUSTER BY {cols_str}")

        # OPTIONS
        desc_escaped = table.description.replace("'", "\\'")
        lines.append("OPTIONS(")
        lines.append(f"  description='{desc_escaped}',")
        labels = [f"layer={table.layer.value}", f"refresh={table.refresh_strategy.value}"]
        if pii_columns:
            labels.append("contains_pii=true")
        labels_str = ", ".join(f'"{l}"' for l in labels)
        lines.append(f"  labels=[{labels_str}]")
        lines.append(");")
        lines.append("")

        sql = "\n".join(lines)

        return DDLOutput(
            table_name=f"${{DATASET}}.{qualified_name}",
            file_name=file_name,
            sql=sql,
            partition_type=partition_type,
            cluster_columns=table.cluster_columns[:4],
            pii_columns=pii_columns,
        )

    def _get_partition_function(self, ptype: PartitionType) -> str:
        if ptype in (PartitionType.DAY, PartitionType.MONTH, PartitionType.YEAR):
            return "TIMESTAMP_TRUNC"
        return "TIMESTAMP_TRUNC"

    def _generate_grant_statements(self, table: TableSpec, pii_columns: list[str]) -> list[str]:
        qualified_name = self.parser.get_qualified_name(table)
        grants = []
        grants.append(
            f"-- Grant restricted access for PII table: {qualified_name}\n"
            f"GRANT SELECT ON TABLE `${{PROJECT_ID}}.${{DATASET}}.{qualified_name}`\n"
            f"TO 'group:data-analysts@${{ORG_DOMAIN}}';\n"
        )
        grants.append(
            f"-- Revoke access to PII columns for general analysts\n"
            f"-- Note: Implement column-level security via BigQuery policy tags\n"
            f"-- PII columns requiring policy tags: {', '.join(pii_columns)}\n"
        )
        return grants
