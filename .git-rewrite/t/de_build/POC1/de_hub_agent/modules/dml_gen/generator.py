"""
DML Generator Module
Generates BigQuery transformation SQL (MERGE, INSERT, CREATE OR REPLACE)
based on the refresh strategy of each table.
"""
import logging
from datetime import datetime, timezone
from core.models import (
    GenerateRequest, TableSpec, RefreshStrategy,
    DMLOutput, DMLGenerationResult, ColumnMapping,
)
from modules.input_parser.parser import InputParser

logger = logging.getLogger(__name__)


class DMLGenerator:
    """Generates BigQuery DML from TableSpec and transformation rules."""

    def __init__(self, parser: InputParser):
        self.parser = parser
        self.generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def generate(self, request: GenerateRequest) -> DMLGenerationResult:
        dml_files = []
        warnings = []

        for table in request.data_model.tables:
            try:
                dml = self._route_to_pattern(table, request)
                if dml:
                    dml_files.append(dml)
            except Exception as e:
                warnings.append(f"DML generation failed for {table.name}: {str(e)}")
                logger.error("DML gen failed for %s: %s", table.name, e)

        logger.info("DML generation complete: %d files, %d warnings", len(dml_files), len(warnings))
        return DMLGenerationResult(dml_files=dml_files, warnings=warnings)

    def _route_to_pattern(self, table: TableSpec, request: GenerateRequest) -> DMLOutput | None:
        qname = self.parser.get_qualified_name(table)
        strategy = table.refresh_strategy
        mappings = [m for m in request.column_mappings if m.source_table == table.source_table]

        if strategy == RefreshStrategy.SCD2:
            return self._gen_scd2_merge(table, qname, mappings)
        elif strategy == RefreshStrategy.SCD1:
            return self._gen_scd1_merge(table, qname, mappings)
        elif strategy == RefreshStrategy.INCREMENTAL:
            return self._gen_incremental_append(table, qname, request)
        elif strategy == RefreshStrategy.FULL:
            return self._gen_full_refresh(table, qname, request)
        else:
            logger.warning("Unknown refresh strategy for %s: %s", table.name, strategy)
            return None

    def _header(self, qname: str, pattern: str, source: str) -> str:
        return (
            f"-- =============================================================================\n"
            f"-- DML: {qname}\n"
            f"-- Pattern: {pattern}\n"
            f"-- Source: {source}\n"
            f"-- Generated: {self.generated_at}\n"
            f"-- Generator: DE_CodeGen_Optimizer_Agent v1.0\n"
            f"-- =============================================================================\n\n"
        )

    def _gen_scd2_merge(self, table: TableSpec, qname: str, mappings: list[ColumnMapping]) -> DMLOutput:
        biz_cols = [c.name for c in table.columns if c.name not in ('updated_at',)]
        biz_keys = table.primary_key
        non_key_cols = [c for c in biz_cols if c not in biz_keys]
        pii_cols = self.parser.get_pii_columns(table)

        hash_cols = ", ".join(f"COALESCE(CAST(source.{c} AS STRING), '')" for c in non_key_cols)
        key_join_parts = []
        for k in biz_keys:
            is_numeric = any(c.data_type in ('INT64', 'FLOAT64') for c in table.columns if c.name == k)
            default_val = "0" if is_numeric else "''"
            key_join_parts.append(
                f"COALESCE(target.{k}, {default_val}) = COALESCE(source.{k}, {default_val})"
            )
        key_join = " AND ".join(key_join_parts)
        surrogate_expr = "FARM_FINGERPRINT(CONCAT(" + ", ".join(f"CAST(source.{k} AS STRING)" for k in biz_keys) + "))"

        select_cols = ",\n    ".join(f"source.{c}" for c in biz_cols)

        sql = self._header(qname, "SCD Type-2 MERGE", table.source_table or "N/A")

        sql += f"""-- Step 1: Stage incoming records with hash for change detection
CREATE TEMP TABLE _scd2_staged AS
SELECT
    {select_cols},
    {surrogate_expr} AS _surrogate_key,
    SHA256(CONCAT({hash_cols})) AS _row_hash
FROM `${{PROJECT_ID}}.${{SOURCE_DATASET}}.{table.source_table.split('.')[-1] if table.source_table else table.name}` AS source;

-- Step 2: Close existing records where business data has changed
MERGE INTO `${{PROJECT_ID}}.${{DATASET}}.{qname}` AS target
USING _scd2_staged AS source
ON {key_join}
  AND target._is_current = TRUE

-- Close changed records
WHEN MATCHED AND target._row_hash != source._row_hash THEN
  UPDATE SET
    _effective_to = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY),
    _is_current = FALSE,
    _loaded_at = CURRENT_TIMESTAMP()

-- No action for unchanged records (implicit: WHEN MATCHED AND hashes equal → skip)
;

-- Step 3: Insert new versions for changed records + brand new records
INSERT INTO `${{PROJECT_ID}}.${{DATASET}}.{qname}`
(
    {",".join(f"{chr(10)}    {c}" for c in biz_cols)},
    _surrogate_key,
    _effective_from,
    _effective_to,
    _is_current,
    _row_hash,
    _loaded_at
)
SELECT
    {select_cols},
    source._surrogate_key,
    CURRENT_DATE() AS _effective_from,
    DATE '9999-12-31' AS _effective_to,
    TRUE AS _is_current,
    source._row_hash,
    CURRENT_TIMESTAMP() AS _loaded_at
FROM _scd2_staged AS source
LEFT JOIN `${{PROJECT_ID}}.${{DATASET}}.{qname}` AS target
  ON {key_join}
  AND target._is_current = TRUE
WHERE target.{biz_keys[0]} IS NULL  -- new records
   OR target._row_hash != source._row_hash;  -- changed records

-- Step 4: Cleanup
DROP TABLE IF EXISTS _scd2_staged;
"""
        return DMLOutput(
            target_table=qname,
            file_name=f"merge_{qname}.sql",
            sql=sql,
            pattern=RefreshStrategy.SCD2,
            source_tables=[table.source_table] if table.source_table else [],
        )

    def _gen_scd1_merge(self, table: TableSpec, qname: str, mappings: list[ColumnMapping]) -> DMLOutput:
        biz_keys = table.primary_key
        all_cols = [c.name for c in table.columns]
        non_key_cols = [c for c in all_cols if c not in biz_keys]
        hash_cols = ", ".join(f"COALESCE(CAST(source.{c} AS STRING), '')" for c in non_key_cols)
        key_join = " AND ".join(f"target.{k} = source.{k}" for k in biz_keys)
        update_sets = ",\n    ".join(f"target.{c} = source.{c}" for c in non_key_cols)
        insert_cols = ", ".join(all_cols + ["_loaded_at"])
        insert_vals = ", ".join([f"source.{c}" for c in all_cols] + ["CURRENT_TIMESTAMP()"])

        sql = self._header(qname, "SCD Type-1 MERGE (overwrite)", table.source_table or "N/A")
        sql += f"""MERGE INTO `${{PROJECT_ID}}.${{DATASET}}.{qname}` AS target
USING (
  SELECT
    {",".join(f"{chr(10)}    {c}" for c in all_cols)},
    SHA256(CONCAT({hash_cols})) AS _row_hash
  FROM `${{PROJECT_ID}}.${{SOURCE_DATASET}}.{table.source_table.split('.')[-1] if table.source_table else table.name}` AS raw
) AS source
ON {key_join}

-- Update changed records (SCD-1: overwrite in place)
WHEN MATCHED AND SHA256(CONCAT({", ".join(f"COALESCE(CAST(target.{c} AS STRING), '')" for c in non_key_cols)})) != source._row_hash THEN
  UPDATE SET
    {update_sets},
    _loaded_at = CURRENT_TIMESTAMP()

-- Insert new records
WHEN NOT MATCHED BY TARGET THEN
  INSERT ({insert_cols})
  VALUES ({insert_vals});
"""
        return DMLOutput(
            target_table=qname, file_name=f"merge_{qname}.sql", sql=sql,
            pattern=RefreshStrategy.SCD1,
            source_tables=[table.source_table] if table.source_table else [],
        )

    def _gen_incremental_append(self, table: TableSpec, qname: str, request: GenerateRequest) -> DMLOutput:
        all_cols = [c.name for c in table.columns]
        watermark_col = next((c.name for c in table.columns if c.name in ('loaded_at', 'updated_at', 'event_timestamp')), None)
        if not watermark_col:
            watermark_col = all_cols[-1]

        pk_cols = table.primary_key
        dedup_order = watermark_col

        sql = self._header(qname, "Incremental Append (high-water-mark)", table.source_table or "N/A")
        sql += f"""-- Step 1: Identify new records using high-water-mark pattern
-- Watermark column: {watermark_col}
INSERT INTO `${{PROJECT_ID}}.${{DATASET}}.{qname}`
(
    {",".join(f"{chr(10)}    {c}" for c in all_cols)},
    _loaded_at
)
WITH incremental_batch AS (
  SELECT
    {",".join(f"{chr(10)}    {c}" for c in all_cols)},
    ROW_NUMBER() OVER (
      PARTITION BY {", ".join(pk_cols)}
      ORDER BY {dedup_order} DESC
    ) AS _dedup_rank
  FROM `${{PROJECT_ID}}.${{SOURCE_DATASET}}.{table.source_table.split('.')[-1] if table.source_table else table.name}`
  WHERE {watermark_col} > COALESCE(
    (SELECT MAX({watermark_col}) FROM `${{PROJECT_ID}}.${{DATASET}}.{qname}`),
    TIMESTAMP '1970-01-01 00:00:00 UTC'
  )
)
SELECT
    {",".join(f"{chr(10)}    {c}" for c in all_cols)},
    CURRENT_TIMESTAMP() AS _loaded_at
FROM incremental_batch
WHERE _dedup_rank = 1;  -- Keep only latest version per primary key within batch
"""
        return DMLOutput(
            target_table=qname, file_name=f"append_{qname}.sql", sql=sql,
            pattern=RefreshStrategy.INCREMENTAL,
            source_tables=[table.source_table] if table.source_table else [],
        )

    def _gen_full_refresh(self, table: TableSpec, qname: str, request: GenerateRequest) -> DMLOutput:
        all_cols = [c.name for c in table.columns]
        is_derived = table.source_table and table.source_table.startswith("derived_from_")

        sql = self._header(qname, "Full Refresh (replace)", table.source_table or "N/A")

        if is_derived:
            source_ref = table.source_table.replace("derived_from_", "")
            rules = [r for r in request.transformation_rules if r.target_column in [c.name for c in table.columns]]
            sql += f"""-- Full refresh: rebuild from upstream fact table
CREATE OR REPLACE TABLE `${{PROJECT_ID}}.${{DATASET}}.{qname}`
PARTITION BY {table.partition_config.column if table.partition_config else "/* no partition */"}
{f"CLUSTER BY {', '.join(table.cluster_columns[:4])}" if table.cluster_columns else ""}
AS
SELECT
    {table.partition_config.column if table.partition_config else "NULL"} AS {table.partition_config.column if table.partition_config else "summary_date"},
    {",".join(f"{chr(10)}    {c}" for c in all_cols if c != (table.partition_config.column if table.partition_config else ""))},
    CURRENT_TIMESTAMP() AS _loaded_at
FROM `${{PROJECT_ID}}.${{DATASET}}.{source_ref}` AS src
GROUP BY {", ".join(c for c in all_cols if "total" not in c and "avg" not in c and "gross" not in c and "net" not in c)};
"""
        else:
            sql += f"""-- Full refresh: truncate and reload from source
CREATE OR REPLACE TABLE `${{PROJECT_ID}}.${{DATASET}}.{qname}`
{f"CLUSTER BY {', '.join(table.cluster_columns[:4])}" if table.cluster_columns else ""}
AS
SELECT
    {",".join(f"{chr(10)}    {c}" for c in all_cols)},
    CURRENT_TIMESTAMP() AS _loaded_at
FROM `${{PROJECT_ID}}.${{SOURCE_DATASET}}.{table.source_table.split('.')[-1] if table.source_table else table.name}`;
"""
        return DMLOutput(
            target_table=qname, file_name=f"refresh_{qname}.sql", sql=sql,
            pattern=RefreshStrategy.FULL,
            source_tables=[table.source_table] if table.source_table else [],
        )
