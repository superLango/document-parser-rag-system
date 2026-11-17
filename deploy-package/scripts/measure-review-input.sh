set -u
cd /home/htjiance8/hanson-deploy/deploy-package
set -a; . ./.env; set +a
GW="http://127.0.0.1:${GATEWAY_PORT}"
U1=$(python3 -c 'import uuid;print(uuid.uuid4())'); U2=$(python3 -c 'import uuid;print(uuid.uuid4())')
RESP=$(curl -sS -m 120 -X POST "$GW/api/v1/integration/upload?kb_id=$U1&prompt_id=$U2" -F "file=@samples/smoke.pdf;type=application/pdf")
DOC=$(printf '%s' "$RESP" | python3 -c 'import json,sys;d=json.load(sys.stdin).get("data") or {};print(d.get("document_id",""))')
echo "doc=$DOC"
for i in $(seq 1 100); do
  ST=$(docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select status from runs where document_id='$DOC' order by created_at desc limit 1;" | tr -d ' \r')
  case "$ST" in *HUMAN_REVIEW*|*STRUCTURED_READY*|*FAILED*) break;; esac
  sleep 3
done
RID=$(docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select id from runs where document_id='$DOC' order by created_at desc limit 1;" | tr -d ' \r')
echo "run=$RID status=$ST"
docker compose exec -T orchestration python - "$RID" <<'PY'
import asyncio, json, sys
from sqlalchemy import select
from services.orchestration.db import SessionLocal
from services.orchestration.models import Artifact
from services.orchestration.workflow import get_store

async def main(run_id):
    async with SessionLocal() as s:
        rows = (await s.execute(select(Artifact).where(Artifact.run_id == run_id))).scalars().all()
        meta = [(a.role, a.storage_key) for a in rows]
    store = get_store()
    for role, key in meta:
        try:
            data = await store.get_bytes(key)
        except Exception as exc:
            print("%-24s key=%s FAIL %s" % (role, key, exc)); continue
        print("%-24s bytes=%d" % (role, len(data)))

asyncio.run(main(sys.argv[1]))
PY
echo "DOC=$DOC" > /tmp/measure_doc.txt
echo "RID=$RID" >> /tmp/measure_doc.txt
