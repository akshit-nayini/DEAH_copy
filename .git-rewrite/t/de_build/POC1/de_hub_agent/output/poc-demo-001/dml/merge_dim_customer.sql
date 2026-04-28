-- =============================================================================
-- DML: dim_customer
-- Pattern: SCD Type-2 MERGE
-- Source: source_crm.customers
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

-- Step 1: Stage incoming records with hash for change detection
CREATE TEMP TABLE _scd2_staged AS
SELECT
    source.customer_id,
    source.first_name,
    source.last_name,
    source.email,
    source.phone,
    source.address_line1,
    source.city,
    source.state,
    source.country,
    source.customer_segment,
    source.created_date,
    FARM_FINGERPRINT(CONCAT(CAST(source.customer_id AS STRING))) AS _surrogate_key,
    SHA256(CONCAT(COALESCE(CAST(source.first_name AS STRING), ''), COALESCE(CAST(source.last_name AS STRING), ''), COALESCE(CAST(source.email AS STRING), ''), COALESCE(CAST(source.phone AS STRING), ''), COALESCE(CAST(source.address_line1 AS STRING), ''), COALESCE(CAST(source.city AS STRING), ''), COALESCE(CAST(source.state AS STRING), ''), COALESCE(CAST(source.country AS STRING), ''), COALESCE(CAST(source.customer_segment AS STRING), ''), COALESCE(CAST(source.created_date AS STRING), ''))) AS _row_hash
FROM `${PROJECT_ID}.${SOURCE_DATASET}.customers` AS source;

-- Step 2: Close existing records where business data has changed
MERGE INTO `${PROJECT_ID}.${DATASET}.dim_customer` AS target
USING _scd2_staged AS source
ON COALESCE(target.customer_id, 0) = COALESCE(source.customer_id, 0)
  AND target._is_current = TRUE

-- Close changed records
WHEN MATCHED AND target._row_hash != source._row_hash THEN
  UPDATE SET
    _effective_to = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY),
    _is_current = FALSE,
    _loaded_at = CURRENT_TIMESTAMP()

-- No action for unchanged records (implicit: WHEN MATCHED AND hashes equal → skip)
;

-- Step 3: Insert new versions for changed records + brand new records
INSERT INTO `${PROJECT_ID}.${DATASET}.dim_customer`
(
    
    customer_id,
    first_name,
    last_name,
    email,
    phone,
    address_line1,
    city,
    state,
    country,
    customer_segment,
    created_date,
    _surrogate_key,
    _effective_from,
    _effective_to,
    _is_current,
    _row_hash,
    _loaded_at
)
SELECT
    source.customer_id,
    source.first_name,
    source.last_name,
    source.email,
    source.phone,
    source.address_line1,
    source.city,
    source.state,
    source.country,
    source.customer_segment,
    source.created_date,
    source._surrogate_key,
    CURRENT_DATE() AS _effective_from,
    DATE '9999-12-31' AS _effective_to,
    TRUE AS _is_current,
    source._row_hash,
    CURRENT_TIMESTAMP() AS _loaded_at
FROM _scd2_staged AS source
LEFT JOIN `${PROJECT_ID}.${DATASET}.dim_customer` AS target
  ON COALESCE(target.customer_id, 0) = COALESCE(source.customer_id, 0)
  AND target._is_current = TRUE
WHERE target.customer_id IS NULL  -- new records
   OR target._row_hash != source._row_hash;  -- changed records

-- Step 4: Cleanup
DROP TABLE IF EXISTS _scd2_staged;
