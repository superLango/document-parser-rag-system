set -u
cd /home/htjiance8/hanson-deploy/deploy-package
RID=$(docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select id from runs order by created_at desc limit 1;" < /dev/null)
RID=$(printf '%s' "$RID" | tr -d ' \r')
echo "run=$RID"
docker compose cp scripts/measure_review.py orchestration:/tmp/measure_review.py < /dev/null
docker compose exec -T -e PYTHONPATH=/app:/app/packages/contracts/src:/app/packages/domain/src:/app/packages/observability/src orchestration python /tmp/measure_review.py "$RID" < /dev/null
