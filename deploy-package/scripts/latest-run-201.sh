set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== latest run stages =="
docker compose exec -T postgres psql -U hanson -d hanson -c "select s.stage, round(extract(epoch from (s.finished_at - s.started_at))::numeric,1) as secs from run_stages s where s.run_id = (select id from runs order by created_at desc limit 1) order by secs desc;"
echo "== latest run doc/status =="
docker compose exec -T postgres psql -U hanson -d hanson -c "select r.id, r.status, r.stage, d.filename, r.created_at from runs r join documents d on d.id=r.document_id order by r.created_at desc limit 3;"
