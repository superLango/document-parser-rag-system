set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== new stack =="
docker compose ps --format '{{.Name}}  {{.Status}}'
echo "== stray sandbox containers =="
docker ps -a --filter 'name=hanson-sandbox-run' --format '{{.Names}} {{.Status}}' | head -5 || true
echo "== old project (stopped, rollback ready) =="
docker ps -a --filter 'name=hanson-doc-parse' --format '{{.Names}} {{.Status}}' | head -10
echo "== ports =="
docker ps --format '{{.Names}} {{.Ports}}' | grep -E '18000|18080'
echo "== db counts =="
docker compose exec -T postgres psql -U hanson -d hanson -t -c "select 'documents='||count(*) from documents union all select 'runs='||count(*) from runs;"
