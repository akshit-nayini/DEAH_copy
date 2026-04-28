-- =============================================================================
-- Table: fct_daily_sales_summary
-- Description: Daily aggregated sales metrics by product and region
-- Layer: fct
-- Refresh Strategy: full_refresh
-- Source: derived_from_fct_orders
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.fct_daily_sales_summary`
(
  summary_date                   DATE NOT NULL,                   OPTIONS(description='Aggregation date')
  product_id                     INT64 NOT NULL,                  OPTIONS(description='FK to product dimension')
  region                         STRING NOT NULL,                 OPTIONS(description='Sales region')
  total_orders                   INT64 NOT NULL,                  OPTIONS(description='Count of orders')
  total_quantity                 INT64 NOT NULL,                  OPTIONS(description='Sum of units sold')
  gross_revenue                  FLOAT64 NOT NULL,                OPTIONS(description='Sum of total_amount before discounts')
  net_revenue                    FLOAT64 NOT NULL,                OPTIONS(description='Sum of total_amount after discounts')
  avg_order_value                FLOAT64 NOT NULL,                OPTIONS(description='Average order value for the day')
  _loaded_at                     TIMESTAMP NOT NULL               OPTIONS(description='ETL load timestamp')
)
PARTITION BY summary_date
CLUSTER BY product_id, region
OPTIONS(
  description='Daily aggregated sales metrics by product and region',
  labels=["layer=fct", "refresh=full_refresh"]
);
