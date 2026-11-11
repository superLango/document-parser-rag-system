#!/usr/bin/env bash
# 注册中心冒烟：列表、resolve、版本详情与匹配。
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:18005}"

echo "[1/4] 配方列表"
curl -fsS "$BASE_URL/internal/recipes" | python3 -c '
import json, sys
recipes = json.load(sys.stdin)
print("  recipes =", len(recipes))
for item in recipes:
    print("  ", item["recipe_id"], item["channels"])
'

echo "[2/4] resolve stable"
curl -fsS -X POST "$BASE_URL/internal/recipes/resolve" \
  -H 'Content-Type: application/json' \
  -d '{"recipe_id":"mechanical_properties_v1","channel":"stable"}'
echo

echo "[3/4] 版本详情"
curl -fsS "$BASE_URL/internal/recipes/mechanical_properties_v1" | head -c 300
echo

echo "[4/4] matcher"
curl -fsS -X POST "$BASE_URL/internal/recipes/match" \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{"table": {"table_id": "T1", "page_no": 1, "profile": "mechanical_properties", "orientation": "grade_rows", "n_cols": 3, "header_rows": 1, "header_paths": [["牌号"], ["抗拉强度 Rm/MPa"], ["断后伸长率 A/%"]], "rows": [["牌号", "抗拉强度 Rm/MPa", "断后伸长率 A/%"], ["Q355B", "470", "22"]], "blocks": []}}
JSON
echo
echo "[recipe] CHECK DONE"
