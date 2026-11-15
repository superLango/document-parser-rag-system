from __future__ import annotations

import asyncio

from services.agent.tools.builtin import (
    build_default_registry,
    escalate_to_human,
    request_review,
    run_sandbox,
)


def test_write_tools_registered_with_write_permission() -> None:
    registry = build_default_registry()
    permissions = registry.permissions()
    for name in ("escalate_to_human", "run_sandbox", "request_review"):
        assert permissions[name] == "write"
        assert registry.get(name) is not None


def test_escalate_to_human_requires_reason() -> None:
    result = asyncio.run(escalate_to_human({}, {}))
    assert result == {"error": "reason_required"}


def test_escalate_to_human_carries_table_ids() -> None:
    result = asyncio.run(
        escalate_to_human(
            {"reason": "low confidence", "table_ids": ["T1", "T2"]},
            {},
        )
    )
    assert result["status"] == "human_required"
    assert result["table_ids"] == ["T1", "T2"]


def test_run_sandbox_requires_request_context() -> None:
    result = asyncio.run(run_sandbox({}, {}))
    assert result == {"error": "sandbox_request_missing"}


def test_request_review_requires_request_context() -> None:
    result = asyncio.run(request_review({}, {}))
    assert result == {"error": "review_request_missing"}
