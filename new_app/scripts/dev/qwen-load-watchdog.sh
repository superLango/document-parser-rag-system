#!/usr/bin/env bash
# Run on the model server: kill the loading model process if MemAvailable drops
# below the floor. This protects shared services (GLM-OCR/Layout) and the host.
set -uo pipefail

PID="${1:?usage: qwen-load-watchdog.sh <pid> [floor_mb] [log] [ready_url]}"
FLOOR_MB="${2:-8192}"
LOG="${3:-/home/grainuser/hansonDoc_RAG/logs/qwen-load-watchdog.log}"
READY_URL="${4:-}"

while kill -0 "$PID" 2>/dev/null; do
  if [ -n "$READY_URL" ] && curl -fsS --max-time 2 "$READY_URL" >/dev/null 2>&1; then
    echo "$(date '+%F %T') pid=$PID READY; watchdog exiting" >> "$LOG"
    exit 0
  fi
  avail_kb="$(awk '/MemAvailable/{print $2}' /proc/meminfo)"
  avail_mb=$((avail_kb / 1024))
  echo "$(date '+%F %T') pid=$PID available_mb=$avail_mb floor_mb=$FLOOR_MB" >> "$LOG"
  if [ "$avail_mb" -lt "$FLOOR_MB" ]; then
    echo "$(date '+%F %T') TRIPPED: killing $PID" >> "$LOG"
    kill -9 "$PID" 2>/dev/null || true
    exit 2
  fi
  sleep 2
done
echo "$(date '+%F %T') pid=$PID exited" >> "$LOG"
