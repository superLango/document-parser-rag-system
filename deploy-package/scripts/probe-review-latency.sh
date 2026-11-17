set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== review logs =="
docker compose logs --timestamps --tail 80 review 2>&1 | tail -25 | cut -c1-200
echo "== orchestration recent agent/review calls =="
docker compose logs --timestamps --tail 300 orchestration 2>&1 | grep -E 'agent:run|internal/review|stage .*(start|done|finished)|routing|review' | tail -20 | cut -c1-200
echo "== agent harness log lines =="
docker compose logs --tail 300 agent 2>&1 | grep -viE 'healthz|GET /' | grep -E 'INFO|WARNING|ERROR|INFO:' | tail -15 | cut -c1-200
