#!/usr/bin/env bash
# M2.3 LoRA 重跑脚本（保守配置，GB10 / spark-15b6）。
#
# 2026-10-28 全量训练在 batch=4 / max_seq=2048 下跑到第 3 步后整机硬挂（无 OOM 日志）。
# 数据 token 分布：p50 219 / p90 834 / p99 1064 / max 1481，max_seq=1280 只截断 1 条。
# 因此改为 batch=1 + grad_accum=16（等效 batch 16）、max_seq=1280，并每 10 步存 checkpoint。
#
# 用法（建议在 tmux 中运行）：
#   tmux new-session -d -s m2train \
#     'bash /home/grainuser/hanson_m2/code/run_m2_lora.sh > /home/grainuser/hanson_m2/logs/train.log 2>&1'
set -uo pipefail

ROOT=${ROOT:-/home/grainuser/hanson_m2}
PY=${PY:-/home/grainuser/miniforge3/envs/grain_ultra/bin/python}
MODEL=${MODEL:-/home/grainuser/models/models/Qwen3.5-9B}
DATA_DIR=${DATA_DIR:-$ROOT/data}
OUTPUT=${OUTPUT:-$ROOT/adapter-v1}
MAX_SEQ=${MAX_SEQ:-1280}

export PYTORCH_ALLOC_CONF=expandable_segments:True
export TOKENIZERS_PARALLELISM=false

mkdir -p "$ROOT/logs"

# 内存看门狗：每 30s 记一次，若再次硬挂至少留下最后水位
(
  while true; do
    printf '%s ' "$(date '+%F %T')"
    awk '/MemTotal|MemAvailable|SwapFree/ {printf "%s=%dMB ", $1, int($2 / 1024)}' /proc/meminfo
    printf '\n'
    sleep 30
  done
) >>"$ROOT/logs/mem.log" 2>&1 &
MON=$!

"$PY" "$ROOT/code/train_lora.py" \
  --model "$MODEL" \
  --train "$DATA_DIR/train.jsonl" \
  --eval "$DATA_DIR/eval.jsonl" \
  --output "$OUTPUT" \
  --epochs 2 \
  --batch 1 \
  --grad-accum 16 \
  --max-seq "$MAX_SEQ" \
  --logging-steps 5 \
  --save-steps 10 \
  --resume
STATUS=$?

kill "$MON" 2>/dev/null
exit "$STATUS"
