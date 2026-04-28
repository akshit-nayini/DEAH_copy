#!/bin/bash
# =============================================================================
# DE Hub Agent — Source Data Setup Script
# Creates source datasets and loads synthetic sample data into BigQuery
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - BigQuery API enabled on the project
#
# Usage:
#   chmod +x setup_source_data.sh
#   ./setup_source_data.sh <PROJECT_ID> <REGION>
#
# Example:
#   ./setup_source_data.sh my-gcp-project us-central1
# =============================================================================

set -euo pipefail

PROJECT_ID="${1:?Usage: ./setup_source_data.sh <PROJECT_ID> <REGION>}"
REGION="${2:-us-central1}"

echo "============================================================"
echo "DE Hub Agent — Source Data Setup"
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo "============================================================"
echo ""

# ─── Step 1: Create datasets ─────────────────────────────────────
echo "[1/5] Creating datasets..."

# Source datasets (simulating upstream source systems)
for DS in source_crm source_catalog source_orders source_events source_reference; do
  bq --project_id="${PROJECT_ID}" mk --dataset \
    --location="${REGION}" \
    --description="Source system dataset: ${DS}" \
    "${PROJECT_ID}:${DS}" 2>/dev/null || echo "  Dataset ${DS} already exists"
done

# Target datasets (where our agent's generated code writes to)
for DS in de_hub_staging de_hub_analytics; do
  bq --project_id="${PROJECT_ID}" mk --dataset \
    --location="${REGION}" \
    --description="DE Hub target dataset: ${DS}" \
    "${PROJECT_ID}:${DS}" 2>/dev/null || echo "  Dataset ${DS} already exists"
done

echo "  ✓ Datasets created"
echo ""

# ─── Step 2: Create source tables ────────────────────────────────
echo "[2/5] Creating source tables..."

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Source: CRM Customers
CREATE TABLE IF NOT EXISTS `source_crm.customers` (
  cust_id       STRING      NOT NULL,
  fname         STRING      NOT NULL,
  lname         STRING      NOT NULL,
  email_addr    STRING      NOT NULL,
  phone         STRING,
  address_line1 STRING,
  city          STRING,
  state         STRING,
  country       STRING,
  customer_segment STRING,
  created_date  DATE        NOT NULL,
  updated_at    TIMESTAMP   NOT NULL
);
SQL

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Source: Product Catalog
CREATE TABLE IF NOT EXISTS `source_catalog.products` (
  product_id    INT64       NOT NULL,
  product_name  STRING      NOT NULL,
  category      STRING      NOT NULL,
  subcategory   STRING,
  brand         STRING,
  unit_price    FLOAT64     NOT NULL,
  cost_price    FLOAT64,
  is_active     BOOL        NOT NULL,
  created_date  DATE        NOT NULL,
  updated_at    TIMESTAMP   NOT NULL
);
SQL

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Source: Order Lines
CREATE TABLE IF NOT EXISTS `source_orders.order_lines` (
  ord_id        STRING      NOT NULL,
  line_seq      INT64       NOT NULL,
  customer_id   INT64       NOT NULL,
  product_id    INT64       NOT NULL,
  order_date    DATE        NOT NULL,
  quantity      INT64       NOT NULL,
  unit_price    FLOAT64     NOT NULL,
  discount_amount FLOAT64,
  total_amount  FLOAT64     NOT NULL,
  order_status  STRING      NOT NULL,
  shipping_date DATE,
  loaded_at     TIMESTAMP   NOT NULL
);
SQL

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Source: Order Events
CREATE TABLE IF NOT EXISTS `source_events.order_status_changes` (
  event_id        STRING      NOT NULL,
  order_id        INT64       NOT NULL,
  event_type      STRING      NOT NULL,
  event_timestamp TIMESTAMP   NOT NULL,
  event_payload   JSON,
  loaded_at       TIMESTAMP   NOT NULL
);
SQL

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Source: Shipping Regions (reference)
CREATE TABLE IF NOT EXISTS `source_reference.shipping_regions` (
  region_code      STRING   NOT NULL,
  region_name      STRING   NOT NULL,
  country          STRING   NOT NULL,
  shipping_zone    STRING   NOT NULL,
  avg_delivery_days INT64
);
SQL

echo "  ✓ Source tables created"
echo ""

# ─── Step 3: Load synthetic data ─────────────────────────────────
echo "[3/5] Loading synthetic sample data..."

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Insert 100 sample customers
INSERT INTO `source_crm.customers`
SELECT
  CAST(id AS STRING) AS cust_id,
  CONCAT('First_', CAST(id AS STRING)) AS fname,
  CONCAT('Last_', CAST(id AS STRING)) AS lname,
  CONCAT('user', CAST(id AS STRING), '@example.com') AS email_addr,
  CONCAT('+1555', LPAD(CAST(id AS STRING), 7, '0')) AS phone,
  CONCAT(CAST(id * 10 AS STRING), ' Main Street') AS address_line1,
  (ARRAY['New York','Los Angeles','Chicago','Houston','Phoenix','Philadelphia','Dallas','Austin','Denver','Seattle'])[OFFSET(MOD(id, 10))] AS city,
  (ARRAY['NY','CA','IL','TX','AZ','PA','TX','TX','CO','WA'])[OFFSET(MOD(id, 10))] AS state,
  'US' AS country,
  (ARRAY['premium','standard','basic'])[OFFSET(MOD(id, 3))] AS customer_segment,
  DATE_ADD(DATE '2022-01-01', INTERVAL CAST(MOD(id * 7, 900) AS INT64) DAY) AS created_date,
  TIMESTAMP_ADD(TIMESTAMP '2024-01-01 00:00:00 UTC', INTERVAL CAST(MOD(id * 13, 86400 * 365) AS INT64) SECOND) AS updated_at
FROM UNNEST(GENERATE_ARRAY(1, 100)) AS id;
SQL

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Insert 50 sample products
INSERT INTO `source_catalog.products`
SELECT
  id AS product_id,
  CONCAT('Product_', CAST(id AS STRING)) AS product_name,
  (ARRAY['Electronics','Clothing','Home','Sports','Books'])[OFFSET(MOD(id, 5))] AS category,
  (ARRAY['Laptops','Shirts','Kitchen','Running','Fiction','Phones','Pants','Bedroom','Swimming','Non-Fiction'])[OFFSET(MOD(id, 10))] AS subcategory,
  (ARRAY['BrandA','BrandB','BrandC','BrandD','BrandE'])[OFFSET(MOD(id, 5))] AS brand,
  ROUND(10.0 + MOD(id * 17, 490), 2) AS unit_price,
  ROUND(5.0 + MOD(id * 11, 200), 2) AS cost_price,
  MOD(id, 7) != 0 AS is_active,
  DATE_ADD(DATE '2021-06-01', INTERVAL CAST(MOD(id * 11, 1000) AS INT64) DAY) AS created_date,
  TIMESTAMP_ADD(TIMESTAMP '2024-06-01 00:00:00 UTC', INTERVAL CAST(MOD(id * 19, 86400 * 180) AS INT64) SECOND) AS updated_at
FROM UNNEST(GENERATE_ARRAY(1, 50)) AS id;
SQL

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Insert 500 sample order lines
INSERT INTO `source_orders.order_lines`
SELECT
  CAST(CAST(FLOOR(id / 3) + 1000 AS INT64) AS STRING) AS ord_id,
  MOD(id, 3) + 1 AS line_seq,
  MOD(id, 100) + 1 AS customer_id,
  MOD(id, 50) + 1 AS product_id,
  DATE_ADD(DATE '2024-01-01', INTERVAL CAST(MOD(id * 3, 365) AS INT64) DAY) AS order_date,
  MOD(id, 5) + 1 AS quantity,
  ROUND(10.0 + MOD(id * 17, 490), 2) AS unit_price,
  CASE WHEN MOD(id, 4) = 0 THEN ROUND(MOD(id * 3, 50) * 0.5, 2) ELSE NULL END AS discount_amount,
  ROUND((MOD(id, 5) + 1) * (10.0 + MOD(id * 17, 490)) - COALESCE(CASE WHEN MOD(id, 4) = 0 THEN MOD(id * 3, 50) * 0.5 ELSE 0 END, 0), 2) AS total_amount,
  (ARRAY['pending','confirmed','shipped','delivered','cancelled'])[OFFSET(MOD(id, 5))] AS order_status,
  CASE WHEN MOD(id, 5) IN (2, 3) THEN DATE_ADD(DATE '2024-01-01', INTERVAL CAST(MOD(id * 3, 365) + 3 AS INT64) DAY) ELSE NULL END AS shipping_date,
  TIMESTAMP_ADD(TIMESTAMP '2024-01-01 00:00:00 UTC', INTERVAL CAST(id * 3600 AS INT64) SECOND) AS loaded_at
FROM UNNEST(GENERATE_ARRAY(1, 500)) AS id;
SQL

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Insert 200 sample order events
INSERT INTO `source_events.order_status_changes`
SELECT
  GENERATE_UUID() AS event_id,
  MOD(id, 167) + 1000 AS order_id,
  (ARRAY['created','updated','shipped','delivered','cancelled'])[OFFSET(MOD(id, 5))] AS event_type,
  TIMESTAMP_ADD(TIMESTAMP '2024-01-01 00:00:00 UTC', INTERVAL CAST(id * 7200 AS INT64) SECOND) AS event_timestamp,
  JSON '{"source": "order_service", "version": "1.0"}' AS event_payload,
  TIMESTAMP_ADD(TIMESTAMP '2024-01-01 00:00:00 UTC', INTERVAL CAST(id * 7200 + 60 AS INT64) SECOND) AS loaded_at
FROM UNNEST(GENERATE_ARRAY(1, 200)) AS id;
SQL

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache <<'SQL'
-- Insert shipping region reference data
INSERT INTO `source_reference.shipping_regions` VALUES
  ('US-EAST', 'US East Coast', 'US', 'Zone-1', 3),
  ('US-WEST', 'US West Coast', 'US', 'Zone-2', 5),
  ('US-CENT', 'US Central', 'US', 'Zone-1', 4),
  ('US-SOUTH', 'US South', 'US', 'Zone-1', 4),
  ('CA-EAST', 'Canada East', 'CA', 'Zone-3', 7),
  ('CA-WEST', 'Canada West', 'CA', 'Zone-3', 8),
  ('UK-ALL', 'United Kingdom', 'GB', 'Zone-4', 10),
  ('EU-WEST', 'Western Europe', 'EU', 'Zone-4', 12),
  ('APAC-AU', 'Australia', 'AU', 'Zone-5', 14),
  ('APAC-JP', 'Japan', 'JP', 'Zone-5', 12);
SQL

echo "  ✓ Sample data loaded"
echo ""

# ─── Step 4: Verify row counts ───────────────────────────────────
echo "[4/5] Verifying data..."

for TABLE in "source_crm.customers" "source_catalog.products" "source_orders.order_lines" "source_events.order_status_changes" "source_reference.shipping_regions"; do
  COUNT=$(bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=csv --nouse_cache \
    "SELECT COUNT(*) FROM \`${TABLE}\`" 2>/dev/null | tail -1)
  echo "  ${TABLE}: ${COUNT} rows"
done

echo ""

# ─── Step 5: Summary ─────────────────────────────────────────────
echo "[5/5] Setup complete!"
echo ""
echo "============================================================"
echo "SOURCE DATA READY"
echo "============================================================"
echo ""
echo "Source datasets:"
echo "  source_crm.customers            — 100 rows"
echo "  source_catalog.products          — 50 rows"
echo "  source_orders.order_lines        — 500 rows"
echo "  source_events.order_status_changes — 200 rows"
echo "  source_reference.shipping_regions — 10 rows"
echo ""
echo "Target datasets (empty, ready for pipeline):"
echo "  de_hub_staging    — staging tables will be created here"
echo "  de_hub_analytics  — dimension & fact tables will be created here"
echo ""
echo "Next steps:"
echo "  1. Run the agent to generate DDL/DML"
echo "  2. Execute DDL to create target tables"
echo "  3. Execute DML to run transformations"
echo "  4. Deploy DAGs to Cloud Composer"
echo "============================================================"
