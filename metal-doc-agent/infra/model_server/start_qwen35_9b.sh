#!/usr/bin/env bash
# Start Qwen3.5-9B for metal-doc-agent on the model host (GB10).
# Usage: bash start_qwen35_9b.sh [--detach|--check|--help]
set -Eeuo pipefail

RUNTIME_ROOT="${MODEL_RUNTIME_ROOT:-/home/grainuser/metal-doc-agent-runtime}"
VLLM_BIN="${METAL_DOC_VLLM_BIN:-/home/grainuser/hansonDoc_RAG_deploy/venv/bin/vllm}"
MODEL_DIR="${METAL_DOC_QWEN_MODEL_DIR:-/home/grainuser/models/models/Qwen3.5-9B}"
PORT="${METAL_DOC_QWEN_PORT:-9989}"
MODEL_NAME="${METAL_DOC_QWEN_NAME:-Qwen3.5-9B}"
PID_FILE="$RUNTIME_ROOT/run/qwen35_9b_${PORT}.pid"
LOG_FILE="$RUNTIME_ROOT/logs/vllm_qwen35_9b_${PORT}.log"

mkdir -p "$RUNTIME_ROOT/run" "$RUNTIME_ROOT/logs"

model_pid() {
    local proc pid args
    for proc in /proc/[0-9]*; do
        pid="${proc##*/}"
        [[ "$(stat -c %u "$proc" 2>/dev/null)" == "$(id -u)" ]] || continue
        args="$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null)" || continue
        [[ "$args" == *"vllm serve "* && "$args" == *"--port $PORT"* &&
           "$args" == *"--served-model-name $MODEL_NAME"* ]] || continue
        printf '%s\n' "$pid"
        return 0
    done
    return 1
}

port_listening() { ss -lntH "sport = :$PORT" 2>/dev/null | grep -q .; }
ready() { curl -fsS --max-time 3 "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; }

status() {
    local pid
    if pid="$(model_pid)"; then
        if ready; then
            echo "$MODEL_NAME ready on :$PORT (PID $pid)"
        else
            echo "$MODEL_NAME process running, API still loading (PID $pid); log: $LOG_FILE"
        fi
    elif port_listening; then
        echo ":$PORT is occupied by another process; no matching $MODEL_NAME process found"
    else
        echo "$MODEL_NAME stopped"
    fi
}

case "${1:-}" in
    --check) status; exit 0 ;;
    --detach) ;;
    -h|--help) echo "Usage: bash start_qwen35_9b.sh [--detach|--check|--help]"; exit 0 ;;
    "") ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
esac

if pid="$(model_pid)"; then
    status
    exit 0
fi
if port_listening; then
    echo "Port $PORT is occupied; refusing to start another model" >&2
    exit 1
fi
[[ -x "$VLLM_BIN" ]] || { echo "vLLM executable missing: $VLLM_BIN" >&2; exit 1; }
[[ -f "$MODEL_DIR/config.json" ]] || { echo "Model missing: $MODEL_DIR/config.json" >&2; exit 1; }

# flashinfer JIT needs ninja; the vLLM wrapper's venv is not on PATH in non-interactive SSH.
export PATH="$(dirname "$VLLM_BIN"):$PATH"
cd "$RUNTIME_ROOT"

printf '\n[%s] starting %s\n' "$(date '+%F %T')" "$MODEL_NAME" >> "$LOG_FILE"
nohup "$VLLM_BIN" serve "$MODEL_DIR" \
    --host 0.0.0.0 --port "$PORT" --served-model-name "$MODEL_NAME" \
    --trust-remote-code --tensor-parallel-size 1 \
    --max-model-len 16384 --max-num-seqs 2 --max-num-batched-tokens 16384 \
    --gpu-memory-utilization 0.35 --kv-cache-dtype fp8 \
    --enable-prefix-caching --language-model-only --reasoning-parser qwen3 \
    </dev/null >> "$LOG_FILE" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$PID_FILE"
sleep 2
if ! kill -0 "$pid" 2>/dev/null; then
    echo "Qwen3.5-9B exited during startup; inspect $LOG_FILE" >&2
    exit 1
fi
echo "Qwen3.5-9B started in background (PID $pid). Model loading may take several minutes."
echo "Check readiness: bash start_qwen35_9b.sh --check"
