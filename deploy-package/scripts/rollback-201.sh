set -eu
# 回滚：停新栈，恢复老项目（容器在上一步只是 stop，可直接 start）
OLD=/home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra/docker
PKG=/home/htjiance8/hanson-deploy/deploy-package

cd "$PKG"
echo "[$(date +%T)] stop new stack"
docker compose stop

cd "$OLD"
echo "[$(date +%T)] start old project"
docker compose -p hanson-doc-parse -f compose.yaml -f compose.ai01.yaml start
docker compose -p hanson-doc-parse-selfheal -f compose.selfheal.ai01.yaml start

echo "[$(date +%T)] verify"
for p in 18000 18080; do printf 'port %s -> ' "$p"; curl -s -m 4 -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$p/" || true; done
