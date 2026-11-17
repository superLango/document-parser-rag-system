set -eu
PKG=/home/htjiance8/hanson-deploy/deploy-package
cd "$PKG"
echo "[$(date +%T)] load app image"
docker load -i images/hanson-app-arm64.tar | tail -2
echo "[$(date +%T)] refresh .env from .env.ai01"
cp .env.ai01 .env
docker compose config >/dev/null
echo "[$(date +%T)] recreate services"
docker compose up -d
for i in $(seq 1 30); do
  bad=$(docker compose ps --format '{{.Name}} {{.Status}}' | grep -vc 'healthy\|Up' || true)
  echo "  attempt $i not_ready=$bad"
  [ "$bad" = "0" ] && break
  sleep 8
done
docker compose ps --format '{{.Name}}  {{.Status}}'
echo "[$(date +%T)] verify env in ocr container"
docker compose exec -T ocr sh -c 'echo GLM_OCR_MAX_CONCURRENCY=$GLM_OCR_MAX_CONCURRENCY LAYOUT_BLOCK_CONCURRENCY=$LAYOUT_BLOCK_CONCURRENCY'
