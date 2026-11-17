set -u
cd /home/htjiance8/hanson-deploy/deploy-package
set -a; . ./.env; set +a
GW="http://127.0.0.1:${GATEWAY_PORT}"
for id in $(curl -s "$GW/v1/documents" | python3 -c 'import json,sys;d=json.load(sys.stdin);it=d if isinstance(d,list) else (d.get("data") or []);print("\n".join(x["id"] for x in it))'); do
  printf 'delete %s -> ' "$id"; curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "$GW/v1/documents/$id"
done
echo "== counts =="
docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select 'documents='||count(*) from documents union all select 'runs='||count(*) from runs union all select 'integration='||count(*) from integration_tasks;"
