#!/usr/bin/env bash
# =============================================================================
# push_env_to_gcs.sh — Upload .env to GCS bucket (run once from local machine)
#
# After this, anyone on a GCP VM with the right service account attached
# can pull it automatically — no manual file copying needed.
#
# Usage:
#   chmod +x scripts/push_env_to_gcs.sh
#   ./scripts/push_env_to_gcs.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

GCS_BUCKET="${GCS_BUCKET:-deah}"
GCS_CONFIG_PREFIX="${GCS_CONFIG_PREFIX:-requirements-pod/_config}"
ENV_FILE="${REPO_DIR}/.env"

[[ -f "${ENV_FILE}" ]] || { echo "ERROR: ${ENV_FILE} not found"; exit 1; }

echo "Uploading .env to gs://${GCS_BUCKET}/${GCS_CONFIG_PREFIX}/.env ..."
gsutil cp "${ENV_FILE}" "gs://${GCS_BUCKET}/${GCS_CONFIG_PREFIX}/.env"

echo ""
echo "Done. Anyone on a VM with the service account attached can now run:"
echo "  ./scripts/vm_init.sh"
