set -u
cd /home/htjiance8/hanson-deploy/deploy-package
set -a; . ./.env; set +a
GW="http://127.0.0.1:${GATEWAY_PORT}"
U1=$(python3 -c 'import uuid;print(uuid.uuid4())')
U2=$(python3 -c 'import uuid;print(uuid.uuid4())')
RESP=$(curl -sS -m 120 -X POST "$GW/api/v1/integration/upload?kb_id=$U1&prompt_id=$U2" -F "file=@samples/smoke.pdf;type=application/pdf")
TASK=$(printf '%s' "$RESP" | python3 -c 'import json,sys;d=json.load(sys.stdin).get("data") or {};print(d.get("task_id",""))')
DOC=$(printf '%s' "$RESP" | python3 -c 'import json,sys;d=json.load(sys.stdin).get("data") or {};print(d.get("document_id",""))')
echo "task=$TASK doc=$DOC"
START=$(date +%s)
for i in $(seq 1 200); do
  ST=$(docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select status||'/'||stage from runs where document_id='$DOC' order by created_at desc limit 1;" | tr -d ' \r')
  case "$ST" in
    *HUMAN_REVIEW*|*STRUCTURED_READY*|*FAILED*|*CANCELLED*) break;;
  esac
  sleep 3
done
echo "elapsed=$(( $(date +%s) - START ))s state=$ST"
echo "== stage durations (secs) =="
docker compose exec -T postgres psql -U hanson -d hanson -c "select s.stage, round(extract(epoch from (s.finished_at - s.started_at))::numeric,1) as secs from run_stages s join runs r on r.id=s.run_id where r.document_id='$DOC' order by secs desc;"
echo "== records =="
curl -s -m 30 "$GW/api/v1/integration/result?task_id=$TASK" | python3 -c 'import json,sys;d=json.load(sys.stdin).get("data") or {};print("records=%d"%len(d.get("rows") or []))'
curl -s -o /dev/null -w 'cleanup=%{http_code}\n' -X DELETE "$GW/v1/documents/$DOC"
