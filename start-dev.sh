#!/bin/bash
# Start requirements pod (if not already running) + frontend dev server

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
POD_PORT=8001

# ── Pod ───────────────────────────────────────────────────────────────────────
if curl -s --max-time 2 "http://localhost:${POD_PORT}/api/v1/health" > /dev/null 2>&1; then
    echo "✓ Requirements pod already running on port ${POD_PORT}"
else
    echo "→ Starting requirements pod on port ${POD_PORT}..."
    cd "$SCRIPT_DIR"
    nohup python3 -m uvicorn core.requirements_pod.main:app \
        --host 0.0.0.0 --port "${POD_PORT}" \
        > pod.log 2>&1 &
    POD_PID=$!
    echo "  Pod PID: ${POD_PID}"

    # Wait up to 15s for pod to be ready
    echo -n "  Waiting for pod"
    for i in $(seq 1 15); do
        sleep 1
        if curl -s --max-time 1 "http://localhost:${POD_PORT}/api/v1/health" > /dev/null 2>&1; then
            echo " ready."
            break
        fi
        echo -n "."
        if [ "$i" -eq 15 ]; then
            echo " timed out. Check pod.log for errors."
        fi
    done
fi

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "→ Starting frontend dev server..."
cd "$SCRIPT_DIR/WebApp/frontend"
npm run dev
