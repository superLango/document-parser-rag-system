from __future__ import annotations

import asyncio
from pathlib import Path

from hanson_contracts import AgentBudget, AgentTask, ModelResponse

from services.agent.agents.repair import RepairAgent
from services.agent.agents.triage import TriageAgent
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
            content="{}", prompt_tokens=4, completion_tokens=2, total_tokens=6
        )


def _task(role: str) -> AgentTask:
    return AgentTask(
        task_id=f"{role}-1",
        trace_id="trace-1",
        role=role,  # type: ignore[arg-type]
        objective="triage/repair feedback",
        inputs={
            "feedback": {
                "category": "missing_measure",
                "target": {"recipe_id": "mechanical_properties_v1", "measure": "Z"},
                "description": "断面收缩率 Z 未抽取",
                "expected_value": "22",
            },
            "run": {"status": "STRUCTURED_READY", "records": 2, "tables": 1},
            "recipe": {
                "recipe_id": "mechanical_properties_v1",
                "version": "1.0.0",
                "bindings": {"measures": {"Rm": {"unit": "MPa"}}},
                "signature": {"tokens": ["牌号", "rm"]},
            },
            "triage": {"root_cause": "recipe_binding", "repair_scope": "recipe"},
        },
        budget=AgentBudget(max_steps=2, max_tool_calls=0, max_tokens=4000),
    )


def _agents(tmp_path: Path, gateway: FakeGateway):
    sessions = SessionStore(tmp_path / "sessions.db")
    common = (
        gateway,
        ContextManager(HeuristicTokenizer(), max_tokens=4000),
        sessions,
        PromptLibrary(),
    )
    return TriageAgent(*common), RepairAgent(*common), sessions


def test_triage_valid_model_output(tmp_path: Path) -> None:
    async def scenario() -> None:
        triage, _, sessions = _agents(
            tmp_path,
            FakeGateway(
                {
                    "root_cause": "recipe_binding",
                    "repair_scope": "recipe",
                    "confidence": 0.9,
                    "evidence": ["Z not in bindings"],
                    "summary": "add Z binding",
                }
            ),
        )
        try:
            result = await triage.run(_task("triage"))
            assert result.degraded is False
            assert result.output["root_cause"] == "recipe_binding"
            assert result.output["repair_scope"] == "recipe"
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_triage_falls_back_on_model_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        triage, _, sessions = _agents(
            tmp_path, FakeGateway(error=ModelUnavailable("down"))
        )
        try:
            result = await triage.run(_task("triage"))
            assert result.degraded is True
            assert result.output["root_cause"] == "recipe_binding"
            assert result.output["repair_scope"] == "recipe"
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_repair_valid_model_output(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, repair, sessions = _agents(
            tmp_path,
            FakeGateway(
                {
                    "root_cause": "recipe_binding",
                    "scope": "recipe",
                    "summary": "add Z",
                    "patch": {
                        "ops": [
                            {
                                "op": "add",
                                "path": "/bindings/measures/Z",
                                "value": {"unit": "%", "family": "tensile"},
                            }
                        ]
                    },
                    "test_plan": ["reparse"],
                    "risk": "low",
                    "confidence": 0.9,
                }
            ),
        )
        try:
            result = await repair.run(_task("repair"))
            assert result.degraded is False
            assert result.output["patch"]["ops"][0]["path"] == "/bindings/measures/Z"
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_repair_fallback_adds_measure_binding(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, repair, sessions = _agents(
            tmp_path, FakeGateway(error=ModelUnavailable("down"))
        )
        try:
            result = await repair.run(_task("repair"))
            assert result.degraded is True
            ops = result.output["patch"]["ops"]
            assert any(op["path"] == "/bindings/measures/Z" for op in ops)
            assert any(op["path"] == "/signature/tokens/-" for op in ops)
        finally:
            sessions.close()

    asyncio.run(scenario())
