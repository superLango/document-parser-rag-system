set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "start"
docker compose exec -T orchestration python -c "print('orch-python-ok')" 2>&1 | head -5
echo "rc=$?"
RID=$(docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select id from runs order by created_at desc limit 1;")
echo "rid=$RID"
