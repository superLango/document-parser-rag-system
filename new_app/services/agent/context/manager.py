"""Context assembly, L1-L3 compaction and lossless invariants."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from hanson_contracts import ModelMessage

from .tokenizer import Tokenizer


class ContextOverflow(RuntimeError):
    def __init__(self, tokens: int, budget: int) -> None:
        self.tokens = tokens
        self.budget = budget
        super().__init__(f"context overflow: {tokens} > {budget} tokens")


@dataclass
class ContextBlock:
    kind: str
    content: str
    immutable: bool = False
    ref: str = ""
    tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "content": self.content,
            "immutable": self.immutable,
            "ref": self.ref,
            "tokens": self.tokens,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ContextBlock:
        return cls(
            kind=str(payload.get("kind") or ""),
            content=str(payload.get("content") or ""),
            immutable=bool(payload.get("immutable")),
            ref=str(payload.get("ref") or ""),
            tokens=int(payload.get("tokens") or 0),
        )


@dataclass
class ContextState:
    system: str = ""
    objective: str = ""
    blocks: list[ContextBlock] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    header_paths: list[list[str]] = field(default_factory=list)
    units: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    tokens: int = 0
    max_tokens: int = 64000
    compaction_level: int = 0
    degraded: bool = False
    overflow: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "objective": self.objective,
            "blocks": [block.as_dict() for block in self.blocks],
            "history": list(self.history),
            "schema": self.schema,
            "decisions": self.decisions,
            "evidence_ids": self.evidence_ids,
            "header_paths": self.header_paths,
            "units": self.units,
            "fields": self.fields,
            "tokens": self.tokens,
            "max_tokens": self.max_tokens,
            "compaction_level": self.compaction_level,
            "degraded": self.degraded,
            "overflow": self.overflow,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ContextState:
        return cls(
            system=str(payload.get("system") or ""),
            objective=str(payload.get("objective") or ""),
            blocks=[ContextBlock.from_dict(item) for item in payload.get("blocks") or []],
            history=list(payload.get("history") or []),
            schema=dict(payload.get("schema") or {}),
            decisions=list(payload.get("decisions") or []),
            evidence_ids=[str(item) for item in payload.get("evidence_ids") or []],
            header_paths=[
                [str(part) for part in path] for path in payload.get("header_paths") or []
            ],
            units=[str(item) for item in payload.get("units") or []],
            fields=[str(item) for item in payload.get("fields") or []],
            tokens=int(payload.get("tokens") or 0),
            max_tokens=int(payload.get("max_tokens") or 64000),
            compaction_level=int(payload.get("compaction_level") or 0),
            degraded=bool(payload.get("degraded")),
            overflow=bool(payload.get("overflow")),
        )


class ContextManager:
    def __init__(
        self,
        tokenizer: Tokenizer,
        max_tokens: int = 64000,
        l1_ratio: float = 0.70,
        l2_ratio: float = 0.85,
        l3_ratio: float = 0.95,
    ) -> None:
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.l1_ratio = l1_ratio
        self.l2_ratio = l2_ratio
        self.l3_ratio = l3_ratio

    async def assemble(
        self,
        system_prompt: str,
        objective: str,
        *,
        facts: list[dict[str, Any]] | None = None,
        history: list[ModelMessage] | None = None,
        tool_outputs: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        decisions: list[dict[str, Any]] | None = None,
        evidence_ids: list[str] | None = None,
        header_paths: list[list[str]] | None = None,
        units: list[str] | None = None,
        fields: list[str] | None = None,
    ) -> ContextState:
        state = ContextState(
            system=system_prompt,
            objective=objective,
            schema=dict(schema or {}),
            decisions=list(decisions or []),
            evidence_ids=[str(item) for item in (evidence_ids or [])],
            header_paths=[[str(part) for part in path] for path in (header_paths or [])],
            units=[str(item) for item in (units or [])],
            fields=[str(item) for item in (fields or [])],
            history=[message.model_dump() for message in (history or [])],
            max_tokens=self.max_tokens,
        )
        for fact in facts or []:
            state.blocks.append(
                ContextBlock(
                    kind="fact",
                    content=str(fact.get("content") or ""),
                    immutable=bool(fact.get("immutable")),
                    ref=str(fact.get("ref") or ""),
                )
            )
        for output in tool_outputs or []:
            state.blocks.append(
                ContextBlock(
                    kind="tool",
                    content=str(output.get("content") or ""),
                    immutable=bool(output.get("immutable")),
                    ref=str(output.get("summary") or output.get("artifact_ref") or ""),
                )
            )
        await self._recount(state)
        if state.tokens > self.max_tokens:
            await self._compact_to(state, self.max_tokens * self.l1_ratio, level=1)
        if state.tokens > self.max_tokens * self.l2_ratio:
            await self._compact_to(state, self.max_tokens * self.l2_ratio, level=2)
        if state.tokens > self.max_tokens * self.l3_ratio:
            await self._compact_to(state, self.max_tokens * self.l3_ratio, level=3)
        if state.tokens > self.max_tokens:
            state.overflow = True
            raise ContextOverflow(state.tokens, self.max_tokens)
        state.degraded = bool(getattr(self.tokenizer, "degraded", False))
        return state

    async def _recount(self, state: ContextState) -> None:
        state.tokens = await self.tokenizer.count(state.system) + 4
        state.tokens += await self.tokenizer.count(state.objective) + 4
        state.tokens += await self.tokenizer.count(
            json.dumps(state.schema, ensure_ascii=False, sort_keys=True)
        )
        state.tokens += await self.tokenizer.count(
            json.dumps(state.decisions, ensure_ascii=False, sort_keys=True)
        )
        for block in state.blocks:
            block.tokens = await self.tokenizer.count(block.content) + 4
            state.tokens += block.tokens
        messages = [ModelMessage.model_validate(item) for item in state.history]
        state.tokens += await self.tokenizer.count_messages(messages)

    async def _compact_to(self, state: ContextState, target: float, level: int) -> None:
        if level == 1:
            while state.history and state.tokens > target:
                state.history.pop(0)
                await self._recount(state)
        elif level == 2:
            for block in state.blocks:
                if block.kind != "tool" or block.immutable:
                    continue
                replacement = block.ref or "[tool output summarized]"
                if block.content != replacement:
                    block.content = replacement
                    await self._recount(state)
                    if state.tokens <= target:
                        break
        elif level == 3:
            state.history.clear()
            for block in state.blocks:
                if block.immutable or block.kind == "tool":
                    continue
                replacement = f"[dropped content; ref={block.ref}]" if block.ref else "[dropped]"
                if block.content != replacement:
                    block.content = replacement
            await self._recount(state)
        if level > state.compaction_level:
            state.compaction_level = level

    @staticmethod
    def check_lossless(before: ContextState, after: ContextState) -> dict[str, Any]:
        before_fields = set(before.fields)
        after_fields = set(after.fields)
        return {
            "lost_evidence": sorted(set(before.evidence_ids) - set(after.evidence_ids)),
            "headers_preserved": before.header_paths == after.header_paths,
            "units_preserved": before.units == after.units,
            "objective_preserved": before.objective == after.objective,
            "schema_preserved": before.schema == after.schema,
            "decisions_preserved": before.decisions == after.decisions,
            "lost_fields": sorted(before_fields - after_fields),
            "lossless": (
                not (set(before.evidence_ids) - set(after.evidence_ids))
                and before.header_paths == after.header_paths
                and before.units == after.units
                and before.objective == after.objective
                and before.schema == after.schema
                and before.decisions == after.decisions
                and not (before_fields - after_fields)
            ),
            "token_reduction": round(
                1 - (after.tokens / before.tokens), 4
            )
            if before.tokens
            else 0.0,
            "before_tokens": before.tokens,
            "after_tokens": after.tokens,
            "compaction_level": after.compaction_level,
        }

    @staticmethod
    def render_messages(
        state: ContextState,
        *,
        instruction: str = "Return only one JSON value that matches the schema.",
    ) -> list[ModelMessage]:
        context_parts = [state.objective]
        if state.schema:
            context_parts.append(
                "Output schema:\n"
                + json.dumps(state.schema, ensure_ascii=False, sort_keys=True)
            )
        if state.decisions:
            context_parts.append(
                "Confirmed decisions:\n"
                + json.dumps(state.decisions, ensure_ascii=False, sort_keys=True)
            )
        for block in state.blocks:
            if block.kind == "fact":
                context_parts.append(f"Fact {block.ref or '-'}: {block.content}")
            else:
                context_parts.append(f"Tool {block.ref or '-'}: {block.content}")
        if state.evidence_ids:
            context_parts.append("Evidence IDs: " + ", ".join(state.evidence_ids))
        context_parts.append(instruction)
        messages = [ModelMessage(role="system", content=state.system)]
        if state.history:
            messages.extend(ModelMessage.model_validate(item) for item in state.history)
        messages.append(ModelMessage(role="user", content="\n\n".join(context_parts)))
        return messages
