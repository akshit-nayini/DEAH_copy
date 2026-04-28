-- =============================================================================
-- DML: fct_orders
-- Pattern: Incremental Append (high-water-mark)
-- Source: source_orders.order_lines
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

-- Step 1: Identify new records using high-water-mark pattern
-- Watermark column: loaded_at
INSERT INTO `${PROJECT_ID}.${DATASET}.fct_orders`
(
    
    order_id,
    order_line_id,
    customer_id,
    product_id,
    order_date,
    quantity,
    unit_price,
    discount_amount,
    total_amount,
    order_status,
    shipping_date,
    loaded_at,
    _loaded_at
)
WITH incremental_batch AS (
  SELECT
    
    order_id,
    order_line_id,
    customer_id,
    product_id,
    order_date,
    quantity,
    unit_price,
    discount_amount,
    total_amount,
    order_status,
    shipping_date,
    loaded_at,
    ROW_NUMBER() OVER (
      PARTITION BY order_id, order_line_id
      ORDER BY loaded_at DESC
    ) AS _dedup_rank
  FROM `${PROJECT_ID}.${SOURCE_DATASET}.order_lines`
  WHERE loaded_at > COALESCE(
    (SELECT MAX(loaded_at) FROM `${PROJECT_ID}.${DATASET}.fct_orders`),
    TIMESTAMP '1970-01-01 00:00:00 UTC'
  )
)
SELECT
    
    order_id,
    order_line_id,
    customer_id,
    product_id,
    order_date,
    quantity,
    unit_price,
    discount_amount,
    total_amount,
    order_status,
    shipping_date,
    loaded_at,
    CURRENT_TIMESTAMP() AS _loaded_at
FROM incremental_batch
WHERE _dedup_rank = 1;  -- Keep only latest version per primary key within batch
