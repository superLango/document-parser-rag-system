set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== latest run =="
docker compose exec -T postgres psql -U hanson -d hanson -c "select r.id, r.status, r.stage, d.filename, r.created_at from runs r join documents d on d.id=r.document_id order by r.created_at desc limit 3;"
echo "== review degraded evidence =="
docker compose logs --timestamps --tail 200 review 2>&1 | grep -iE 'degraded|unavailable|error' | tail -5 | cut -c1-200
docker compose logs --timestamps --tail 300 agent 2>&1 | grep -iE 'ContextOverflow|overflow' | tail -4 | cut -c1-200
echo "== review report artifact stats =="
docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select a.storage_key from artifacts a join runs r on r.id=a.run_id where a.role='review' order by a.created_at desc limit 1;"
echo "== documents =="
docker compose exec -T postgres psql -U hanson -d hanson -c "select count(*) as documents from documents;"
