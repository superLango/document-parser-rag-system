#!/usr/bin/env bash
# Wait for the Qwen 35B endpoint on the model server.
set -uo pipefail

HOST="${1:-192.168.1.35}"
PORT="${2:-9988}"
for i in $(seq 1 24); do
  body="$(curl -s -m 3 "http://$HOST:$PORT/v1/models" 2>/dev/null || true)"
  if printf '%s' "$body" | grep -q '"id"'; then
    echo "ready: $body"
    exit 0
  fi
  echo "[$i] Qwen loading..."
  sleep 10
done
echo "Qwen not ready after 240s"
exit 1
