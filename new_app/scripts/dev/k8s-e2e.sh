#!/usr/bin/env bash
# 通过 kind NodePort 走通上传 -> run -> 结果，验证 K8s 内的 M1 主链路。
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-hanson}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
FIXTURE="${1:-${REPO_ROOT}/README.md}"

export PATH="$PATH:$HOME/.local/bin"

NODE_IP="$(docker inspect "${CLUSTER_NAME}-control-plane" \
  --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}')"
GATEWAY="http://$NODE_IP:30080"
echo "gateway: $GATEWAY"

echo "[1/4] 上传文档"
doc_json="$(curl -fsS -X POST "$GATEWAY/v1/documents" \
  -F "file=@${FIXTURE};type=text/markdown")"
doc_id="$(printf '%s' "$doc_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "  document_id=$doc_id"

echo "[2/4] 创建 run"
run_json="$(curl -fsS -X POST "$GATEWAY/v1/documents/$doc_id/runs" \
  -H 'Content-Type: application/json' -d '{}')"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "  run_id=$run_id"

echo "[3/4] 轮询状态"
status=""
for i in $(seq 1 60); do
  status="$(curl -fsS "$GATEWAY/v1/runs/$run_id" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "  [$i] $status"
  case "$status" in
    STRUCTURED_READY | FAILED | CANCELLED) break ;;
  esac
  sleep 1
done

echo "[4/4] 时间线与结果"
curl -fsS "$GATEWAY/v1/runs/$run_id/timeline" && echo
curl -fsS "$GATEWAY/v1/runs/$run_id/result" && echo

if [ "$status" != "STRUCTURED_READY" ]; then
  echo "[k8s] E2E FAILED: $status"
  exit 1
fi
echo "[k8s] E2E DONE"
