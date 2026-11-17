set -u
cd /home/htjiance8/hanson-deploy/deploy-package
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
GW="${GATEWAY_PORT:-18000}"
WEB="${WEB_PORT:-18080}"
echo "== endpoints =="
for p in /healthz /v1/health /api/v1/health /api/v1/documents; do
  printf '%-22s ' "$p"; curl -s -m 8 -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:${GW}${p}"
done
printf '%-22s ' "web /"; curl -s -m 8 -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:${WEB}/"
printf '%-22s ' "web /integration"; curl -s -m 8 -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:${WEB}/integration/task/test"
echo "== model reachability from app container =="
docker compose exec -T api-gateway python -c "
import urllib.request
for name,url in [('glm','http://193.168.2.201:9977/v1/models'),('layout','http://193.168.2.201:9979/health'),('qwen','http://193.168.2.202:9988/v1/models')]:
    try:
        with urllib.request.urlopen(url,timeout=8) as r: print(f'{name}={r.status}')
    except Exception as e: print(f'{name}=FAIL {e}')
"
echo "== containers =="
docker compose ps --format '{{.Name}}\t{{.Status}}'
