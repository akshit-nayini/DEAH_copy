-- =============================================================================
-- DML: dim_shipping_region
-- Pattern: Full Refresh (replace)
-- Source: source_reference.shipping_regions
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

-- Full refresh: truncate and reload from source
CREATE OR REPLACE TABLE `${PROJECT_ID}.${DATASET}.dim_shipping_region`

AS
SELECT
    
    region_code,
    region_name,
    country,
    shipping_zone,
    avg_delivery_days,
    CURRENT_TIMESTAMP() AS _loaded_at
FROM `${PROJECT_ID}.${SOURCE_DATASET}.shipping_regions`;
