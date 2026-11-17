set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose exec -T postgres psql -U hanson -d hanson -A -F'|' -c "select id, status, degraded, stats::text from review_reports order by id desc limit 2;" 2>&1 | cut -c1-400
