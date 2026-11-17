set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== review_reports columns =="
docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select column_name from information_schema.columns where table_name='review_reports' order by ordinal_position;" | tr '\n' ' '
echo
echo "== latest review report =="
docker compose exec -T postgres psql -U hanson -d hanson -x -c "select * from review_reports order by id desc limit 1;" 2>&1 | head -25
echo "== latest run event types =="
docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select event_type from run_events where run_id=(select id from runs order by created_at desc limit 1) order by sequence;" | tr '\n' ' '
echo
