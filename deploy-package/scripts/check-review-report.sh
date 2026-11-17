set -u
cd /home/htjiance8/hanson-deploy/deploy-package
RID=$(docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select id from runs order by created_at desc limit 1;")
echo "run=$RID"
echo "== review reports =="
docker compose exec -T postgres psql -U hanson -d hanson -c "select status, degraded, stats from review_reports where run_id='$RID';" 2>&1 | head -8
echo "== review events =="
docker compose exec -T postgres psql -U hanson -d hanson -c "select event_type, payload from run_events where run_id='$RID' order by sequence desc limit 6;" 2>&1 | head -20
