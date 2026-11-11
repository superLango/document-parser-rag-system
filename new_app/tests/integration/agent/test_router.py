from __future__ import annotations

import asyncio
from pathlib import Path

from hanson_contracts import AgentBudget, AgentTask, ModelResponse

from services.agent.agents.router import RouterAgent
from services.agent.context import ContextManager, HeuristicTokenizer
from services.agent.model_gateway import ModelUnavailable
from services.agent.prompts import PromptLibrary
from services.agent.session import SessionStore


class FakeGateway:
    def __init__(self, value=None, error=None) -> None:
        self.value = value
        self.error = error

    async def chat_json(self, messages, **kwargs):
        if self.error is not None:
            raise self.error
        return self.value, ModelResponse(
            content="{}", prompt_tokens=5, completion_tokens=2, total_tokens=7
        )


def _task() -> AgentTask:
    return AgentTask(
        task_id="route-1",
        trace_id="trace-1",
        role="router",
        objective="route tables",
        inputs={
            "tables": [{"table_id": "T1", "page_no": 1, "profile": "mechanical_properties"}],
            "catalog": [
                {"recipe_id": "r1", "version": "1.0.0", "profile": "mechanical_properties"}
            ],
            "deterministic": [
                {
                    "table_id": "T1",
                    "recipe_id": "r1",
                    "version": "1.0.0",
                    "confidence": 0.8,
                    "reasons": ["baseline"],
                }
            ],
        },
        budget=AgentBudget(max_steps=2, max_tool_calls=0, max_tokens=4000),
    )


def test_router_uses_valid_model_decision(tmp_path: Path) -> None:
    async def scenario() -> None:
        gateway = FakeGateway(
            {
                "assignments": [
                    {
                        "table_id": "T1",
                        "recipe_id": "r1",
                        "version": "1.0.0",
                        "confidence": 0.93,
                        "reasons": ["model"],
                    }
                ],
                "fallback": "fail",
                "confidence": 0.93,
            }
        )
        sessions = SessionStore(tmp_path / "sessions.db")
        agent = RouterAgent(
            gateway,
            ContextManager(HeuristicTokenizer(), max_tokens=4000),
            sessions,
            PromptLibrary(),
        )
        try:
            result = await agent.run(_task())
            assert result.status == "completed"
            assert result.degraded is False
            assert result.output["assignments"][0]["recipe_id"] == "r1"
            assert result.output["assignments"][0]["confidence"] == 0.93
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_router_falls_back_on_model_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        sessions = SessionStore(tmp_path / "sessions.db")
        agent = RouterAgent(
            FakeGateway(error=ModelUnavailable("down")),
            ContextManager(HeuristicTokenizer(), max_tokens=4000),
            sessions,
            PromptLibrary(),
        )
        try:
            result = await agent.run(_task())
            assert result.status == "completed"
            assert result.degraded is True
            assert result.output["assignments"][0]["recipe_id"] == "r1"
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_router_rejects_recipe_not_in_catalog(tmp_path: Path) -> None:
    async def scenario() -> None:
        gateway = FakeGateway(
            {
                "assignments": [
                    {
                        "table_id": "T1",
                        "recipe_id": "invented",
                        "version": "9.9.9",
                        "confidence": 0.99,
                    }
                ],
                "fallback": "fail",
                "confidence": 0.99,
            }
        )
        sessions = SessionStore(tmp_path / "sessions.db")
        agent = RouterAgent(
            gateway,
            ContextManager(HeuristicTokenizer(), max_tokens=4000),
            sessions,
            PromptLibrary(),
        )
        try:
            result = await agent.run(_task())
            assert result.output["assignments"][0]["recipe_id"] == "r1"
        finally:
            sessions.close()

    asyncio.run(scenario())
