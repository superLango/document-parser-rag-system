#!/usr/bin/env bash
set -euo pipefail
export PATH="$PATH:$HOME/.local/bin"
RUN_ID="${1:-651a421a-0b94-42b9-aced-86c131adb0e7}"

echo "--- runs ---"
kubectl -n hanson-standard exec deploy/postgres -- \
  psql -U hanson -d hanson -t -A -F '|' -c \
  "select id,status,stage,created_at,started_at,finished_at from runs where id='$RUN_ID';"

echo "--- run_stages ---"
kubectl -n hanson-standard exec deploy/postgres -- \
  psql -U hanson -d hanson -t -A -F '|' -c \
  "select stage,status,started_at,finished_at,duration_ms from run_stages where run_id='$RUN_ID' order by stage;"

echo "--- run_events ---"
kubectl -n hanson-standard exec deploy/postgres -- \
  psql -U hanson -d hanson -t -A -F '|' -c \
  "select sequence,type,stage,occurred_at from run_events where run_id='$RUN_ID' order by sequence;"

echo "--- pod time ---"
kubectl -n hanson-standard exec deploy/orchestration -- date -u
kubectl -n hanson-standard exec deploy/postgres -- date -u
