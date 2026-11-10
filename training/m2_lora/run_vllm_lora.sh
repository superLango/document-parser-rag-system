#!/usr/bin/env bash
# Serve Qwen3.5-9B plus a LoRA adapter through vLLM (OpenAI-compatible API).
#
# The venv ships vLLM 0.26.0 but installing `ninja` alone is not enough: vLLM's
# EngineCore subprocess calls `ninja` through PATH, so PATH must include the
# venv bin directory or kernel compilation dies with FileNotFoundError.
#
# PEFT adapters trained with transformers use `base_model.model.model.layers...`
# keys, while vLLM binds Qwen3.5 LoRA by full module path
# `base_model.model.language_model.model.layers...`. Serve a converted copy:
#   python code/convert_adapter_for_vllm.py --src adapter-v4 --dst adapter-v4-vllm
#   ADAPTER_PATH=$ROOT/adapter-v4-vllm bash code/run_vllm_lora.sh
# Without the conversion vLLM loads the adapter but silently applies no weights.
#
# Usage (model host):
#   bash /home/grainuser/hanson_m2/code/run_vllm_lora.sh > logs/vllm_v4.log 2>&1 &
set -uo pipefail

ROOT=${ROOT:-/home/grainuser/hanson_m2}
VENV=${VENV:-/home/grainuser/models/venv}
MODEL=${MODEL:-/home/grainuser/models/models/Qwen3.5-9B}
PORT=${PORT:-9991}
ADAPTER_NAME=${ADAPTER_NAME:-adapter-v4}
ADAPTER_PATH=${ADAPTER_PATH:-$ROOT/adapter-v4}
MAX_LEN=${MAX_LEN:-16384}
GPU_UTIL=${GPU_UTIL:-0.4}

export PATH="$VENV/bin:$PATH"
export VLLM_LOGGING_LEVEL=${VLLM_LOGGING_LEVEL:-INFO}

exec "$VENV/bin/vllm" serve "$MODEL" \
  --served-model-name Qwen3.5-9B \
  --trust-remote-code \
  --enable-lora \
  --lora-modules "${ADAPTER_NAME}=${ADAPTER_PATH}" \
  --port "$PORT" \
  --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization "$GPU_UTIL"
