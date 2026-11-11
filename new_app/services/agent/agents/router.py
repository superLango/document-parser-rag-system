"""RouterAgent: model-assisted routing with deterministic guards and fallback."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from hanson_contracts import (
    AgentResult,
    AgentStep,
    AgentTask,
    RouteAssignment,
    RouteDecision,
)

from ..context import ContextManager
from ..model_gateway import ModelGateway, ModelOutputInvalid, ModelUnavailable
from ..prompts import PromptLibrary
from ..session import SessionStore

ROUTE_SCHEMA = {
    "type": "object",
    "required": ["assignments", "fallback", "confidence"],
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["table_id", "recipe_id", "version", "confidence"],
                "properties": {
                    "table_id": {"type": "string"},
                    "recipe_id": {"type": "string"},
                    "version": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "fallback": {"type": "string", "enum": ["human", "generic", "fail"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

VALID_FALLBACK = {"human", "generic", "fail"}


class RouterAgent:
    def __init__(
        self,
        gateway: ModelGateway,
        context_manager: ContextManager,
        sessions: SessionStore,
        prompts: PromptLibrary,
    ) -> None:
        self.gateway = gateway
        self.context_manager = context_manager
        self.sessions = sessions
        self.prompts = prompts

    async def run(self, task: AgentTask) -> AgentResult:
        prompt = self.prompts.resolve("router", task.prompt_id)
        session = self.sessions.create(task, prompt.prompt_id, prompt.sha256)
        tables = list(task.inputs.get("tables") or [])
        catalog = list(task.inputs.get("catalog") or [])
        deterministic = task.inputs.get("deterministic") or []
        compact = {
            "tables": [_compact_table(item) for item in tables],
            "catalog": catalog,
            "deterministic": deterministic,
        }
        degraded = False
        response = None
        try:
            state = await self.context_manager.assemble(
                prompt.text,
                task.objective,
                facts=[
                    {
                        "content": json.dumps(compact, ensure_ascii=False, sort_keys=True),
                        "immutable": True,
                    }
                ],
                schema=ROUTE_SCHEMA,
            )
            messages = self.context_manager.render_messages(
                state, instruction="Return only the RouteDecision JSON object."
            )
            value, response = await self.gateway.chat_json(messages)
            decision = _parse_decision(value, tables, catalog, deterministic)
        except (ModelUnavailable, ModelOutputInvalid):
            degraded = True
            decision = _deterministic_decision(deterministic, tables)
        session.status = "completed"
        session.output = decision.model_dump(mode="json")
        session.steps.append(
            AgentStep(
                index=1,
                kind="final",
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                detail={"degraded": degraded},
            )
        )
        if response is not None:
            session.usage.model_calls += 1
            session.usage.prompt_tokens += response.prompt_tokens
            session.usage.completion_tokens += response.completion_tokens
            session.usage.total_tokens += response.total_tokens
        self.sessions.save(session, task)
        return AgentResult(
            task_id=task.task_id,
            session_id=session.session_id,
            status="completed",
            output=session.output or {},
            usage=session.usage,
            steps=1,
            prompt_id=prompt.prompt_id,
            prompt_hash=prompt.sha256,
            degraded=degraded,
        )


def _compact_table(table: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_id": table.get("table_id"),
        "page_no": table.get("page_no"),
        "caption": table.get("caption"),
        "profile": table.get("profile"),
        "orientation": table.get("orientation"),
        "n_rows": table.get("n_rows"),
        "n_cols": table.get("n_cols"),
        "header_paths": table.get("header_paths") or [],
        "units": table.get("units") or [],
        "sample_rows": _sample_rows(table.get("rows")),
    }


def _sample_rows(rows: Any) -> list[Any]:
    return rows[:5] if isinstance(rows, list) else []


def _deterministic_items(deterministic: Any) -> list[dict[str, Any]]:
    if isinstance(deterministic, dict):
        items = deterministic.get("assignments") or []
    else:
        items = deterministic or []
    return [item for item in items if isinstance(item, dict)]


def _deterministic_decision(
    deterministic: Any,
    tables: list[dict[str, Any]],
) -> RouteDecision:
    table_ids = {str(item.get("table_id")) for item in tables}
    assignments: list[RouteAssignment] = []
    for item in _deterministic_items(deterministic):
        table_id = str(item.get("table_id") or "")
        recipe_id = str(item.get("recipe_id") or "")
        version = str(item.get("version") or "")
        if not table_id or not recipe_id or not version:
            continue
        if table_ids and table_id not in table_ids:
            continue
        assignments.append(
            RouteAssignment(
                table_id=table_id,
                recipe_id=recipe_id,
                version=version,
                confidence=float(item.get("confidence") or item.get("score") or 0.0),
                reasons=list(item.get("reasons") or ["deterministic"]),
            )
        )
    assigned = {item.table_id for item in assignments}
    fallback = "human" if len(assigned) < len(table_ids) else "fail"
    confidence = (
        sum(item.confidence for item in assignments) / len(assignments)
        if assignments
        else 0.0
    )
    return RouteDecision(
        assignments=assignments,
        fallback=fallback,  # type: ignore[arg-type]
        confidence=round(confidence, 4),
    )


def _parse_decision(
    value: Any,
    tables: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    deterministic: Any,
) -> RouteDecision:
    if not isinstance(value, dict):
        return _deterministic_decision(deterministic, tables)
    table_ids = {str(item.get("table_id")) for item in tables}
    catalog_keys = {
        (str(item.get("recipe_id") or ""), str(item.get("version") or ""))
        for item in catalog
        if isinstance(item, dict)
    }
    deterministic_map = {
        str(item.get("table_id")): item
        for item in _deterministic_items(deterministic)
        if item.get("table_id")
    }
    assignments: list[RouteAssignment] = []
    seen_tables: set[str] = set()
    for item in value.get("assignments") or []:
        if not isinstance(item, dict):
            continue
        table_id = str(item.get("table_id") or "")
        recipe_id = str(item.get("recipe_id") or "")
        version = str(item.get("version") or "")
        if not table_id or table_id in seen_tables:
            continue
        if table_ids and table_id not in table_ids:
            continue
        if catalog_keys and (recipe_id, version) not in catalog_keys:
            continue
        confidence = max(0.0, min(float(item.get("confidence") or 0.0), 1.0))
        baseline = deterministic_map.get(table_id)
        reasons = [str(reason) for reason in item.get("reasons") or []]
        if (
            baseline
            and confidence < 0.70
            and (
                str(baseline.get("recipe_id")) != recipe_id
                or str(baseline.get("version")) != version
            )
        ):
            recipe_id = str(baseline.get("recipe_id"))
            version = str(baseline.get("version"))
            confidence = float(baseline.get("confidence") or baseline.get("score") or confidence)
            reasons.append("deterministic_guard")
        seen_tables.add(table_id)
        assignments.append(
            RouteAssignment(
                table_id=table_id,
                recipe_id=recipe_id,
                version=version,
                confidence=round(confidence, 4),
                reasons=reasons,
            )
        )
    for table_id, baseline in sorted(deterministic_map.items()):
        if table_id in seen_tables:
            continue
        recipe_id = str(baseline.get("recipe_id") or "")
        version = str(baseline.get("version") or "")
        if not recipe_id or not version:
            continue
        assignments.append(
            RouteAssignment(
                table_id=table_id,
                recipe_id=recipe_id,
                version=version,
                confidence=float(baseline.get("confidence") or baseline.get("score") or 0.0),
                reasons=list(baseline.get("reasons") or []) + ["deterministic_fill"],
            )
        )
    if not assignments:
        return _deterministic_decision(deterministic, tables)
    fallback = str(value.get("fallback") or "")
    if fallback not in VALID_FALLBACK:
        fallback = "human" if len(assignments) < len(table_ids) else "fail"
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = sum(item.confidence for item in assignments) / len(assignments)
    return RouteDecision(
        assignments=assignments,
        fallback=fallback,  # type: ignore[arg-type]
        confidence=round(float(confidence), 4),
    )
