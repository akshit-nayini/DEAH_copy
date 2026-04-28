#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Copy secrets to VM and start the stack
#
# Run from your LOCAL machine:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh
#
# On FIRST run: copies .env + credentials to the VM
# On subsequent runs: skips copy if files already exist (pass --force to overwrite)
#
# Set these once, or export them in your shell profile:
#   export VM_USER=pavithra
#   export VM_HOST=<your-vm-external-ip>
#   export VM_APP_DIR=/home/pavithra/DEAH      # where the repo lives on the VM
# =============================================================================

set -euo pipefail

VM_USER="${VM_USER:-pavithra}"
VM_HOST="${VM_HOST:-}"          # fill in or export before running
VM_APP_DIR="${VM_APP_DIR:-/home/${VM_USER}/DEAH/core/requirements_pod}"
FORCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --host)  VM_HOST="$2"; shift 2 ;;
    --user)  VM_USER="$2"; shift 2 ;;
    --dir)   VM_APP_DIR="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

[[ -z "${VM_HOST}" ]] && { echo "ERROR: set VM_HOST=<vm-ip> or pass --host <ip>"; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_TARGET="${VM_USER}@${VM_HOST}"

echo "==> Target: ${SSH_TARGET}:${VM_APP_DIR}"

# ---------- 1. Copy .env if missing (or --force) -----------------------------
echo ""
echo "[1/3] Checking .env on VM..."
ENV_EXISTS=$(ssh "${SSH_TARGET}" "[ -f '${VM_APP_DIR}/.env' ] && echo yes || echo no")

if [[ "${ENV_EXISTS}" == "no" || "${FORCE}" == "true" ]]; then
  echo "      Copying .env..."
  scp "${REPO_DIR}/.env" "${SSH_TARGET}:${VM_APP_DIR}/.env"
  echo "      Done."
else
  echo "      Already exists — skipping (use --force to overwrite)"
fi

# ---------- 2. Copy GCS credentials if missing (or --force) ------------------
echo ""
echo "[2/3] Checking credentials/gcs-sa-key.json on VM..."
KEY_EXISTS=$(ssh "${SSH_TARGET}" "[ -f '${VM_APP_DIR}/credentials/gcs-sa-key.json' ] && echo yes || echo no")

if [[ "${KEY_EXISTS}" == "no" || "${FORCE}" == "true" ]]; then
  echo "      Copying credentials/gcs-sa-key.json..."
  ssh "${SSH_TARGET}" "mkdir -p ${VM_APP_DIR}/credentials"
  scp "${REPO_DIR}/credentials/gcs-sa-key.json" \
      "${SSH_TARGET}:${VM_APP_DIR}/credentials/gcs-sa-key.json"
  ssh "${SSH_TARGET}" "chmod 600 ${VM_APP_DIR}/credentials/gcs-sa-key.json"
  echo "      Done."
else
  echo "      Already exists — skipping (use --force to overwrite)"
fi

# ---------- 3. Start the stack -----------------------------------------------
echo ""
echo "[3/3] Starting stack on VM..."
ssh "${SSH_TARGET}" "cd ${VM_APP_DIR} && docker compose up --build -d"

echo ""
echo "Stack is up."
echo "  API : http://${VM_HOST}:8000"
echo "  UI  : http://${VM_HOST}:5173"
