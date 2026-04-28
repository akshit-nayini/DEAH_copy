-- =============================================================================
-- Table: fct_orders
-- Description: Fact table for customer orders with line-item granularity
-- Layer: fct
-- Refresh Strategy: incremental_append
-- Source: source_orders.order_lines
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.fct_orders`
(
  order_id                       INT64 NOT NULL,                  OPTIONS(description='Unique order identifier')
  order_line_id                  INT64 NOT NULL,                  OPTIONS(description='Line item sequence within order')
  customer_id                    INT64 NOT NULL,                  OPTIONS(description='FK to customer dimension')
  product_id                     INT64 NOT NULL,                  OPTIONS(description='FK to product dimension')
  order_date                     DATE NOT NULL,                   OPTIONS(description='Date the order was placed')
  quantity                       INT64 NOT NULL,                  OPTIONS(description='Number of units ordered')
  unit_price                     FLOAT64 NOT NULL,                OPTIONS(description='Price per unit at time of order')
  discount_amount                FLOAT64,                         OPTIONS(description='Discount applied to line item')
  total_amount                   FLOAT64 NOT NULL,                OPTIONS(description='Line total: quantity * unit_price - discount')
  order_status                   STRING NOT NULL,                 OPTIONS(description='Order status: pending, confirmed, shipped, delivered, cancelled')
  shipping_date                  DATE,                            OPTIONS(description='Date the order was shipped')
  loaded_at                      TIMESTAMP NOT NULL,              OPTIONS(description='ETL load timestamp')
  _loaded_at                     TIMESTAMP NOT NULL               OPTIONS(description='ETL load timestamp')
)
PARTITION BY order_date
CLUSTER BY customer_id, product_id, order_status
OPTIONS(
  description='Fact table for customer orders with line-item granularity',
  labels=["layer=fct", "refresh=incremental_append"]
);
