-- =============================================================================
-- Table: stg_order_events
-- Description: Staging table for raw order status change events from event stream
-- Layer: stg
-- Refresh Strategy: incremental_append
-- Source: source_events.order_status_changes
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.stg_order_events`
(
  event_id                       STRING NOT NULL,                 OPTIONS(description='Unique event identifier (UUID)')
  order_id                       INT64 NOT NULL,                  OPTIONS(description='Associated order ID')
  event_type                     STRING NOT NULL,                 OPTIONS(description='Event type: created, updated, shipped, delivered, cancelled')
  event_timestamp                TIMESTAMP NOT NULL,              OPTIONS(description='When the event occurred')
  event_payload                  JSON,                            OPTIONS(description='Raw JSON payload from event stream')
  loaded_at                      TIMESTAMP NOT NULL,              OPTIONS(description='ETL ingestion timestamp')
  _loaded_at                     TIMESTAMP NOT NULL               OPTIONS(description='ETL load timestamp')
)
PARTITION BY TIMESTAMP_TRUNC(event_timestamp, DAY)
CLUSTER BY order_id, event_type
OPTIONS(
  description='Staging table for raw order status change events from event stream',
  labels=["layer=stg", "refresh=incremental_append"]
);
