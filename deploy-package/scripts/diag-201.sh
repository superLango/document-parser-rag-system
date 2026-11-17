set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose ps --format '{{.Name}}\t{{.Status}}'
echo "== unhealthy detail =="
for c in $(docker compose ps -q); do
  s=$(docker inspect -f '{{.Name}} {{.State.Health.Status}}' "$c" 2>/dev/null)
  case "$s" in *unhealthy*) echo "$s"; docker logs --tail 25 "$c" 2>&1 | tail -25;; esac
done
