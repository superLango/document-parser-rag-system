"""TriageAgent: root cause and smallest repair scope."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from hanson_contracts import (
    AgentResult,
    AgentStep,
    AgentTask,
    TriageDecision,
)

from ..context import ContextManager
from ..model_gateway import ModelGateway, ModelOutputInvalid, ModelUnavailable
from ..prompts import PromptLibrary
from ..session import SessionStore

TRIAGE_SCHEMA = {
    "type": "object",
    "required": ["root_cause", "repair_scope", "confidence", "summary"],
    "properties": {
        "root_cause": {"type": "string"},
        "repair_scope": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "needs_human": {"type": "boolean"},
    },
}
ROOT_CAUSES = {
    "ocr_error",
    "table_structure",
    "recipe_binding",
    "template_schema",
    "model_extraction",
    "dictionary",
    "display",
    "unknown",
}
REPAIR_SCOPES = {"data", "recipe", "template", "prompt", "engine", "display", "none"}


class TriageAgent:
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
        prompt = self.prompts.resolve("triage", task.prompt_id)
        session = self.sessions.create(task, prompt.prompt_id, prompt.sha256)
        feedback = task.inputs.get("feedback") or {}
        run_context = task.inputs.get("run") or {}
        recipe = task.inputs.get("recipe") or {}
        degraded = False
        response = None
        decision: TriageDecision
        try:
            state = await self.context_manager.assemble(
                prompt.text,
                task.objective,
                facts=[
                    {
                        "content": json.dumps(
                            {
                                "feedback": feedback,
                                "run": run_context,
                                "recipe": recipe,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "immutable": True,
                    }
                ],
                schema=TRIAGE_SCHEMA,
            )
            messages = self.context_manager.render_messages(
                state, instruction="Return only the TriageDecision JSON object."
            )
            value, response = await self.gateway.chat_json(messages)
            decision = _parse_triage(value, feedback)
        except (ModelUnavailable, ModelOutputInvalid):
            degraded = True
            decision = triage_fallback(feedback)
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


def _parse_triage(value: Any, feedback: dict[str, Any]) -> TriageDecision:
    if not isinstance(value, dict):
        return triage_fallback(feedback)
    root_cause = str(value.get("root_cause") or "unknown")
    repair_scope = str(value.get("repair_scope") or "none")
    if root_cause not in ROOT_CAUSES or repair_scope not in REPAIR_SCOPES:
        return triage_fallback(feedback)
    try:
        confidence = float(value.get("confidence") or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    return TriageDecision(
        root_cause=root_cause,  # type: ignore[arg-type]
        repair_scope=repair_scope,  # type: ignore[arg-type]
        confidence=max(0.0, min(confidence, 1.0)),
        evidence=[str(item) for item in value.get("evidence") or []],
        summary=str(value.get("summary") or ""),
        needs_human=bool(value.get("needs_human")),
    )


def triage_fallback(feedback: dict[str, Any]) -> TriageDecision:
    category = str(feedback.get("category") or "").lower()
    description = str(feedback.get("description") or "")
    target = feedback.get("target") or {}
    text = f"{category} {description} {json.dumps(target, ensure_ascii=False)}".lower()
    if any(token in text for token in ("ocr", "识别", "看不清", "文字")):
        return TriageDecision(
            root_cause="ocr_error",
            repair_scope="data",
            confidence=0.7,
            evidence=[description],
            summary="OCR or image quality issue; rerun OCR or fix the source.",
        )
    if any(token in text for token in ("表头", "结构", "合并", "multirow", "header")):
        return TriageDecision(
            root_cause="table_structure",
            repair_scope="recipe",
            confidence=0.7,
            evidence=[description],
            summary="Table structure/header issue; repair the recipe rules.",
        )
    if any(token in text for token in ("模板", "schema", "template")):
        return TriageDecision(
            root_cause="template_schema",
            repair_scope="template",
            confidence=0.7,
            evidence=[description],
            summary="Template schema mismatch; create a template candidate.",
        )
    if any(token in text for token in ("展示", "display", "页面")):
        return TriageDecision(
            root_cause="display",
            repair_scope="display",
            confidence=0.7,
            evidence=[description],
            summary="Display-only issue; no parsing promotion required.",
        )
    if any(
        token in text
        for token in ("未抽取", "缺失", "missing", "measure", "字段", "binding", "单位")
    ):
        measure = str(target.get("measure") or "")
        return TriageDecision(
            root_cause="recipe_binding",
            repair_scope="recipe",
            confidence=0.85,
            evidence=[
                description,
                f"target measure={measure}" if measure else "recipe binding target",
            ],
            summary="Measure is not bound in the recipe; add a candidate binding.",
        )
    return TriageDecision(
        root_cause="unknown",
        repair_scope="recipe",
        confidence=0.4,
        evidence=[description],
        summary="Insufficient evidence; keep the item for human triage.",
        needs_human=True,
    )
