#!/usr/bin/env bash
# =============================================================================
# push_secrets_to_gcp.sh — Upload local secrets to GCP Secret Manager
#
# Run this ONCE from your local machine (or whenever secrets change).
# After this, the VM uses vm_setup.sh to pull them automatically.
#
# Usage:
#   chmod +x scripts/push_secrets_to_gcp.sh
#   ./scripts/push_secrets_to_gcp.sh
#   ./scripts/push_secrets_to_gcp.sh --project my-gcp-project
# =============================================================================

set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-verizon-data}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) GCP_PROJECT="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

ENV_FILE="${REPO_DIR}/.env"
SA_KEY_FILE="${REPO_DIR}/credentials/gcs-sa-key.json"

# Validate files exist
[[ -f "${ENV_FILE}" ]]    || { echo "ERROR: ${ENV_FILE} not found"; exit 1; }
[[ -f "${SA_KEY_FILE}" ]] || { echo "ERROR: ${SA_KEY_FILE} not found"; exit 1; }

create_or_update_secret() {
  local name="$1"
  local file="$2"

  if gcloud secrets describe "${name}" --project="${GCP_PROJECT}" &>/dev/null; then
    echo "  Updating existing secret: ${name}"
    gcloud secrets versions add "${name}" \
      --data-file="${file}" \
      --project="${GCP_PROJECT}"
  else
    echo "  Creating new secret: ${name}"
    gcloud secrets create "${name}" \
      --data-file="${file}" \
      --replication-policy="automatic" \
      --project="${GCP_PROJECT}"
  fi
}

echo "==> Pushing secrets to GCP project: ${GCP_PROJECT}"
echo ""
echo "[1/2] .env → secret 'taskflow-env'"
create_or_update_secret "taskflow-env" "${ENV_FILE}"

echo ""
echo "[2/2] gcs-sa-key.json → secret 'taskflow-gcs-sa-key'"
create_or_update_secret "taskflow-gcs-sa-key" "${SA_KEY_FILE}"

echo ""
echo "Done. Secrets are stored in GCP Secret Manager."
echo "On your VM run:  ./scripts/vm_setup.sh --start"
echo ""
echo "Grant the VM's service account access with:"
echo "  gcloud projects add-iam-policy-binding ${GCP_PROJECT} \\"
echo "    --member='serviceAccount:YOUR_VM_SA@${GCP_PROJECT}.iam.gserviceaccount.com' \\"
echo "    --role='roles/secretmanager.secretAccessor'"
