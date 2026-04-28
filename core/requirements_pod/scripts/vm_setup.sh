#!/usr/bin/env bash
# =============================================================================
# vm_setup.sh — One-time VM bootstrap for TaskFlow AI Agent
#
# What it does:
#   1. Pulls .env secrets from GCP Secret Manager
#   2. Pulls the GCS service-account key from GCP Secret Manager
#   3. Writes both to the right paths so docker-compose picks them up
#   4. (Optional) Starts the stack
#
# Prerequisites on the VM:
#   - gcloud CLI installed and authenticated (or the VM has a service account
#     with roles/secretmanager.secretAccessor)
#   - Docker + docker-compose installed
#
# Usage:
#   chmod +x scripts/vm_setup.sh
#   ./scripts/vm_setup.sh                     # just pulls secrets + creds
#   ./scripts/vm_setup.sh --start             # also starts docker-compose
#   ./scripts/vm_setup.sh --project my-gcp-project  # override GCP project
# =============================================================================

set -euo pipefail

# ---------- defaults (override with flags or env vars) -----------------------
GCP_PROJECT="${GCP_PROJECT:-verizon-data}"
SECRET_ENV_NAME="${SECRET_ENV_NAME:-taskflow-env}"           # name in Secret Manager for .env contents
SECRET_SA_KEY_NAME="${SECRET_SA_KEY_NAME:-taskflow-gcs-sa-key}"  # name for the SA JSON key
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CREDS_DIR="${REPO_DIR}/credentials"
DO_START=false

# ---------- parse flags -------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)       DO_START=true; shift ;;
    --project)     GCP_PROJECT="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

echo "==> Repo dir : ${REPO_DIR}"
echo "==> GCP project: ${GCP_PROJECT}"

# ---------- 1. Pull .env from Secret Manager ----------------------------------
echo ""
echo "[1/3] Fetching .env from Secret Manager (${SECRET_ENV_NAME})..."
gcloud secrets versions access latest \
  --secret="${SECRET_ENV_NAME}" \
  --project="${GCP_PROJECT}" \
  > "${REPO_DIR}/.env"
echo "      Written to ${REPO_DIR}/.env"

# ---------- 2. Pull GCS SA key from Secret Manager ---------------------------
echo ""
echo "[2/3] Fetching GCS service-account key (${SECRET_SA_KEY_NAME})..."
mkdir -p "${CREDS_DIR}"
gcloud secrets versions access latest \
  --secret="${SECRET_SA_KEY_NAME}" \
  --project="${GCP_PROJECT}" \
  > "${CREDS_DIR}/gcs-sa-key.json"
chmod 600 "${CREDS_DIR}/gcs-sa-key.json"
echo "      Written to ${CREDS_DIR}/gcs-sa-key.json"

# ---------- 3. (Optional) start the stack ------------------------------------
echo ""
echo "[3/3] Stack startup..."
if [ "${DO_START}" = true ]; then
  cd "${REPO_DIR}"
  docker compose up --build -d
  echo "      Stack started. API: http://localhost:8000  UI: http://localhost:5173"
else
  echo "      Skipped (pass --start to auto-start)"
  echo "      Run manually: docker compose up --build -d"
fi

echo ""
echo "Done."
