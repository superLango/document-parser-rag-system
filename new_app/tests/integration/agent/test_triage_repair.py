from __future__ import annotations

import asyncio
from pathlib import Path

from hanson_contracts import AgentBudget, AgentTask, ModelResponse

from services.agent.agents.repair import RepairAgent, _parse_repair
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


def test_repair_rejects_noop_binding_patch(tmp_path: Path) -> None:
    """补丁只是重复添加已有绑定时应拦截，不再进入沙箱验证。"""
    recipe = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.0.0",
        "bindings": {"measures": {"Z": {"unit": "%", "family": "tensile"}}},
        "signature": {"tokens": ["牌号", "断面收缩率"]},
    }

    async def scenario() -> None:
        _, repair, sessions = _agents(
            tmp_path,
            FakeGateway(
                {
                    "root_cause": "recipe_binding",
                    "scope": "recipe",
                    "summary": "add Z again",
                    "patch": {
                        "ops": [
                            {
                                "op": "add",
                                "path": "/bindings/measures/Z",
                                "value": {"unit": "%", "family": "tensile"},
                            },
                            {
                                "op": "add",
                                "path": "/signature/tokens/-",
                                "value": "断面收缩率",
                            },
                        ]
                    },
                    "test_plan": ["reparse"],
                    "risk": "low",
                    "confidence": 0.9,
                }
            ),
        )
        task = _task("repair")
        task.inputs["recipe"] = recipe
        try:
            result = await repair.run(task)
            assert result.output["needs_human"] is True
            assert result.output["patch"] in ({}, {"ops": []})
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_repair_keeps_actionable_op_when_one_is_redundant(tmp_path: Path) -> None:
    recipe = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.0.0",
        "bindings": {"measures": {"Z": {"unit": "%", "family": "tensile"}}},
        "signature": {"tokens": ["牌号"]},
    }

    async def scenario() -> None:
        _, repair, sessions = _agents(
            tmp_path,
            FakeGateway(
                {
                    "root_cause": "recipe_binding",
                    "scope": "recipe",
                    "summary": "add Z token",
                    "patch": {
                        "ops": [
                            {
                                "op": "add",
                                "path": "/bindings/measures/Z",
                                "value": {"unit": "%", "family": "tensile"},
                            },
                            {
                                "op": "add",
                                "path": "/signature/tokens/-",
                                "value": "断面收缩率",
                            },
                        ]
                    },
                    "test_plan": ["reparse"],
                    "risk": "low",
                    "confidence": 0.9,
                }
            ),
        )
        task = _task("repair")
        task.inputs["recipe"] = recipe
        try:
            result = await repair.run(task)
            ops = result.output["patch"]["ops"]
            assert [op["path"] for op in ops] == ["/signature/tokens/-"]
        finally:
            sessions.close()

    asyncio.run(scenario())


def test_parse_repair_keeps_data_table_repair_patch() -> None:
    proposal = _parse_repair(
        {
            "root_cause": "table_structure",
            "scope": "data",
            "summary": "repair header row",
            "patch": {
                "table_repair": {
                    "table_id": "T8",
                    "spec": {"header_rows": 1, "patch_cells": {"1": {"1": "≥27"}}},
                }
            },
            "test_plan": ["rerun T8"],
            "risk": "medium",
            "needs_human": False,
            "confidence": 0.7,
        },
        {"target": {}},
        {"repair_scope": "data"},
        {},
    )
    assert proposal.scope == "data"
    assert proposal.patch["table_repair"]["table_id"] == "T8"
    assert proposal.needs_human is False


def test_parse_repair_keeps_flattened_data_table_repair() -> None:
    proposal = _parse_repair(
        {
            "root_cause": "table_structure",
            "scope": "data",
            "summary": "repair header row",
            "patch": {
                "table_repair": {
                    "table_id": "T5",
                    "header_rows": 2,
                    "patch_cells": {"0": {"1": "化学成分(质量分数)/%"}},
                }
            },
            "test_plan": ["rerun T5"],
            "risk": "medium",
            "needs_human": False,
            "confidence": 0.7,
        },
        {"target": {}},
        {"repair_scope": "data"},
        {},
    )
    spec = proposal.patch["table_repair"]["spec"]
    assert proposal.patch["table_repair"]["table_id"] == "T5"
    assert spec["header_rows"] == 2
    assert spec["patch_cells"] == {"0": {"1": "化学成分(质量分数)/%"}}


def test_parse_repair_unwraps_nested_proposal() -> None:
    nested = {
        "root_cause": "table_structure",
        "scope": "data",
        "summary": "repair header",
        "patch": {
            "table_repair": {"table_id": "T1", "spec": {"header_rows": 1}}
        },
        "test_plan": [],
        "needs_human": False,
    }
    proposal = _parse_repair(
        {"patch": nested}, {"target": {}}, {"repair_scope": "data"}, {}
    )
    assert proposal.scope == "data"
    assert proposal.patch["table_repair"]["table_id"] == "T1"


def test_parse_repair_reclassifies_recipe_ops_declared_as_data() -> None:
    proposal = _parse_repair(
        {
            "root_cause": "recipe_binding",
            "scope": "data",
            "summary": "bind Ag",
            "patch": {
                "ops": [
                    {
                        "op": "add",
                        "path": "/bindings/measures/Ag",
                        "value": {"unit": "%"},
                    }
                ]
            },
            "test_plan": [],
            "needs_human": False,
        },
        {"target": {}},
        {"repair_scope": "recipe"},
        {},
    )
    assert proposal.scope == "recipe"
    assert proposal.patch["ops"][0]["path"] == "/bindings/measures/Ag"
    assert proposal.needs_human is False


def test_parse_repair_still_rejects_empty_data_patch() -> None:
    proposal = _parse_repair(
        {
            "root_cause": "table_structure",
            "scope": "data",
            "summary": "no spec",
            "patch": {},
            "test_plan": [],
            "needs_human": False,
        },
        {"target": {}},
        {"repair_scope": "data"},
        {},
    )
    assert proposal.needs_human is True
    assert not proposal.patch.get("ops")
