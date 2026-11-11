#!/usr/bin/env bash
# 验证阶段失败重试：注入一次 ocr 失败，确认重试后成功并写入 run.stage.failed 事件。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
NAMESPACE="${NAMESPACE:-hanson-standard}"
export PATH="$PATH:$HOME/.local/bin"

PSQL=(kubectl -n "$NAMESPACE" exec deploy/postgres -- psql -U hanson -d hanson -t -A -F '|')

echo "[1/5] 注入 ocr 失败一次"
kubectl -n "$NAMESPACE" patch configmap app-config --type merge \
  -p '{"data":{"MOCK_FAIL_STAGE":"ocr","MOCK_FAIL_TIMES":"1"}}' >/dev/null
kubectl -n "$NAMESPACE" rollout restart deployment/orchestration >/dev/null
kubectl -n "$NAMESPACE" rollout status deployment/orchestration --timeout=180s

echo "[2/5] 运行主链路"
output="$(bash "$SCRIPT_DIR/k8s-e2e.sh")"
printf '%s\n' "$output" | head -8
run_id="$(printf '%s\n' "$output" | grep -o 'run_id=[0-9a-f-]*' | head -1 | cut -d= -f2)"

echo "[3/5] 阶段状态"
"${PSQL[@]}" -c "select stage,status,duration_ms from run_stages where run_id='$run_id' order by stage;"

echo "[4/5] 事件序列"
"${PSQL[@]}" -c \
  "select sequence,type,payload->>'attempt',payload->>'will_retry' \
   from run_events where run_id='$run_id' order by sequence;"

echo "[5/5] 恢复配置"
kubectl apply -k "$NEW_APP_DIR/deploy/k8s/base" >/dev/null
kubectl -n "$NAMESPACE" rollout restart deployment/orchestration >/dev/null
kubectl -n "$NAMESPACE" rollout status deployment/orchestration --timeout=180s
echo "[k8s] RETRY CHECK DONE"
