set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose exec -T agent python - <<'PY'
import asyncio, json, time, uuid
import httpx
from services.agent.config import settings
from services.agent.context.tokenizer import build_tokenizer

async def main():
    tok = build_tokenizer(settings.tokenizer_mode, settings.base_url_tertiary, settings.model)
    text = ("牌号 抗拉强度 屈服强度 伸长率 断面收缩率 冲击功 " * 3000)
    t = time.monotonic(); n = await tok.count(text); print("tokenize_600k_chars tokens=%d %.2fs" % (n, time.monotonic()-t))

    payload = {
        "task_id": f"probe-{uuid.uuid4().hex[:8]}",
        "trace_id": "probe",
        "role": "review",
        "objective": "Review extracted records against their evidence.",
        "inputs": {"records": [], "evidence": [], "tables": [], "deterministic_findings": []},
        "output_schema": {"type": "object", "properties": {"findings": {"type": "array"}}},
        "tools": [],
        "budget": {"max_steps": 2, "max_tool_calls": 0, "max_tokens": 64000, "wall_time_seconds": 300},
    }
    t = time.monotonic()
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post("http://127.0.0.1:8003/internal/agent:run", json=payload)
        print("agent_empty_payload status=%s %.2fs" % (r.status_code, time.monotonic()-t))

asyncio.run(main())
PY
