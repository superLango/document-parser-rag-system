#!/bin/bash
# 测试内网 LLM：连通性检查 + 触发 GB-T1220 抽取（完整产品流程）
# 用法：bash scripts/test_intranet_extract.sh
set -e

BASE="http://127.0.0.1:8000/api/v1"
KB="25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
DOC="09a79bb1-1c17-44bc-bb02-57eab2e25580"   # GB-T1220-2007 不锈钢棒
OUT="/home/grainuser/hansonDoc_RAG/qa/evaluation/results/gb1220_intranet_platform"
mkdir -p "$OUT"
LOG="$OUT/run_log.txt"
# 全部输出同时写入日志文件（终端也显示）
exec > >(tee "$LOG") 2>&1

echo "===== 1) 登录 ====="
TOKEN=$(curl -s -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
echo "token 获取成功"

echo "===== 2) 测试内网 LLM 连通 ====="
curl -s -X POST "$BASE/kb/$KB/resources/llm/test" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"api_base":"http://192.168.0.65:31510/v1","model":"qwen3.5","api_key":"auozora"}'
echo

echo "===== 3) 触发 GB-T1220 抽取 ====="
T0=$(date +%s)
curl -s -X POST "$BASE/kb/$KB/extraction/$DOC" -H "Authorization: Bearer $TOKEN" | head -c 300
echo

echo "===== 4) 轮询抽取状态（每 10s，最长 40 分钟）====="
LAST=""
for i in $(seq 1 240); do
    sleep 10
    RESP=$(curl -s "$BASE/kb/$KB/extraction/$DOC/status" -H "Authorization: Bearer $TOKEN")
    STATUS=$(echo "$RESP" | python3 -c 'import sys,json;d=json.load(sys.stdin)["data"];print(d.get("status"),d.get("progress"),str(d.get("error"))[:120])' 2>/dev/null || echo "解析失败")
    if [ "$STATUS" != "$LAST" ]; then
        echo "[$(date +%H:%M:%S)] $STATUS"
        LAST="$STATUS"
    fi
    if echo "$STATUS" | grep -qE '^(completed|failed)'; then
        break
    fi
done
T1=$(date +%s)
echo "===== 5) 获取结果并保存 ====="
curl -s "$BASE/kb/$KB/extraction/$DOC/result" -H "Authorization: Bearer $TOKEN" > "$OUT/run.json"
echo "结果已保存: $OUT/run.json"
echo "总耗时: $((T1-T0))s"
python3 - <<PY
import json
d = json.load(open('$OUT/run.json'))
print('status:', d.get('status'))
if d.get('status') == 'completed':
    s = d.get('summary', {})
    print('total_records:', s.get('total_records'), '| kept_cat:', s.get('kept_categories'))
    for c in d.get('categories') or []:
        print('  ', c.get('feature'), 'records=', len(c.get('records') or []), 'rejected=', len(c.get('rejected') or []))
else:
    print('error:', str(d.get('error'))[:400])
PY
