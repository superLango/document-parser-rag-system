#!/usr/bin/env bash
# Start the GLM-OCR vLLM service on the model plane with the tuned batch settings.
#
# Tuned for the engine's OCR workload (many short block requests):
#   * max-num-seqs 12           (2026-11-02: faster end-to-end on long tables)
#   * max-num-batched-tokens 8192
#   * prefix caching + chunked prefill + fp8 KV
#
# Usage: start_glm_ocr.sh [max-num-seqs] [max-num-batched-tokens] [gpu-memory-utilization]
# Stop:  pkill -f 'vllm serve .*GLM-OCR'
set -euo pipefail

DEPLOY_ROOT=${DEPLOY_ROOT:-/home/grainuser/hansonDoc_RAG_deploy}
MODEL=${MODEL:-$DEPLOY_ROOT/models/glm-ocr/GLM-OCR}
VENV=${VENV:-/home/grainuser/models/venv}
SEQS=${1:-${MAX_NUM_SEQS:-12}}
BATCHED=${2:-${MAX_NUM_BATCHED_TOKENS:-8192}}
GPU_UTIL=${3:-${GPU_MEMORY_UTILIZATION:-0.4}}
LOG=${LOG:-/home/grainuser/hansonDoc_RAG/logs/vllm_glm_ocr_9977.log}

# flashinfer JIT needs ninja/nvcc on PATH (SSH non-login shells lack ~/.local/bin).
export PATH="$VENV/bin:/home/grainuser/.local/bin:/usr/local/cuda/bin:$PATH"

cd "$DEPLOY_ROOT"
mkdir -p "$(dirname "$LOG")"
setsid nohup "$VENV/bin/vllm" serve "$MODEL" \
  --host 0.0.0.0 \
  --port 9977 \
  --served-model-name GLM-OCR \
  --trust-remote-code \
  --max-num-seqs "$SEQS" \
  --max-num-batched-tokens "$BATCHED" \
  --max-model-len 32768 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --gpu-memory-utilization "$GPU_UTIL" \
  --kv-cache-dtype fp8 >> "$LOG" 2>&1 < /dev/null &

echo "GLM-OCR starting: max_num_seqs=$SEQS batched_tokens=$BATCHED gpu_util=$GPU_UTIL (log: $LOG)"
for _ in $(seq 1 120); do
  if curl -sf -m 3 http://127.0.0.1:9977/v1/models >/dev/null; then
    echo "GLM-OCR ready"
    echo "NOTE: warm batch sizes 1/4/8 once after a restart (first inference JIT can take minutes)."
    exit 0
  fi
  sleep 2
done
echo "GLM-OCR NOT READY; tail of log:" >&2
tail -n 40 "$LOG" >&2
exit 1
