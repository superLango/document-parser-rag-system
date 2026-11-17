set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose exec -T agent python - <<'PY'
import asyncio, json, time, uuid
from hanson_contracts import AgentTask, AgentBudget
from services.agent.agents.review import REVIEW_SCHEMA
from services.agent.config import Settings
from services.agent.runtime import AgentRuntime

async def main():
    rt = AgentRuntime(Settings())
    t = time.monotonic(); prompt = rt.prompts.resolve("review", None)
    print("prompt %.3fs chars=%d" % (time.monotonic()-t, len(prompt.text)))
    task = AgentTask(
        task_id=f"probe-{uuid.uuid4().hex[:8]}", trace_id="probe", role="review",
        objective="Review extracted records against their evidence.",
        inputs={"records": [], "evidence": [], "tables": [], "deterministic_findings": []},
        output_schema=REVIEW_SCHEMA, tools=[],
        budget=AgentBudget(max_steps=2, max_tool_calls=0, max_tokens=64000, wall_time_seconds=300),
    )
    t = time.monotonic(); session = rt.sessions.create(task, prompt.prompt_id, prompt.sha256)
    print("session %.3fs" % (time.monotonic()-t))
    compact = {"records": [], "evidence": [], "tables": [], "deterministic_findings": []}
    t = time.monotonic()
    state = await rt.context_manager.assemble(prompt.text, task.objective,
        facts=[{"content": json.dumps(compact, ensure_ascii=False), "immutable": True}], schema=REVIEW_SCHEMA)
    print("assemble %.3fs tokens=%d" % (time.monotonic()-t, state.tokens))
    messages = rt.context_manager.render_messages(state, instruction="Return only the ReviewReport findings JSON object.")
    t = time.monotonic(); value, response = await rt.gateway.chat_json(messages)
    print("chat_json %.3fs prompt_tokens=%d completion_tokens=%d" % (
        time.monotonic()-t, response.prompt_tokens, response.completion_tokens))
    t = time.monotonic(); rt.sessions.save(session, task); print("save %.3fs" % (time.monotonic()-t))

asyncio.run(main())
PY
