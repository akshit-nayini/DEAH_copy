#!/usr/bin/env bash
# =============================================================================
# vm_init.sh — One-command VM setup (no manual file uploads needed)
#
# Run on the VM after cloning the repo:
#   chmod +x scripts/vm_init.sh
#   ./scripts/vm_init.sh
#
# What it does:
#   1. Pulls .env from GCS bucket using the VM's attached service account
#      (no JSON key file needed — VM identity is enough)
#   2. Sets GCS_CREDENTIALS_PATH to empty so the app uses ADC (no key file)
#   3. Runs DB migrations
#   4. Starts the stack with docker compose
#
# Prerequisites on the VM:
#   - gcloud CLI installed  (sudo apt install google-cloud-cli)
#   - Docker + docker compose installed
#   - VM has a service account with Storage Object Viewer on the bucket
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

GCS_BUCKET="${GCS_BUCKET:-deah}"
GCS_CONFIG_PREFIX="${GCS_CONFIG_PREFIX:-requirements-pod/_config}"

cd "${REPO_DIR}"

# ---------- 1. Pull .env from GCS (uses VM's service account via ADC) --------
echo "[1/3] Pulling .env from gs://${GCS_BUCKET}/${GCS_CONFIG_PREFIX}/.env ..."
gsutil cp "gs://${GCS_BUCKET}/${GCS_CONFIG_PREFIX}/.env" .env
echo "      Done."

# ---------- 2. Override credentials path — VM uses ADC, no key file needed ---
echo ""
echo "[2/3] Configuring for VM (using Application Default Credentials) ..."
# Remove GCS_CREDENTIALS_PATH so GCSStorageProvider falls back to ADC
sed -i 's|^GCS_CREDENTIALS_PATH=.*|GCS_CREDENTIALS_PATH=|' .env
echo "      GCS_CREDENTIALS_PATH cleared — VM SA will be used automatically."

# ---------- 3. Start the stack -----------------------------------------------
echo ""
echo "[3/3] Starting stack ..."
docker compose up --build -d

echo ""
echo "Stack is up."
echo "  API : http://localhost:8000"
echo "  UI  : http://localhost:5173"
echo ""
echo "Next time just run:  docker compose up -d"
