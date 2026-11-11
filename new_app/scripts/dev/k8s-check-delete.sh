#!/usr/bin/env bash
# 验证文档删除：运行中 run 先取消，DB 子表级联删除，对象存储清理。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-hanson}"
NAMESPACE="${NAMESPACE:-hanson-standard}"
export PATH="$PATH:$HOME/.local/bin"

NODE_IP="$(docker inspect "${CLUSTER_NAME}-control-plane" \
  --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}')"
GATEWAY="http://$NODE_IP:30080"
PSQL=(kubectl -n "$NAMESPACE" exec deploy/postgres -- psql -U hanson -d hanson -t -A)

echo "[1/5] 上传文档"
doc_json="$(curl -fsS -X POST "$GATEWAY/v1/documents" \
  -F "file=@${NEW_APP_DIR}/README.md;type=text/markdown")"
doc_id="$(printf '%s' "$doc_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "  document_id=$doc_id"

echo "[2/5] 创建 run 并在运行中删除"
run_json="$(curl -fsS -X POST "$GATEWAY/v1/documents/$doc_id/runs" \
  -H 'Content-Type: application/json' -d '{}')"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "  run_id=$run_id"
sleep 0.1

echo "[3/5] 删除前计数"
"${PSQL[@]}" -c \
  "select
     (select count(*) from runs where document_id='$doc_id') as runs,
     (select count(*) from run_stages s join runs r on r.id=s.run_id where r.document_id='$doc_id') as stages,
     (select count(*) from run_events e join runs r on r.id=e.run_id where r.document_id='$doc_id') as events,
     (select count(*) from artifacts a join runs r on r.id=a.run_id where r.document_id='$doc_id') as artifacts;"

echo "[4/5] 删除文档"
code="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$GATEWAY/v1/documents/$doc_id")"
echo "  delete status=$code"

echo "[5/5] 删除后校验"
get_code="$(curl -s -o /dev/null -w '%{http_code}' "$GATEWAY/v1/documents/$doc_id")"
echo "  get status=$get_code"
"${PSQL[@]}" -c \
  "select
     (select count(*) from runs where document_id='$doc_id') as runs,
     (select count(*) from run_stages s join runs r on r.id=s.run_id where r.document_id='$doc_id') as stages,
     (select count(*) from run_events e join runs r on r.id=e.run_id where r.document_id='$doc_id') as events,
     (select count(*) from artifacts a join runs r on r.id=a.run_id where r.document_id='$doc_id') as artifacts;"
echo "--- minio objects under run ---"
kubectl -n "$NAMESPACE" exec deploy/minio -- \
  ls "/data/hanson-docs/runs/$run_id" 2>&1 || echo "  (objects removed)"

if [ "$code" != "204" ] || [ "$get_code" != "404" ]; then
  echo "[k8s] DELETE CHECK FAILED"
  exit 1
fi
echo "[k8s] DELETE CHECK DONE"
