set -eu
BASE="${BASE:-/home/htjiance8/hanson-deploy}"
PKG="$BASE/deploy-package"
cd "$PKG"

if [ -f images/hanson-runtime-images-arm64.tar ]; then
  echo "[$(date +%T)] docker load arm64 images"
  docker load -i images/hanson-runtime-images-arm64.tar | tail -3
fi

if [ ! -f .env ]; then
  echo "[$(date +%T)] init .env from .env.ai01"
  cp .env.ai01 .env
fi

echo "[$(date +%T)] docker compose up -d"
docker compose up -d

echo "[$(date +%T)] wait for health"
for i in $(seq 1 60); do
  unhealthy=$(docker compose ps --format '{{.Name}} {{.Health}}' | grep -vc 'healthy' || true)
  echo "  attempt $i unhealthy=$unhealthy"
  [ "$unhealthy" = "0" ] && break
  sleep 10
done
docker compose ps --format '{{.Name}}\t{{.Status}}'
