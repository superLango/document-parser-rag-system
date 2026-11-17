set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== ocr layout-first summary =="
docker compose logs --tail 600 ocr 2>&1 | grep -E 'layout-first document=' | tail -5
echo "== ocr stage timing lines =="
docker compose logs --tail 600 ocr 2>&1 | grep -iE 'duration=|elapsed|took' | tail -8
echo "== agent usage/latency =="
docker compose logs --tail 400 agent 2>&1 | grep -iE 'latency|tokens|endpoint|degraded' | tail -12
