-- =============================================================================
-- Table: dim_product
-- Description: Product dimension table with category hierarchy
-- Layer: dim
-- Refresh Strategy: scd_type_1
-- Source: source_catalog.products
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.dim_product`
(
  product_id                     INT64 NOT NULL,                  OPTIONS(description='Unique product identifier')
  product_name                   STRING NOT NULL,                 OPTIONS(description='Product display name')
  category                       STRING NOT NULL,                 OPTIONS(description='Top-level product category')
  subcategory                    STRING,                          OPTIONS(description='Product subcategory')
  brand                          STRING,                          OPTIONS(description='Product brand name')
  unit_price                     FLOAT64 NOT NULL,                OPTIONS(description='Current unit price in USD')
  cost_price                     FLOAT64,                         OPTIONS(description='Unit cost price in USD')
  is_active                      BOOL NOT NULL,                   OPTIONS(description='Whether product is currently active for sale')
  created_date                   DATE NOT NULL,                   OPTIONS(description='Product catalog entry date')
  updated_at                     TIMESTAMP NOT NULL,              OPTIONS(description='Last modification timestamp')
  _loaded_at                     TIMESTAMP NOT NULL               OPTIONS(description='ETL load timestamp')
)
CLUSTER BY category, brand
OPTIONS(
  description='Product dimension table with category hierarchy',
  labels=["layer=dim", "refresh=scd_type_1"]
);
