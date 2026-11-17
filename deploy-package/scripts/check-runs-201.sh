set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose exec -T postgres psql -U hanson -d hanson -c "select status, stage, count(*) from runs group by 1,2 order by 1;" 2>&1 | head -12
docker compose exec -T postgres psql -U hanson -d hanson -c "select count(*) as documents from documents;" 2>&1 | head -5
