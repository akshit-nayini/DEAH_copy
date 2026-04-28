-- =============================================================================
-- DML: dim_product
-- Pattern: SCD Type-1 MERGE (overwrite)
-- Source: source_catalog.products
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

MERGE INTO `${PROJECT_ID}.${DATASET}.dim_product` AS target
USING (
  SELECT
    
    product_id,
    product_name,
    category,
    subcategory,
    brand,
    unit_price,
    cost_price,
    is_active,
    created_date,
    updated_at,
    SHA256(CONCAT(COALESCE(CAST(source.product_name AS STRING), ''), COALESCE(CAST(source.category AS STRING), ''), COALESCE(CAST(source.subcategory AS STRING), ''), COALESCE(CAST(source.brand AS STRING), ''), COALESCE(CAST(source.unit_price AS STRING), ''), COALESCE(CAST(source.cost_price AS STRING), ''), COALESCE(CAST(source.is_active AS STRING), ''), COALESCE(CAST(source.created_date AS STRING), ''), COALESCE(CAST(source.updated_at AS STRING), ''))) AS _row_hash
  FROM `${PROJECT_ID}.${SOURCE_DATASET}.products` AS raw
) AS source
ON target.product_id = source.product_id

-- Update changed records (SCD-1: overwrite in place)
WHEN MATCHED AND SHA256(CONCAT(COALESCE(CAST(target.product_name AS STRING), ''), COALESCE(CAST(target.category AS STRING), ''), COALESCE(CAST(target.subcategory AS STRING), ''), COALESCE(CAST(target.brand AS STRING), ''), COALESCE(CAST(target.unit_price AS STRING), ''), COALESCE(CAST(target.cost_price AS STRING), ''), COALESCE(CAST(target.is_active AS STRING), ''), COALESCE(CAST(target.created_date AS STRING), ''), COALESCE(CAST(target.updated_at AS STRING), ''))) != source._row_hash THEN
  UPDATE SET
    target.product_name = source.product_name,
    target.category = source.category,
    target.subcategory = source.subcategory,
    target.brand = source.brand,
    target.unit_price = source.unit_price,
    target.cost_price = source.cost_price,
    target.is_active = source.is_active,
    target.created_date = source.created_date,
    target.updated_at = source.updated_at,
    _loaded_at = CURRENT_TIMESTAMP()

-- Insert new records
WHEN NOT MATCHED BY TARGET THEN
  INSERT (product_id, product_name, category, subcategory, brand, unit_price, cost_price, is_active, created_date, updated_at, _loaded_at)
  VALUES (source.product_id, source.product_name, source.category, source.subcategory, source.brand, source.unit_price, source.cost_price, source.is_active, source.created_date, source.updated_at, CURRENT_TIMESTAMP());
