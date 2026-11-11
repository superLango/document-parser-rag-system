#!/usr/bin/env bash
# Probe the model server's OpenAI-compatible endpoints from WSL.
# Usage: bash model-probe.sh [host]
set -uo pipefail

HOST="${1:-192.168.1.35}"
PORTS=(9977 9978 9979 9989 9990 9991 8000 8080)

for port in "${PORTS[@]}"; do
  code="$(curl -s -o "/tmp/model-probe-$port.json" -w '%{http_code}' -m 2 \
    "http://$HOST:$port/v1/models" 2>/dev/null || true)"
  echo "port $port -> ${code:-000}"
  if [ "$code" = "200" ]; then
    head -c 600 "/tmp/model-probe-$port.json"
    echo
  fi
done

echo "--- health ---"
for port in 9977 9978 9991; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://$HOST:$port/health" 2>/dev/null || true)"
  echo "health $port -> ${code:-000}"
done
