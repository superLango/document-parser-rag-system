set -u
cd /home/htjiance8/hanson-deploy/deploy-package
RID=$(docker compose exec -T postgres psql -U hanson -d hanson -t -A -c "select id from runs order by created_at desc limit 1;" | tr -d ' \r')
echo "run=$RID"
docker compose exec -T orchestration python - "$RID" <<'PY'
import asyncio, sys
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
            print("%-28s bytes=%d" % (role, len(data)))
        except Exception as exc:
            print("%-28s FAIL %s" % (role, exc))

asyncio.run(main(sys.argv[1]))
PY
