#!/usr/bin/env bash
# =============================================================================
# start.sh — Start the TaskFlow stack on the VM
#
# Run this directly on the VM (not locally):
#   chmod +x scripts/start.sh
#   ./scripts/start.sh
#
# Assumes .env and credentials/gcs-sa-key.json are already on disk.
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

# Validate required files are present
MISSING=()
[[ ! -f ".env" ]]                          && MISSING+=(".env")
[[ ! -f "credentials/gcs-sa-key.json" ]]   && MISSING+=("credentials/gcs-sa-key.json")

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "ERROR: Missing required files:"
  for f in "${MISSING[@]}"; do echo "  - ${f}"; done
  echo ""
  echo "Run from your LOCAL machine to copy them:"
  echo "  ./scripts/deploy.sh --host <vm-ip>"
  exit 1
fi

docker compose up --build -d
echo ""
echo "Stack is up."
echo "  API : http://localhost:8000"
echo "  UI  : http://localhost:5173"
