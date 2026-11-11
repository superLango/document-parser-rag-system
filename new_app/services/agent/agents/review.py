"""ReviewAgent: semantic findings with evidence checks and rule-only fallback."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from hanson_contracts import (
    AgentResult,
    AgentStep,
    AgentTask,
    ReviewFinding,
)

from ..context import ContextManager
from ..model_gateway import ModelGateway, ModelOutputInvalid, ModelUnavailable
from ..prompts import PromptLibrary
from ..session import SessionStore

REVIEW_SCHEMA = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "severity", "target", "confidence"],
                "properties": {
                    "category": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "error"]},
                    "target": {"type": "object"},
                    "observed": {"type": "string"},
                    "expected": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        }
    },
}
SEVERITIES = {"info", "warning", "error"}


class ReviewAgent:
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
        prompt = self.prompts.resolve("review", task.prompt_id)
        session = self.sessions.create(task, prompt.prompt_id, prompt.sha256)
        records = [item for item in (task.inputs.get("records") or []) if isinstance(item, dict)]
        evidence = [item for item in (task.inputs.get("evidence") or []) if isinstance(item, dict)]
        tables = [item for item in (task.inputs.get("tables") or []) if isinstance(item, dict)]
        deterministic = task.inputs.get("deterministic_findings") or []
        compact = {
            "records": [_compact_record(item) for item in records[:50]],
            "evidence": evidence[:100],
            "tables": [
                {
                    "table_id": item.get("table_id"),
                    "page_no": item.get("page_no"),
                    "header_paths": item.get("header_paths") or [],
                    "units": item.get("units") or [],
                    "sample_rows": _sample_rows(item.get("rows")),
                }
                for item in tables
            ],
            "deterministic_findings": deterministic,
        }
        degraded = False
        response = None
        findings: list[ReviewFinding] = []
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
                schema=REVIEW_SCHEMA,
            )
            messages = self.context_manager.render_messages(
                state, instruction="Return only the ReviewReport findings JSON object."
            )
            value, response = await self.gateway.chat_json(messages)
            findings = _parse_findings(value, records, evidence, deterministic)
        except (ModelUnavailable, ModelOutputInvalid):
            degraded = True
        session.status = "completed"
        session.output = {"findings": [item.model_dump(mode="json") for item in findings]}
        session.steps.append(
            AgentStep(
                index=1,
                kind="final",
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                detail={"degraded": degraded, "findings": len(findings)},
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


def _sample_rows(rows: Any) -> list[Any]:
    return rows[:5] if isinstance(rows, list) else []


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": record.get("record_id"),
        "table_id": record.get("table_id"),
        "page_no": record.get("page_no"),
        "grade": record.get("grade"),
        "conditions": record.get("conditions") or {},
        "properties": record.get("properties") or {},
        "evidence_refs": record.get("evidence_refs") or [],
    }


def _finding_key(finding: ReviewFinding) -> str:
    return json.dumps(
        {
            "category": finding.category,
            "target": finding.target,
            "observed": finding.observed,
            "expected": finding.expected,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _parse_findings(
    value: Any,
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    deterministic: list[dict[str, Any]],
) -> list[ReviewFinding]:
    if not isinstance(value, dict):
        return []
    record_ids = {str(item.get("record_id")) for item in records}
    evidence_ids = {str(item.get("evidence_id")) for item in evidence}
    record_refs = {
        str(item.get("record_id")): [str(ref) for ref in item.get("evidence_refs") or []]
        for item in records
    }
    deterministic_keys = {
        _finding_key(ReviewFinding.model_validate(item))
        for item in deterministic
        if isinstance(item, dict)
    }
    findings: list[ReviewFinding] = []
    seen: set[str] = set()
    for item in value.get("findings") or []:
        if not isinstance(item, dict):
            continue
        target = item.get("target")
        if not isinstance(target, dict):
            target = {}
        record_id = str(target.get("record_id") or "")
        if record_ids and record_id and record_id not in record_ids:
            continue
        severity = str(item.get("severity") or "warning")
        if severity not in SEVERITIES:
            severity = "warning"
        refs = [
            str(ref)
            for ref in item.get("evidence_refs") or []
            if not evidence_ids or str(ref) in evidence_ids
        ]
        if not refs and record_id in record_refs:
            refs = record_refs[record_id]
        finding = ReviewFinding(
            category=str(item.get("category") or "semantic"),
            severity=severity,  # type: ignore[arg-type]
            target=target,
            observed=str(item["observed"]) if item.get("observed") is not None else None,
            expected=str(item["expected"]) if item.get("expected") is not None else None,
            evidence_refs=refs,
            confidence=max(0.0, min(float(item.get("confidence") or 0.5), 1.0)),
            source="model",
        )
        key = _finding_key(finding)
        if key in seen or key in deterministic_keys:
            continue
        seen.add(key)
        findings.append(finding)
    return findings
