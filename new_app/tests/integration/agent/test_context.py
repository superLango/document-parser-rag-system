from __future__ import annotations

import asyncio

import pytest
from hanson_contracts import ModelMessage

from services.agent.context import (
    ContextManager,
    ContextOverflow,
    HeuristicTokenizer,
)


def _manager(max_tokens: int = 200) -> ContextManager:
    return ContextManager(HeuristicTokenizer(), max_tokens=max_tokens)


def test_compaction_preserves_invariants() -> None:
    async def scenario() -> None:
        history = [
            ModelMessage(role="user", content="历史记录 " * 20 + str(index))
            for index in range(12)
        ]
        manager = _manager(120)
        before = await manager.assemble(
            "system prompt",
            "review records",
            facts=[{"id": "f1", "content": "证据事实 " * 10, "immutable": True}],
            history=history,
            schema={"type": "object", "required": ["findings"]},
            decisions=[{"id": "d1", "value": "keep"}],
            evidence_ids=["ev-1", "ev-2"],
            header_paths=[["牌号"], ["抗拉强度 Rm/MPa"]],
            units=["MPa"],
            fields=["Rm", "A"],
        )
        assert before.tokens <= 120
        assert before.compaction_level >= 1
        regression = manager.check_lossless(before, before)
        assert regression["lossless"] is True
        assert regression["lost_evidence"] == []

    asyncio.run(scenario())


def test_tool_outputs_are_summarized_at_l2() -> None:
    async def scenario() -> None:
        manager = _manager(120)
        state = await manager.assemble(
            "system",
            "review",
            tool_outputs=[
                {
                    "call_id": "c1",
                    "content": "原始工具输出 " * 30,
                    "summary": "[artifact: runs/1/records.json]",
                }
            ],
            evidence_ids=["ev-1"],
            schema={"type": "object"},
        )
        assert state.compaction_level >= 2
        tool_blocks = [block for block in state.blocks if block.kind == "tool"]
        assert tool_blocks[0].content.startswith("[artifact:")

    asyncio.run(scenario())


def test_oversized_schema_raises_overflow() -> None:
    async def scenario() -> None:
        manager = _manager(40)
        with pytest.raises(ContextOverflow):
            await manager.assemble(
                "system",
                "review",
                schema={"field": "x" * 2000},
            )

    asyncio.run(scenario())


def test_render_messages_has_system_and_user() -> None:
    async def scenario() -> None:
        manager = _manager(1000)
        state = await manager.assemble(
            "system",
            "route tables",
            facts=[{"id": "f1", "content": "table T1", "immutable": True}],
            schema={"type": "object"},
        )
        messages = manager.render_messages(state)
        assert messages[0].role == "system"
        assert messages[-1].role == "user"
        assert "route tables" in messages[-1].content

    asyncio.run(scenario())
