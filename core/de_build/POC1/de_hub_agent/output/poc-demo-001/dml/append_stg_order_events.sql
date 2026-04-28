-- =============================================================================
-- DML: stg_order_events
-- Pattern: Incremental Append (high-water-mark)
-- Source: source_events.order_status_changes
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

-- Step 1: Identify new records using high-water-mark pattern
-- Watermark column: event_timestamp
INSERT INTO `${PROJECT_ID}.${DATASET}.stg_order_events`
(
    
    event_id,
    order_id,
    event_type,
    event_timestamp,
    event_payload,
    loaded_at,
    _loaded_at
)
WITH incremental_batch AS (
  SELECT
    
    event_id,
    order_id,
    event_type,
    event_timestamp,
    event_payload,
    loaded_at,
    ROW_NUMBER() OVER (
      PARTITION BY event_id
      ORDER BY event_timestamp DESC
    ) AS _dedup_rank
  FROM `${PROJECT_ID}.${SOURCE_DATASET}.order_status_changes`
  WHERE event_timestamp > COALESCE(
    (SELECT MAX(event_timestamp) FROM `${PROJECT_ID}.${DATASET}.stg_order_events`),
    TIMESTAMP '1970-01-01 00:00:00 UTC'
  )
)
SELECT
    
    event_id,
    order_id,
    event_type,
    event_timestamp,
    event_payload,
    loaded_at,
    CURRENT_TIMESTAMP() AS _loaded_at
FROM incremental_batch
WHERE _dedup_rank = 1;  -- Keep only latest version per primary key within batch
