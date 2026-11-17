set -eu
OLD=/home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra/docker
PKG=/home/htjiance8/hanson-deploy/deploy-package

cd "$OLD"
echo "[$(date +%T)] stop old project (containers kept for rollback)"
docker compose -p hanson-doc-parse -f compose.yaml -f compose.ai01.yaml stop
docker compose -p hanson-doc-parse-selfheal -f compose.selfheal.ai01.yaml stop

cd "$PKG"
echo "[$(date +%T)] switch new stack to production ports"
sed -i 's/^GATEWAY_PORT=.*/GATEWAY_PORT=18000/' .env
sed -i 's/^WEB_PORT=.*/WEB_PORT=18080/' .env
docker compose up -d

echo "[$(date +%T)] verify ports"
for i in $(seq 1 30); do
  g=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/healthz || true)
  w=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/ || true)
  echo "  gateway=$g web=$w"
  [ "$g" = "200" ] && [ "$w" = "200" ] && break
  sleep 5
done
ss -ltn | grep -E ':(18000|18080)\b'
