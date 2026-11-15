from __future__ import annotations

import asyncio

import pytest
from hanson_contracts import AgentBudget, AgentTask

from services.orchestration.feedback.service import (
    FeedbackBudgetExceeded,
    FeedbackService,
)


def _task() -> AgentTask:
    return AgentTask(
        task_id="t1",
        trace_id="run-1",
        role="triage",
        objective="test",
    )


def test_task_budget_caps_tokens_and_wall_time() -> None:
    service = FeedbackService(
        auto_budget=AgentBudget(max_tokens=5000, wall_time_seconds=30.0)
    )
    budget = service._task_budget(
        max_steps=2,
        max_tool_calls=0,
        max_tokens=16000,
        wall_time_seconds=300.0,
    )
    assert budget.max_tokens == 5000
    assert budget.wall_time_seconds <= 30.0


def test_task_budget_keeps_floor_of_1024_tokens() -> None:
    service = FeedbackService(
        auto_budget=AgentBudget(max_tokens=1024, wall_time_seconds=30.0)
    )
    service._used_tokens = 900
    budget = service._task_budget(
        max_steps=1, max_tool_calls=0, max_tokens=4000
    )
    assert budget.max_tokens == 1024


def test_process_resets_budget_and_reports_usage() -> None:
    service = FeedbackService(auto_budget=AgentBudget(max_tokens=8000))
    service._used_tokens = 999
    service._reset_budget(AgentBudget(max_tokens=4000, wall_time_seconds=20.0))
    assert service.last_usage == {"tokens": 0, "agent_calls": 0}
    assert service._budget_remaining_tokens() == 4000


def test_call_agent_refuses_when_token_budget_exhausted() -> None:
    service = FeedbackService(
        auto_budget=AgentBudget(max_tokens=1024, wall_time_seconds=30.0)
    )
    service._used_tokens = 1024
    with pytest.raises(FeedbackBudgetExceeded):
        asyncio.run(service._call_agent(_task()))


def test_call_agent_refuses_when_time_budget_exhausted() -> None:
    service = FeedbackService(
        auto_budget=AgentBudget(max_tokens=64000, wall_time_seconds=1.0)
    )
    service._started -= 5
    with pytest.raises(FeedbackBudgetExceeded):
        asyncio.run(service._call_agent(_task()))
