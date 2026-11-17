set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose exec -T agent python - <<'PY'
import asyncio, json, time
from services.agent.config import Settings
from services.agent.context.tokenizer import build_tokenizer

async def main():
    s = Settings()
    print("mode=%s endpoints=%s" % (s.tokenizer_mode, s.endpoints()))
    tok = build_tokenizer(s.tokenizer_mode, base_url=s.endpoints()[0].base_url, model=s.model)
    for tag, text in [
        ("empty", ""),
        ("short", "Review extracted records against their evidence."),
        ("prompt", "x" * 1251),
        ("schema", json.dumps({"type": "object", "properties": {"findings": {"type": "array"}}})),
    ]:
        t = time.monotonic(); n = await tok.count(text)
        print("%s chars=%d tokens=%d %.3fs" % (tag, len(text), n, time.monotonic() - t))

asyncio.run(main())
PY
