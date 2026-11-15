"""RepairAgent: minimal candidate recipe patch with a test plan."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from hanson_contracts import (
    AgentResult,
    AgentStep,
    AgentTask,
    CodePatch,
    RepairProposal,
    TriageDecision,
)
from pydantic import ValidationError

from services.code_guard import apply_code_gate, violation_summary

from ..context import ContextManager
from ..model_gateway import ModelGateway, ModelOutputInvalid, ModelUnavailable
from ..prompts import PromptLibrary
from ..session import SessionStore

logger = logging.getLogger(__name__)

REPAIR_SCHEMA = {
    "type": "object",
    "required": ["root_cause", "scope", "summary", "patch", "test_plan"],
    "properties": {
        "root_cause": {"type": "string"},
        "scope": {"type": "string"},
        "summary": {"type": "string"},
        "patch": {"type": "object"},
        "code_patch": {
            "type": "object",
            "properties": {
                "base_version": {"type": "string"},
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["path", "content"],
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["added", "modified"],
                            },
                            "diff": {"type": "string"},
                        },
                    },
                },
            },
        },
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
        repair_context = task.inputs.get("repair_context") or {}
        diagnosis = task.inputs.get("diagnosis") or {}
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
                                "diagnosis": diagnosis,
                                "repair_context": repair_context,
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
        except (ModelUnavailable, ModelOutputInvalid) as exc:
            logger.warning("repair model output unusable: %s", exc)
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


_MISSING = object()


def _pointer_get(document: Any, pointer: str) -> Any:
    """Resolve a JSON Pointer; ``_MISSING`` when the path does not exist."""
    if pointer in {"", "/"}:
        return document
    current = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return _MISSING
            current = current[token]
        elif isinstance(current, list):
            if token == "-" or not token.isdigit():
                return _MISSING
            index = int(token)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _is_redundant(op: dict[str, Any], recipe: dict[str, Any]) -> bool:
    """True when the op cannot change the recipe (re-adds an identical value)."""
    if not recipe:
        return False
    action = str(op.get("op") or "")
    path = str(op.get("path") or "")
    if action not in {"add", "replace"} or "value" not in op:
        return False
    if path.endswith("/-"):
        parent = _pointer_get(recipe, path[: -len("/-")])
        return isinstance(parent, list) and op["value"] in parent
    current = _pointer_get(recipe, path)
    if current is _MISSING:
        return False
    return current == op["value"]


def _needs_human_proposal(
    root_cause: str, summary: str, confidence: float = 0.3
) -> RepairProposal:
    return RepairProposal(
        proposal_id=str(uuid.uuid4()),
        root_cause=root_cause,  # type: ignore[arg-type]
        scope="recipe",
        summary=summary,
        patch={},
        test_plan=[],
        risk="medium",
        needs_human=True,
        confidence=confidence,
    )


def _filtered_fallback(
    feedback: dict[str, Any],
    triage: dict[str, Any] | TriageDecision,
    recipe: dict[str, Any],
) -> RepairProposal:
    """规则兜底补丁同样要做 no-op 过滤，避免重复绑定进入验证。"""
    fallback = repair_fallback(feedback, triage, recipe)
    original = _ops(fallback.patch)
    ops = [op for op in original if not _is_redundant(op, recipe)]
    if len(ops) == len(original):
        return fallback
    if not ops:
        return _needs_human_proposal(
            fallback.root_cause,
            "Fallback patch only re-added existing recipe bindings; "
            "keeping the item for human triage.",
        )
    return fallback.model_copy(update={"patch": {"ops": ops}})


def _data_repair_patch(scope: str, patch: Any) -> dict[str, Any] | None:
    """Keep a table_repair payload; it has no JSON Patch ops by design."""
    if scope != "data" or not isinstance(patch, dict):
        return None
    payload = patch.get("table_repair")
    if isinstance(payload, dict) and isinstance(payload.get("spec"), dict):
        return {"table_repair": payload}
    if isinstance(payload, dict):
        # Tolerate a flattened spec: {"table_id": "T5", "header_rows": 1, ...}.
        spec = {
            key: value
            for key, value in payload.items()
            if key in {"header_rows", "replace_rows", "patch_cells", "delete_rows"}
        }
        if spec:
            return {
                "table_repair": {"table_id": payload.get("table_id"), "spec": spec}
            }
    if isinstance(patch.get("spec"), dict):
        return {"spec": patch["spec"]}
    return None


def _parse_repair(
    value: Any,
    feedback: dict[str, Any],
    triage: dict[str, Any],
    recipe: dict[str, Any],
) -> RepairProposal:
    if not isinstance(value, dict):
        logger.warning("repair output is not an object: %s", str(value)[:400])
        return _filtered_fallback(feedback, triage, recipe)
    inner = value.get("patch")
    if (
        isinstance(inner, dict)
        and isinstance(inner.get("patch"), dict)
        and ("scope" in inner or "root_cause" in inner)
    ):
        # Tolerate a proposal nested one level deep inside "patch".
        value = inner
    scope = str(value.get("scope") or "none")
    root_cause = str(value.get("root_cause") or "unknown")
    if scope not in {"data", "recipe", "template", "prompt", "engine", "display", "none"}:
        logger.warning("repair output scope invalid: %s", str(value)[:400])
        return _filtered_fallback(feedback, triage, recipe)
    raw_ops = [op for op in _ops(value.get("patch")) if _valid_op(op)]
    ops = [op for op in raw_ops if not _is_redundant(op, recipe)]
    code_patch = _parse_code_patch(value.get("code_patch"))
    data_patch = _data_repair_patch(scope, value.get("patch"))
    if scope == "data" and not data_patch and ops:
        # Recipe ops declared as data scope: the ops are still verifiable.
        scope = "recipe"
    if (
        scope != "engine"
        and not ops
        and not data_patch
        and not bool(value.get("needs_human"))
    ):
        logger.warning(
            "repair output has no usable patch: scope=%s patch=%s",
            scope,
            json.dumps(value.get("patch") or {}, ensure_ascii=False)[:400],
        )
        return _filtered_fallback(feedback, triage, recipe)
    target = feedback.get("target") or {}
    measure = str(target.get("measure") or "")
    if measure and scope == "recipe" and not any(
        measure in str(op.get("path") or "") for op in ops
    ):
        bound = _pointer_get(recipe, f"/bindings/measures/{measure}")
        if bound is _MISSING:
            fallback = repair_fallback(feedback, triage, recipe)
            ops.extend(
                op
                for op in _ops(fallback.patch)
                if not _is_redundant(op, recipe)
            )
    if scope == "recipe" and not ops and code_patch is None:
        # 补丁全部是重复绑定（no-op）时，不要进入验证：直接交回人工，
        # 避免把"缺列/结构问题"误判成"缺绑定"。
        return _needs_human_proposal(
            root_cause,
            f"{len(raw_ops)} proposed patch ops are no-ops against the current "
            "recipe; the evidence does not support a recipe binding change.",
        )
    try:
        confidence = float(value.get("confidence") or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    proposal = RepairProposal(
        proposal_id=str(value.get("proposal_id") or uuid.uuid4()),
        root_cause=root_cause,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
        summary=str(value.get("summary") or ""),
        patch=data_patch or {"ops": ops},
        code_patch=code_patch,
        test_plan=[str(item) for item in value.get("test_plan") or []],
        risk=str(value.get("risk") or "low"),  # type: ignore[arg-type]
        needs_human=bool(value.get("needs_human")),
        confidence=max(0.0, min(confidence, 1.0)),
    )
    return _gate_code_proposal(proposal)


def _parse_code_patch(value: Any) -> CodePatch | None:
    if not isinstance(value, dict):
        return None
    try:
        return CodePatch.model_validate(value)
    except ValidationError:
        return None


def _gate_code_proposal(proposal: RepairProposal) -> RepairProposal:
    if proposal.scope == "engine":
        if proposal.code_patch is None or not proposal.code_patch.files:
            proposal.needs_human = True
            proposal.risk = "high"
            proposal.summary = (
                f"{proposal.summary} No engine code patch supplied."
            ).strip()
            return proposal
        apply_code_gate(proposal)
        if proposal.guard is not None and not proposal.guard.passed:
            proposal.summary = (
                f"{proposal.summary} Code guard blocked: "
                f"{violation_summary(proposal.guard)}."
            ).strip()
        return proposal
    if proposal.code_patch is not None:
        proposal.needs_human = True
        proposal.risk = "high"
        proposal.summary = (
            f"{proposal.summary} code_patch is only allowed for engine scope."
        ).strip()
    return proposal


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
