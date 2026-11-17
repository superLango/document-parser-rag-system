set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose exec -T postgres psql -U hanson -d hanson -c "\dt" | head -30
echo "== latest review row =="
docker compose exec -T postgres psql -U hanson -d hanson -c "select run_id, status, degraded from review_reports order by created_at desc limit 2;" 2>&1 | head -10
