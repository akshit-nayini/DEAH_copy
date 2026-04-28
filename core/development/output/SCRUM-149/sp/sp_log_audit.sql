-- ============================================================
-- File    : sp_log_audit.sql
-- Purpose : Stored procedure — write one audit record to
--           verizon_data_dea.pipeline_audit_log on every
--           DAG run regardless of outcome (trigger_rule=ALL_DONE)
-- Project : 5gcore | Sprint:
-- Ticket  : SCRUM-149
-- ============================================================
-- Version History:
--   v1.0  2026-04-21  SCRUM-149  Initial creation
-- ============================================================
-- ASSUMPTION: pipeline_audit_log is NOT partitioned (or partition
--   filter is not required) because audit inserts always target
--   the current timestamp and forcing a partition hint here would
--   add no pruning benefit on a write path. VERIFY before deploy
--   if require_partition_filter = true is enabled on this table.
-- ============================================================
-- NOTE: Parameters p_process_name, p_source_table, p_target_table,
--   p_insert_count, p_upsert_count, and p_runtime_seconds are
--   accepted but not yet stored — the approved audit_table schema
--   (run_id, dag_id, execution_timestamp, status, rows_extracted,
--   rows_loaded, error_message) contains no corresponding columns.
--   These parameters are retained in the signature so callers do
--   not need to change if columns are added later.
--   ASSUMPTION: This is intentional. VERIFY before deploy.
-- ============================================================
CREATE OR REPLACE PROCEDURE `verizon-data`.`verizon_data_dea`.`sp_log_audit`(
    IN p_dag_name            STRING
  , IN p_process_name        STRING
  , IN p_source_table        STRING
  , IN p_target_table        STRING
  , IN p_source_count        INT64
  , IN p_target_count        INT64
  , IN p_insert_count        INT64
  , IN p_upsert_count        INT64
  , IN p_runtime_seconds     FLOAT64
  , IN p_status              STRING
  , IN p_error_message       STRING
)
BEGIN

    INSERT INTO `verizon-data`.`verizon_data_dea`.`pipeline_audit_log` (
        run_id
      , dag_id
      , execution_timestamp
      , status
      , rows_extracted
      , rows_loaded
      , error_message
    )
    VALUES (
        GENERATE_UUID()
      , p_dag_name
      , CURRENT_TIMESTAMP()
      , p_status
      , p_source_count
      , p_target_count
      , p_error_message
    );

END;