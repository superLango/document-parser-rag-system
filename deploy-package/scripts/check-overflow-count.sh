set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose logs --timestamps --tail 400 agent 2>&1 | grep -E 'ContextOverflow|context overflow' | tail -3 | cut -c1-180
