#!/bin/bash
# Single-server startup:
#   1. Start requirements pod (if not already running)
#   2. Build the React frontend into Spring Boot's static folder
#   3. Run Spring Boot — serves UI + API on port 8080

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
POD_PORT=8001

# ── 1. Requirements pod ───────────────────────────────────────────────────────
if curl -s --max-time 2 "http://localhost:${POD_PORT}/api/v1/health" > /dev/null 2>&1; then
    echo "✓ Requirements pod already running on port ${POD_PORT}"
else
    echo "→ Starting requirements pod on port ${POD_PORT}..."
    cd "$SCRIPT_DIR"
    nohup python3 -m uvicorn core.requirements_pod.main:app \
        --host 0.0.0.0 --port "${POD_PORT}" \
        > pod.log 2>&1 &
    echo "  Pod PID: $!"

    echo -n "  Waiting for pod"
    for i in $(seq 1 20); do
        sleep 1
        if curl -s --max-time 1 "http://localhost:${POD_PORT}/api/v1/health" > /dev/null 2>&1; then
            echo " ready."
            break
        fi
        echo -n "."
        if [ "$i" -eq 20 ]; then
            echo " timed out — check pod.log"
            exit 1
        fi
    done
fi

# ── 2. Build frontend into Spring Boot static folder ─────────────────────────
echo "→ Building frontend..."
cd "$SCRIPT_DIR/WebApp/frontend"
npm install --silent
npm run build
echo "✓ Frontend built into backend/src/main/resources/static/"

# ── 3. Start Spring Boot (serves UI + API on port 8080) ──────────────────────
echo "→ Starting Spring Boot on port 8080..."
cd "$SCRIPT_DIR/WebApp/backend"
mvn spring-boot:run
