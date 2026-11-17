set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose exec -T agent python - <<'PY'
import asyncio, time, uuid
import httpx

async def time_call(tag, payload):
    t = time.monotonic()
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post("http://127.0.0.1:8003/internal/agent:run", json=payload)
        print("%s status=%s %.2fs" % (tag, r.status_code, time.monotonic() - t))

def payload(role):
    return {
        "task_id": f"probe-{uuid.uuid4().hex[:8]}",
        "trace_id": "probe",
        "role": role,
        "objective": "只回复一句话。",
        "inputs": {"facts": [{"content": "测试", "immutable": True}]},
        "output_schema": {"type": "object", "properties": {"findings": {"type": "array"}}},
        "tools": [],
        "budget": {"max_steps": 2, "max_tool_calls": 0, "max_tokens": 256, "wall_time_seconds": 300},
    }

async def main():
    await time_call("review_empty_1", payload("review"))
    await time_call("review_empty_2", payload("review"))
    await time_call("generic_empty", payload("generic"))

asyncio.run(main())
PY
echo "== agent logs for probes =="
docker compose logs --timestamps --tail 40 agent 2>&1 | grep -E 'agent%3Arun|agent:run' | tail -6 | cut -c1-160
