from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hanson_contracts import (
    AgentBudget,
    AgentResumeRequest,
    AgentTask,
    ModelResponse,
)

from services.agent.context import ContextManager, HeuristicTokenizer
from services.agent.harness import AgentHarness
from services.agent.model_gateway import ModelUnavailable
from services.agent.prompts import PromptLibrary
from services.agent.session import SessionStore
from services.agent.tools import Tool, ToolRegistry


def _response() -> ModelResponse:
    return ModelResponse(
        content="{}",
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=5,
        endpoint="fake",
        model="fake",
        latency_ms=1,
    )


class FakeGateway:
    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls = 0

    async def chat_json(self, messages, **kwargs):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item, _response()


async def echo(arguments: dict, context: dict) -> dict:
    return {"echo": arguments}


def _harness(tmp_path: Path, gateway: Any, max_steps: int = 4) -> tuple[AgentHarness, SessionStore]:
    sessions = SessionStore(tmp_path / "sessions.db")
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="echo arguments",
            input_schema={"type": "object"},
            handler=echo,
        )
    )
    tokenizer = HeuristicTokenizer()
    harness = AgentHarness(
        gateway,
        ContextManager(tokenizer, max_tokens=2000),
        registry,
        sessions,
        PromptLibrary(),
    )
    return harness, sessions


def _task(max_steps: int = 4) -> AgentTask:
    return AgentTask(
        task_id="t1",
        trace_id="trace-1",
        role="repair",
        objective="run a tool and finish",
        inputs={"facts": [{"content": "fact one", "immutable": True}]},
        output_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        tools=["echo"],
        budget=AgentBudget(max_steps=max_steps, max_tool_calls=4, max_tokens=2000),
    )


def test_harness_tool_loop_and_final(tmp_path: Path) -> None:
    async def scenario() -> None:
        gateway = FakeGateway(
            [
                ({"action": "tool", "tool": "echo", "arguments": {"x": 1}}),
                ({"action": "final", "output": {"answer": "done"}}),
            ]
        )
        harness, sessions = _harness(tmp_path, gateway)
        try:
            result = await harness.run(_task())
            assert result.status == "completed"
            assert result.output["answer"] == "done"
            assert result.usage.tool_calls == 1
            session = sessions.get(result.session_id)
            assert session is not None
            assert session.status == "completed"
            assert len(session.tool_calls) == 1
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_harness_resume_preserves_tool_state(tmp_path: Path) -> None:
    async def scenario() -> None:
        gateway = FakeGateway(
            [
                ({"action": "tool", "tool": "echo", "arguments": {"x": 1}}),
                ModelUnavailable("down"),
            ]
        )
        harness, sessions = _harness(tmp_path, gateway)
        try:
            first = await harness.run(_task())
            assert first.status == "failed"
            assert first.error_code == "AGENT_MODEL_UNAVAILABLE"

            resumed_gateway = FakeGateway(
                [{"action": "final", "output": {"answer": "resumed"}}]
            )
            resumed_harness = AgentHarness(
                resumed_gateway,
                ContextManager(HeuristicTokenizer(), max_tokens=2000),
                harness.tools,
                sessions,
                PromptLibrary(),
            )
            result = await resumed_harness.resume(
                AgentResumeRequest(session_id=first.session_id)
            )
            assert result.status == "completed"
            assert result.output["answer"] == "resumed"
            session = sessions.get(first.session_id)
            assert session is not None
            assert len(session.tool_calls) == 1
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_harness_detects_repeated_tool(tmp_path: Path) -> None:
    async def scenario() -> None:
        action = {"action": "tool", "tool": "echo", "arguments": {"x": 1}}
        gateway = FakeGateway([action, action])
        harness, sessions = _harness(tmp_path, gateway)
        try:
            result = await harness.run(_task())
            assert result.status == "failed"
            assert result.error_code == "AGENT_LOOP_DETECTED"
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_harness_budget_exceeded(tmp_path: Path) -> None:
    async def scenario() -> None:
        action = {"action": "tool", "tool": "echo", "arguments": {"x": 1}}
        gateway = FakeGateway([action])
        harness, sessions = _harness(tmp_path, gateway)
        try:
            result = await harness.run(_task(max_steps=1))
            assert result.status == "failed"
            assert result.error_code == "AGENT_BUDGET_EXCEEDED"
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_harness_invalid_output_fails(tmp_path: Path) -> None:
    async def scenario() -> None:
        gateway = FakeGateway(
            [
                ({"action": "final", "output": {"wrong": True}}),
                ({"action": "final", "output": {"wrong": True}}),
            ]
        )
        harness, sessions = _harness(tmp_path, gateway)
        try:
            result = await harness.run(_task())
            assert result.status == "failed"
            assert result.error_code == "AGENT_OUTPUT_INVALID"
        finally:
            sessions.close()

    asyncio.run(scenario())
