#!/usr/bin/env bash
# M8 cutover/rollback drill: a single nginx entry switches between the new and
# old systems, then switches back. Requires the Compose stack, the web preview
# (port 4173) and the legacy stack (web 8080 / api 8000).
set -euo pipefail

CONTAINER="${CONTAINER:-hanson-cutover-drill}"
PORT="${PORT:-18088}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT="$ROOT/docs/reports/M8-cutover-drill.json"
TMP="$(mktemp -d)"
NEW_CONF="$TMP/new.conf"
OLD_CONF="$TMP/old.conf"
ACTIVE="$TMP/active.conf"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

cat >"$NEW_CONF" <<EOF
server {
  listen $PORT;
  location = /v1/health { proxy_pass http://127.0.0.1:18000/v1/health; }
  location /v1/ { proxy_pass http://127.0.0.1:18000/v1/; }
  location / { proxy_pass http://127.0.0.1:4173/; }
}
EOF

cat >"$OLD_CONF" <<EOF
server {
  listen $PORT;
  location = /health { proxy_pass http://127.0.0.1:8000/health; }
  location / { proxy_pass http://127.0.0.1:8080/; }
}
EOF

cp "$NEW_CONF" "$ACTIVE"

echo "[1/6] 预检查"
curl -fsS -m 5 "http://localhost:18000/v1/health" >/dev/null
curl -fsS -m 5 "http://localhost:4173/" >/dev/null
curl -fsS -m 5 "http://localhost:8000/health" >/dev/null
curl -fsS -m 5 "http://localhost:8080/" >/dev/null
echo "  ok new/old entries reachable"

echo "[2/6] 启动双入口代理"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" \
  --network host \
  -v "$ACTIVE:/etc/nginx/conf.d/default.conf:ro" \
  nginx:alpine >/dev/null
for _ in $(seq 1 30); do
  if curl -fsS -m 2 "http://localhost:$PORT/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.3
done

NEW_HEALTH="$(curl -fsS -m 5 "http://localhost:$PORT/v1/health")"
NEW_WEB="$(curl -fsS -m 5 "http://localhost:$PORT/")"
echo "$NEW_HEALTH" | grep -q "api-gateway"
echo "$NEW_WEB" | grep -q "标准拆分平台"
echo "  ok entry routes to new system"

echo "[3/6] 切换到旧系统并计时"
SWITCH_START=$(date +%s%3N)
cp "$OLD_CONF" "$ACTIVE"
docker exec "$CONTAINER" nginx -s reload >/dev/null
ROLLBACK_OK=0
for _ in $(seq 1 50); do
  if curl -fsS -m 2 "http://localhost:$PORT/health" 2>/dev/null | grep -q '"version":"0.1.0"'; then
    ROLLBACK_OK=1
    break
  fi
  sleep 0.1
done
SWITCH_MS=$(( $(date +%s%3N) - SWITCH_START ))
OLD_WEB_CODE="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://localhost:$PORT/")"
echo "  switch_ok=$ROLLBACK_OK switch_ms=$SWITCH_MS old_web=$OLD_WEB_CODE"

echo "[4/6] 回切到新系统并计时"
BACK_START=$(date +%s%3N)
cp "$NEW_CONF" "$ACTIVE"
docker exec "$CONTAINER" nginx -s reload >/dev/null
BACK_OK=0
for _ in $(seq 1 50); do
  if curl -fsS -m 2 "http://localhost:$PORT/v1/health" 2>/dev/null | grep -q "api-gateway"; then
    BACK_OK=1
    break
  fi
  sleep 0.1
done
BACK_MS=$(( $(date +%s%3N) - BACK_START ))
echo "  back_ok=$BACK_OK back_ms=$BACK_MS"

echo "[5/6] 写入报告"
mkdir -p "$(dirname "$REPORT")"
cat >"$REPORT" <<EOF
{
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "entry": "http://localhost:$PORT",
  "new_upstream": {"web": "http://localhost:4173", "api": "http://localhost:18000"},
  "old_upstream": {"web": "http://localhost:8080", "api": "http://localhost:8000"},
  "checks": {
    "new_health": $(printf '%s' "$NEW_HEALTH" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin), ensure_ascii=False))'),
    "switch_to_old_ok": $([ "$ROLLBACK_OK" -eq 1 ] && echo true || echo false),
    "switch_to_old_ms": $SWITCH_MS,
    "old_web_status": $OLD_WEB_CODE,
    "switch_back_new_ok": $([ "$BACK_OK" -eq 1 ] && echo true || echo false),
    "switch_back_new_ms": $BACK_MS
  }
}
EOF

echo "[6/6] 结果"
cat "$REPORT"
if [ "$ROLLBACK_OK" -ne 1 ] || [ "$BACK_OK" -ne 1 ]; then
  echo "drill failed" >&2
  exit 1
fi
echo "drill passed"
