#!/bin/bash
# =============================================================================
# DE Hub Agent — Cloud Composer Deployment
# Deploys DAG and SQL files to an existing Cloud Composer environment
#
# Prerequisites:
#   - Cloud Composer environment already created
#   - gcloud CLI authenticated with Composer admin permissions
#
# Usage:
#   ./deploy_to_composer.sh <PROJECT_ID> <COMPOSER_ENV> <REGION> <TARGET_DATASET>
#
# Example:
#   ./deploy_to_composer.sh my-gcp-project my-composer-env us-central1 de_hub_analytics
# =============================================================================

set -euo pipefail

PROJECT_ID="${1:?Usage: ./deploy_to_composer.sh <PROJECT_ID> <COMPOSER_ENV> <REGION> <TARGET_DATASET>}"
COMPOSER_ENV="${2:?Provide Cloud Composer environment name}"
REGION="${3:-us-central1}"
TARGET_DATASET="${4:-de_hub_analytics}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="${SCRIPT_DIR}/.."

echo "============================================================"
echo "DE Hub Agent — Cloud Composer Deployment"
echo "Project:     ${PROJECT_ID}"
echo "Composer:    ${COMPOSER_ENV}"
echo "Region:      ${REGION}"
echo "Dataset:     ${TARGET_DATASET}"
echo "============================================================"
echo ""

# ─── Step 1: Get the Composer DAGs bucket ─────────────────────────
echo "[1/5] Getting Composer DAGs bucket..."
DAGS_BUCKET=$(gcloud composer environments describe "${COMPOSER_ENV}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --format="get(config.dagGcsPrefix)")

echo "  DAGs bucket: ${DAGS_BUCKET}"
echo ""

# ─── Step 2: Set Airflow Variables ────────────────────────────────
echo "[2/5] Setting Airflow variables..."

gcloud composer environments run "${COMPOSER_ENV}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  variables set -- gcp_project_id "${PROJECT_ID}"

gcloud composer environments run "${COMPOSER_ENV}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  variables set -- de_hub_target_dataset "${TARGET_DATASET}"

echo "  ✓ Variables set: gcp_project_id, de_hub_target_dataset"
echo ""

# ─── Step 3: Generate SQL with real project references ────────────
echo "[3/5] Generating SQL files with real project references..."

# Run the agent to generate SQL
cd "${DEPLOY_DIR}/de_hub_agent" 2>/dev/null || cd "${SCRIPT_DIR}/../de_hub_agent"
TEMP_OUTPUT="/tmp/de_hub_composer_$(date +%s)"
python3 main.py sample_payloads/ecommerce_medium.json "${TEMP_OUTPUT}"

# Replace placeholders
find "${TEMP_OUTPUT}" -name "*.sql" -exec sed -i \
  -e "s|\${PROJECT_ID}|${PROJECT_ID}|g" \
  -e "s|\${DATASET}|${TARGET_DATASET}|g" \
  -e "s|\${ORG_DOMAIN}|prodapt.com|g" \
  {} \;

# Fix source dataset references
for f in "${TEMP_OUTPUT}"/dml/*.sql "${TEMP_OUTPUT}"/ddl/*.sql; do
  [ -f "$f" ] || continue
  sed -i \
    -e "s|\${SOURCE_DATASET}\.customers|source_crm.customers|g" \
    -e "s|\${SOURCE_DATASET}\.products|source_catalog.products|g" \
    -e "s|\${SOURCE_DATASET}\.order_lines|source_orders.order_lines|g" \
    -e "s|\${SOURCE_DATASET}\.order_status_changes|source_events.order_status_changes|g" \
    -e "s|\${SOURCE_DATASET}\.shipping_regions|source_reference.shipping_regions|g" \
    "$f"
done

echo "  ✓ SQL generated at ${TEMP_OUTPUT}"
echo ""

# ─── Step 4: Upload SQL files to Composer bucket ──────────────────
echo "[4/5] Uploading SQL files to Composer..."

gsutil -m cp "${TEMP_OUTPUT}"/dml/*.sql "${DAGS_BUCKET}/sql/de_hub/"
echo "  ✓ DML files uploaded"

# ─── Step 5: Upload the DAG ──────────────────────────────────────
echo "[5/5] Uploading DAG file..."

gsutil cp "${DEPLOY_DIR}/04_dags/de_hub_ecommerce_pipeline.py" "${DAGS_BUCKET}/"
echo "  ✓ DAG uploaded"

# Cleanup
rm -rf "${TEMP_OUTPUT}"

echo ""
echo "============================================================"
echo "DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""
echo "The DAG will appear in the Airflow UI within 2-3 minutes."
echo ""
echo "Airflow UI:"
WEBSERVER=$(gcloud composer environments describe "${COMPOSER_ENV}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --format="get(config.airflowUri)" 2>/dev/null || echo "  (check GCP Console)")
echo "  ${WEBSERVER}"
echo ""
echo "Manual trigger:"
echo "  gcloud composer environments run ${COMPOSER_ENV} \\"
echo "    --project=${PROJECT_ID} --location=${REGION} \\"
echo "    dags trigger -- de_hub_ecommerce_pipeline"
echo ""
echo "============================================================"
