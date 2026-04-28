#!/bin/bash
# =============================================================================
# DE Hub Agent — Generate & Execute Pipeline
# Runs the agent, then replaces placeholders with real GCP values
# and executes DDL + DML against BigQuery
#
# Usage:
#   chmod +x run_pipeline.sh
#   ./run_pipeline.sh <PROJECT_ID> <TARGET_DATASET> <SOURCE_DATASET_PREFIX>
#
# Example:
#   ./run_pipeline.sh my-gcp-project de_hub_analytics source
# =============================================================================

set -euo pipefail

PROJECT_ID="${1:?Usage: ./run_pipeline.sh <PROJECT_ID> <TARGET_DATASET> <SOURCE_PREFIX>}"
TARGET_DATASET="${2:-de_hub_analytics}"
SOURCE_PREFIX="${3:-source}"

OUTPUT_DIR="$(pwd)/output/live-run-$(date +%Y%m%d_%H%M%S)"

echo "============================================================"
echo "DE Hub Agent — Generate & Execute Pipeline"
echo "Project:        ${PROJECT_ID}"
echo "Target Dataset: ${TARGET_DATASET}"
echo "Source Prefix:  ${SOURCE_PREFIX}_*"
echo "Output:         ${OUTPUT_DIR}"
echo "============================================================"
echo ""

# ─── Step 1: Run the agent ────────────────────────────────────────
echo "[1/4] Running code generation agent..."
cd "$(dirname "$0")/../de_hub_agent"
python3 main.py sample_payloads/ecommerce_medium.json "${OUTPUT_DIR}"
echo ""

# ─── Step 2: Replace placeholders with real values ────────────────
echo "[2/4] Replacing placeholders with real GCP values..."

find "${OUTPUT_DIR}" -name "*.sql" -exec sed -i \
  -e "s|\${PROJECT_ID}|${PROJECT_ID}|g" \
  -e "s|\${DATASET}|${TARGET_DATASET}|g" \
  -e "s|\${SOURCE_DATASET}|replace_per_file|g" \
  -e "s|\${ORG_DOMAIN}|prodapt.com|g" \
  {} \;

# Fix source dataset references per table (each source system has its own dataset)
for f in "${OUTPUT_DIR}"/dml/*.sql "${OUTPUT_DIR}"/ddl/*.sql; do
  [ -f "$f" ] || continue
  sed -i \
    -e "s|replace_per_file\.customers|${SOURCE_PREFIX}_crm.customers|g" \
    -e "s|replace_per_file\.products|${SOURCE_PREFIX}_catalog.products|g" \
    -e "s|replace_per_file\.order_lines|${SOURCE_PREFIX}_orders.order_lines|g" \
    -e "s|replace_per_file\.order_status_changes|${SOURCE_PREFIX}_events.order_status_changes|g" \
    -e "s|replace_per_file\.shipping_regions|${SOURCE_PREFIX}_reference.shipping_regions|g" \
    "$f"
done

echo "  ✓ Placeholders replaced"
echo ""

# ─── Step 3: Execute DDL (create target tables) ──────────────────
echo "[3/4] Executing DDL — creating target tables in ${TARGET_DATASET}..."

# Order matters: dimensions first, then facts, then staging
for DDL_FILE in \
  "${OUTPUT_DIR}/ddl/dim_shipping_region.sql" \
  "${OUTPUT_DIR}/ddl/dim_product.sql" \
  "${OUTPUT_DIR}/ddl/dim_customer.sql" \
  "${OUTPUT_DIR}/ddl/fct_orders.sql" \
  "${OUTPUT_DIR}/ddl/fct_daily_sales_summary.sql" \
  "${OUTPUT_DIR}/ddl/stg_order_events.sql"; do

  if [ -f "$DDL_FILE" ]; then
    FNAME=$(basename "$DDL_FILE")
    echo "  Executing: ${FNAME}..."
    bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache < "$DDL_FILE" 2>&1 || {
      echo "  ⚠ Warning: ${FNAME} had issues (table may already exist)"
    }
  fi
done

# Execute grants
if [ -f "${OUTPUT_DIR}/ddl/_grants.sql" ]; then
  echo "  Executing: _grants.sql..."
  bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache < "${OUTPUT_DIR}/ddl/_grants.sql" 2>&1 || {
    echo "  ⚠ Warning: Grants may need manual adjustment for your org"
  }
fi

echo "  ✓ Target tables created"
echo ""

# ─── Step 4: Execute DML (run transformations) ───────────────────
echo "[4/4] Executing DML — running transformations..."

# Order: reference dims first, then SCD dims, then incremental facts, then aggregates
for DML_FILE in \
  "${OUTPUT_DIR}/dml/refresh_dim_shipping_region.sql" \
  "${OUTPUT_DIR}/dml/merge_dim_product.sql" \
  "${OUTPUT_DIR}/dml/merge_dim_customer.sql" \
  "${OUTPUT_DIR}/dml/append_fct_orders.sql" \
  "${OUTPUT_DIR}/dml/append_stg_order_events.sql" \
  "${OUTPUT_DIR}/dml/refresh_fct_daily_sales_summary.sql"; do

  if [ -f "$DML_FILE" ]; then
    FNAME=$(basename "$DML_FILE")
    echo "  Executing: ${FNAME}..."
    bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --nouse_cache < "$DML_FILE" 2>&1 || {
      echo "  ✗ FAILED: ${FNAME}"
    }
  fi
done

echo ""

# ─── Summary ─────────────────────────────────────────────────────
echo "============================================================"
echo "PIPELINE EXECUTION COMPLETE"
echo "============================================================"
echo ""
echo "Verify in BigQuery Console:"
echo "  https://console.cloud.google.com/bigquery?project=${PROJECT_ID}"
echo ""
echo "Target tables created in ${PROJECT_ID}.${TARGET_DATASET}:"
echo "  - dim_shipping_region  (full refresh from reference)"
echo "  - dim_product          (SCD-1 merge from catalog)"
echo "  - dim_customer         (SCD-2 merge from CRM)"
echo "  - fct_orders           (incremental append from order lines)"
echo "  - stg_order_events     (incremental append from events)"
echo "  - fct_daily_sales_summary (full refresh aggregate from orders)"
echo ""
echo "Run counts:"
for TABLE in dim_shipping_region dim_product dim_customer fct_orders stg_order_events fct_daily_sales_summary; do
  COUNT=$(bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=csv --nouse_cache \
    "SELECT COUNT(*) FROM \`${TARGET_DATASET}.${TABLE}\`" 2>/dev/null | tail -1)
  echo "  ${TARGET_DATASET}.${TABLE}: ${COUNT} rows"
done
echo ""
echo "Output directory: ${OUTPUT_DIR}"
echo "============================================================"
