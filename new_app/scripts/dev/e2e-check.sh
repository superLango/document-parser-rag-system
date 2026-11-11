#!/usr/bin/env bash
# Compose E2E: create a run for an uploaded document and wait for STRUCTURED_READY.
set -euo pipefail

GATEWAY="${GATEWAY:-http://localhost:18000}"
DOC="${1:?usage: e2e-check.sh <document_id>}"

run_json="$(curl -fsS -X POST "$GATEWAY/v1/documents/$DOC/runs" \
  -H 'Content-Type: application/json' -d '{}')"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "run_id=$run_id"

status=""
for i in $(seq 1 120); do
  status="$(curl -fsS "$GATEWAY/v1/runs/$run_id" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "[$i] $status"
  case "$status" in
    STRUCTURED_READY | FAILED | CANCELLED) break ;;
  esac
  sleep 1
done

echo "--- timeline ---"
curl -fsS "$GATEWAY/v1/runs/$run_id/timeline" && echo
echo "--- result ---"
curl -fsS "$GATEWAY/v1/runs/$run_id/result" && echo

[ "$status" = "STRUCTURED_READY" ]
