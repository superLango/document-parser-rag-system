"""RepairAgent: minimal candidate recipe patch with a test plan."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from hanson_contracts import (
    AgentResult,
    AgentStep,
    AgentTask,
    RepairProposal,
    TriageDecision,
)

from ..context import ContextManager
from ..model_gateway import ModelGateway, ModelOutputInvalid, ModelUnavailable
from ..prompts import PromptLibrary
from ..session import SessionStore

REPAIR_SCHEMA = {
    "type": "object",
    "required": ["root_cause", "scope", "summary", "patch", "test_plan"],
    "properties": {
        "root_cause": {"type": "string"},
        "scope": {"type": "string"},
        "summary": {"type": "string"},
        "patch": {"type": "object"},
        "test_plan": {"type": "array", "items": {"type": "string"}},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "needs_human": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}
ALLOWED_ROOTS = ("/bindings", "/signature", "/rules", "/templates", "/compatibility")
MEASURE_DEFAULTS = {
    "Z": ("%", "tensile", "断面收缩率"),
    "Rm": ("MPa", "tensile", "抗拉强度"),
    "Rp0.2": ("MPa", "tensile", "屈服强度"),
    "Re": ("MPa", "tensile", "屈服强度"),
    "A": ("%", "tensile", "断后伸长率"),
    "KU2": ("J", "impact", "冲击吸收能量"),
    "KV2": ("J", "impact", "冲击吸收能量"),
    "HB": ("", "hardness", "布氏硬度"),
    "HBW": ("", "hardness", "布氏硬度"),
    "HRC": ("", "hardness", "洛氏硬度"),
    "HV": ("", "hardness", "维氏硬度"),
    "持久时间": ("h", "stress_rupture", "持久时间"),
}


class RepairAgent:
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
        prompt = self.prompts.resolve("repair", task.prompt_id)
        session = self.sessions.create(task, prompt.prompt_id, prompt.sha256)
        feedback = task.inputs.get("feedback") or {}
        triage = task.inputs.get("triage") or {}
        recipe = task.inputs.get("recipe") or {}
        target = feedback.get("target") or {}
        degraded = False
        response = None
        proposal: RepairProposal
        try:
            state = await self.context_manager.assemble(
                prompt.text,
                task.objective,
                facts=[
                    {
                        "content": json.dumps(
                            {
                                "feedback": feedback,
                                "triage": triage,
                                "recipe": recipe,
                                "target": target,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "immutable": True,
                    }
                ],
                schema=REPAIR_SCHEMA,
            )
            messages = self.context_manager.render_messages(
                state, instruction="Return only the RepairProposal JSON object."
            )
            value, response = await self.gateway.chat_json(messages)
            proposal = _parse_repair(value, feedback, triage, recipe)
        except (ModelUnavailable, ModelOutputInvalid):
            degraded = True
            proposal = repair_fallback(feedback, triage, recipe)
        session.status = "completed"
        session.output = proposal.model_dump(mode="json")
        session.steps.append(
            AgentStep(
                index=1,
                kind="final",
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                detail={"degraded": degraded, "ops": len(_ops(proposal.patch))},
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


def _ops(patch: Any) -> list[dict[str, Any]]:
    if not isinstance(patch, dict):
        return []
    ops = patch.get("ops")
    return [item for item in ops or [] if isinstance(item, dict)]


def _valid_op(op: dict[str, Any]) -> bool:
    action = str(op.get("op") or "")
    path = str(op.get("path") or "")
    if action not in {"add", "replace", "remove", "test"}:
        return False
    if not any(path == root or path.startswith(root + "/") for root in ALLOWED_ROOTS):
        return False
    if action == "remove":
        return True
    return "value" in op


def _parse_repair(
    value: Any,
    feedback: dict[str, Any],
    triage: dict[str, Any],
    recipe: dict[str, Any],
) -> RepairProposal:
    if not isinstance(value, dict):
        return repair_fallback(feedback, triage, recipe)
    scope = str(value.get("scope") or "none")
    root_cause = str(value.get("root_cause") or "unknown")
    if scope not in {"data", "recipe", "template", "prompt", "engine", "display", "none"}:
        return repair_fallback(feedback, triage, recipe)
    ops = [op for op in _ops(value.get("patch")) if _valid_op(op)]
    if not ops and not bool(value.get("needs_human")):
        return repair_fallback(feedback, triage, recipe)
    target = feedback.get("target") or {}
    measure = str(target.get("measure") or "")
    if measure and scope == "recipe" and not any(
        measure in str(op.get("path") or "") for op in ops
    ):
        fallback = repair_fallback(feedback, triage, recipe)
        ops.extend(_ops(fallback.patch))
    try:
        confidence = float(value.get("confidence") or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    return RepairProposal(
        proposal_id=str(value.get("proposal_id") or uuid.uuid4()),
        root_cause=root_cause,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
        summary=str(value.get("summary") or ""),
        patch={"ops": ops},
        test_plan=[str(item) for item in value.get("test_plan") or []],
        risk=str(value.get("risk") or "low"),  # type: ignore[arg-type]
        needs_human=bool(value.get("needs_human")),
        confidence=max(0.0, min(confidence, 1.0)),
    )


def repair_fallback(
    feedback: dict[str, Any],
    triage: dict[str, Any] | TriageDecision,
    recipe: dict[str, Any],
) -> RepairProposal:
    if isinstance(triage, TriageDecision):
        triage_data = triage.model_dump(mode="json")
    else:
        triage_data = triage or {}
    target = feedback.get("target") or {}
    measure = str(target.get("measure") or _infer_measure(feedback))
    scope = str(triage_data.get("repair_scope") or "none")
    if scope not in {"recipe"}:
        return RepairProposal(
            proposal_id=str(uuid.uuid4()),
            root_cause=str(triage_data.get("root_cause") or "unknown"),  # type: ignore[arg-type]
            scope=scope,  # type: ignore[arg-type]
            summary="Repair scope requires human/other service handling.",
            patch={},
            test_plan=[],
            risk="medium",
            needs_human=True,
            confidence=0.3,
        )
    if not measure:
        return RepairProposal(
            proposal_id=str(uuid.uuid4()),
            root_cause="recipe_binding",
            scope="recipe",
            summary="No concrete measure in feedback; cannot build a binding patch.",
            patch={},
            test_plan=[],
            risk="medium",
            needs_human=True,
            confidence=0.3,
        )
    unit, family, label = MEASURE_DEFAULTS.get(
        measure,
        (
            str(target.get("unit") or ""),
            str(target.get("family") or "custom"),
            str(target.get("label") or measure),
        ),
    )
    ops: list[dict[str, Any]] = [
        {
            "op": "add",
            "path": f"/bindings/measures/{measure}",
            "value": {"unit": unit, "family": family},
        }
    ]
    tokens = recipe.get("signature", {}).get("tokens") or []
    if label and label not in tokens:
        ops.append(
            {"op": "add", "path": "/signature/tokens/-", "value": label}
        )
    return RepairProposal(
        proposal_id=str(uuid.uuid4()),
        root_cause="recipe_binding",
        scope="recipe",
        summary=f"Add {measure} binding and signature token to the recipe.",
        patch={"ops": ops},
        test_plan=[
            "target document reparse",
            "regression: mechanical.md",
            f"target measure {measure} presence check",
        ],
        risk="low",
        needs_human=False,
        confidence=0.9,
    )


def _infer_measure(feedback: dict[str, Any]) -> str:
    target_json = json.dumps(feedback.get("target") or {}, ensure_ascii=False)
    text = f"{feedback.get('description') or ''} {target_json}"
    for measure, (_, _, label) in MEASURE_DEFAULTS.items():
        if measure in text or label in text:
            return measure
    match = re.search(r"\b(Z|Rm|A|KU2|KV2|HB|HRC|HV)\b", text)
    return match.group(1) if match else ""
