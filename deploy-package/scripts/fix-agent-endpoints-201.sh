set -eu
PKG=/home/htjiance8/hanson-deploy/deploy-package
cd "$PKG"
echo "[$(date +%T)] recreate agent"
docker compose up -d agent
sleep 5
echo "== effective endpoints in agent =="
docker compose exec -T agent python -c "
from services.agent.config import settings
print([ (e.name, e.base_url) for e in settings.endpoints() ])
print('context_window=', settings.context_window, 'tokenizer=', settings.tokenizer_mode)
"
echo "== tokenizer latency now =="
docker compose exec -T agent python -c "
import asyncio,time
from services.agent.config import settings
from services.agent.context.tokenizer import build_tokenizer
async def m():
    tok=build_tokenizer(settings.tokenizer_mode, settings.endpoints()[0].base_url, settings.model)
    t=time.monotonic(); n=await tok.count('Review extracted records against their evidence.'); print('tokens=%d %.3fs'%(n,time.monotonic()-t))
asyncio.run(m())
"
