#!/usr/bin/env bash
# Start the PP-DocLayoutV3 HTTP service for metal-doc-agent.
# Usage: bash start_layout_api.sh [--detach|--check|--help]
set -Eeuo pipefail

RUNTIME_ROOT="${MODEL_RUNTIME_ROOT:-/home/grainuser/metal-doc-agent-runtime}"
PYTHON_BIN="${METAL_DOC_LAYOUT_PYTHON:-/home/grainuser/hansonDoc_RAG/backend/.venv/bin/python}"
BACKEND_ROOT="${METAL_DOC_BACKEND_ROOT:-/home/grainuser/hansonDoc_RAG/backend}"
MODEL_DIR="${LAYOUT_MODEL_DIR:-/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3}"
PORT="${LAYOUT_PORT:-9978}"
API_FILE="$RUNTIME_ROOT/layout_api.py"
PID_FILE="$RUNTIME_ROOT/run/layout_api_${PORT}.pid"
LOG_FILE="$RUNTIME_ROOT/logs/layout_api_${PORT}.log"

mkdir -p "$RUNTIME_ROOT/run" "$RUNTIME_ROOT/logs"

pid_running() {
    [[ -f "$PID_FILE" ]] || return 1
    local pid
    pid="$(cat "$PID_FILE")"
    kill -0 "$pid" 2>/dev/null
}

health() { curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; }

status() {
    if pid_running && health; then
        echo "layout ready on :$PORT (PID $(cat "$PID_FILE"))"
    elif pid_running; then
        echo "layout process running, API still loading (PID $(cat "$PID_FILE")); log: $LOG_FILE"
    else
        echo "layout stopped"
    fi
}

case "${1:-}" in
    --check) status; exit 0 ;;
    --detach) ;;
    -h|--help) echo "Usage: bash start_layout_api.sh [--detach|--check|--help]"; exit 0 ;;
    "") ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
esac

if pid_running; then
    status
    exit 0
fi
[[ -x "$PYTHON_BIN" ]] || { echo "Python missing: $PYTHON_BIN" >&2; exit 1; }
[[ -f "$API_FILE" ]] || { echo "layout_api.py missing: $API_FILE" >&2; exit 1; }
[[ -f "$MODEL_DIR/model.safetensors" ]] || { echo "layout model missing: $MODEL_DIR" >&2; exit 1; }
if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "Port $PORT already serves a healthy layout API; refusing to start another" >&2
    exit 1
fi

export PATH="$(dirname "$PYTHON_BIN"):$PATH"
export PYTHONPATH="$BACKEND_ROOT"
export LAYOUT_MODEL_DIR="$MODEL_DIR"
export LAYOUT_PORT="$PORT"

printf '\n[%s] starting layout api\n' "$(date '+%F %T')" >> "$LOG_FILE"
cd "$RUNTIME_ROOT"
nohup "$PYTHON_BIN" "$API_FILE" </dev/null >> "$LOG_FILE" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$PID_FILE"
sleep 2
if ! kill -0 "$pid" 2>/dev/null; then
    echo "layout API exited during startup; inspect $LOG_FILE" >&2
    exit 1
fi
echo "layout API started in background (PID $pid). Model load may take a minute."
echo "Check readiness: bash start_layout_api.sh --check"
