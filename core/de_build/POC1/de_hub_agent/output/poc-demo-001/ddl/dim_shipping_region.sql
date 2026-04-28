-- =============================================================================
-- Table: dim_shipping_region
-- Description: Reference dimension for shipping regions and zones
-- Layer: dim
-- Refresh Strategy: full_refresh
-- Source: source_reference.shipping_regions
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.dim_shipping_region`
(
  region_code                    STRING NOT NULL,                 OPTIONS(description='Unique region code')
  region_name                    STRING NOT NULL,                 OPTIONS(description='Human-readable region name')
  country                        STRING NOT NULL,                 OPTIONS(description='ISO country code')
  shipping_zone                  STRING NOT NULL,                 OPTIONS(description='Shipping zone for cost calculation')
  avg_delivery_days              INT64,                           OPTIONS(description='Average delivery days for the zone')
  _loaded_at                     TIMESTAMP NOT NULL               OPTIONS(description='ETL load timestamp')
)
OPTIONS(
  description='Reference dimension for shipping regions and zones',
  labels=["layer=dim", "refresh=full_refresh"]
);
