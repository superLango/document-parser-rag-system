set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== runs =="
docker compose exec -T postgres psql -U hanson -d hanson -t -c "select status||'/'||stage from runs order by created_at desc limit 3;"
echo "== documents =="
docker compose exec -T postgres psql -U hanson -d hanson -t -c "select count(*) from documents;"
echo "== integration tasks =="
docker compose exec -T postgres psql -U hanson -d hanson -t -c "select task_id||' '||status from integration_tasks order by created_at desc limit 2;" 2>/dev/null
DOC=$(docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select id from documents order by created_at desc limit 1;")
echo "== original file (doc=$DOC) =="
curl -s -m 10 -o /dev/null -w 'via-gateway=%{http_code} type=%{content_type} size=%{size_download}\n' "http://127.0.0.1:18000/v1/documents/$DOC/file"
curl -s -m 10 -o /dev/null -w 'via-web=%{http_code} type=%{content_type} size=%{size_download}\n' "http://127.0.0.1:18081/v1/documents/$DOC/file"
