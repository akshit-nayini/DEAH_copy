-- =============================================================================
-- DML: fct_daily_sales_summary
-- Pattern: Full Refresh (replace)
-- Source: derived_from_fct_orders
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

-- Full refresh: rebuild from upstream fact table
CREATE OR REPLACE TABLE `${PROJECT_ID}.${DATASET}.fct_daily_sales_summary`
PARTITION BY summary_date
CLUSTER BY product_id, region
AS
SELECT
    summary_date AS summary_date,
    
    product_id,
    region,
    total_orders,
    total_quantity,
    gross_revenue,
    net_revenue,
    avg_order_value,
    CURRENT_TIMESTAMP() AS _loaded_at
FROM `${PROJECT_ID}.${DATASET}.fct_orders` AS src
GROUP BY summary_date, product_id, region;
