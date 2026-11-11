"""Review service: deterministic rules plus optional ReviewAgent findings."""

from __future__ import annotations

import logging
import uuid

import httpx
from hanson_contracts import (
    AgentBudget,
    AgentResult,
    AgentTask,
    ReviewFinding,
    ReviewReport,
    ReviewRequest,
)

from .config import Settings
from .rules import merge_findings, run_rules

logger = logging.getLogger(__name__)

REVIEW_OUTPUT_SCHEMA = {
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


class ReviewService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def review(self, request: ReviewRequest) -> ReviewReport:
        deterministic = run_rules(request.records, request.evidence, request.tables)
        model_findings: list[ReviewFinding] = []
        degraded = False
        prompt_id = ""
        prompt_hash = ""
        if self.settings.use_agent:
            try:
                result = await self._call_agent(request, deterministic)
                if result.status == "completed":
                    model_findings = _model_findings(result)
                    prompt_id = result.prompt_id
                    prompt_hash = result.prompt_hash
                    degraded = result.degraded
                else:
                    degraded = True
            except Exception as exc:  # noqa: BLE001 - model review is optional
                logger.warning("review agent unavailable: %s", exc)
                degraded = True
        findings = merge_findings(deterministic, model_findings)
        # Deterministic rule errors block the run; model findings are advisory
        # (and may be false positives), so they only downgrade to "warn".
        deterministic_errors = sum(
            1 for item in deterministic if item.severity == "error"
        )
        model_errors = sum(1 for item in model_findings if item.severity == "error")
        errors = deterministic_errors + model_errors
        warnings = sum(1 for item in findings if item.severity == "warning")
        status = (
            "fail"
            if deterministic_errors
            else ("warn" if warnings or model_errors else "pass")
        )
        return ReviewReport(
            status=status,  # type: ignore[arg-type]
            findings=findings,
            stats={
                "records": len(request.records),
                "findings": len(findings),
                "errors": errors,
                "deterministic_errors": deterministic_errors,
                "model_errors": model_errors,
                "warnings": warnings,
                "info": len(findings) - errors - warnings,
                "deterministic": len(deterministic),
                "model": len(model_findings),
            },
            ruleset_version=self.settings.ruleset_version,
            degraded=degraded,
            prompt_id=prompt_id,
            prompt_hash=prompt_hash,
        )

    async def _call_agent(
        self,
        request: ReviewRequest,
        deterministic: list[ReviewFinding],
    ) -> AgentResult:
        task = AgentTask(
            task_id=f"review-{request.run_id or uuid.uuid4().hex}",
            trace_id=request.trace_id or request.run_id,
            role="review",
            objective=(
                "Review extracted records against their evidence. Report only "
                "issues that deterministic rules cannot detect."
            ),
            inputs={
                "records": request.records,
                "evidence": request.evidence,
                "tables": request.tables,
                "template": request.template,
                "deterministic_findings": [
                    item.model_dump(mode="json") for item in deterministic
                ],
            },
            output_schema=REVIEW_OUTPUT_SCHEMA,
            tools=[],
            budget=AgentBudget(
                max_steps=2,
                max_tool_calls=0,
                max_tokens=64000,
                wall_time_seconds=self.settings.agent_timeout_seconds,
            ),
        )
        url = f"{self.settings.agent_url.rstrip('/')}/internal/agent:run"
        async with httpx.AsyncClient(timeout=self.settings.agent_timeout_seconds) as client:
            response = await client.post(url, json=task.model_dump(mode="json"))
        if response.status_code != 200:
            raise RuntimeError(
                f"agent service error {response.status_code}: {response.text[:300]}"
            )
        return AgentResult.model_validate(response.json())


def _model_findings(result: AgentResult) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for item in result.output.get("findings") or []:
        if not isinstance(item, dict):
            continue
        try:
            finding = ReviewFinding.model_validate(item)
        except ValueError:
            continue
        findings.append(finding.model_copy(update={"source": "model"}))
    return findings
