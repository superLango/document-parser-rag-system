"""Feedback lifecycle: triage, repair, candidate verification and promotion."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from hanson_contracts import (
    AgentBudget,
    AgentResult,
    AgentTask,
    CandidateRef,
    FeedbackCreate,
    FeedbackDetail,
    FeedbackMessage,
    FeedbackVerifyIn,
    RecipeRef,
    RegressionStats,
    RepairProposal,
    TriageDecision,
    VerificationDiff,
    VerificationPackage,
)
from sqlalchemy import func, select

from ..config import settings
from ..db import SessionLocal
from ..models import Artifact, Feedback, Promotion, Run, RunEvent
from ..workflow import _call_sandbox, build_sandbox_request, get_store

logger = logging.getLogger(__name__)

TERMINAL = {"promoted", "discarded"}


class FeedbackError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _dedupe_key(payload: FeedbackCreate) -> str:
    material = "|".join(
        [
            payload.run_id,
            payload.category,
            json.dumps(payload.target, ensure_ascii=False, sort_keys=True),
            re.sub(r"\s+", "", payload.description),
            payload.expected_value or "",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _detail(feedback: Feedback) -> FeedbackDetail:
    triage = (
        TriageDecision.model_validate(feedback.triage)
        if feedback.triage
        else None
    )
    proposal = (
        RepairProposal.model_validate(feedback.proposal)
        if feedback.proposal
        else None
    )
    candidate = (
        CandidateRef.model_validate(feedback.candidate)
        if feedback.candidate
        else None
    )
    verification = (
        VerificationPackage.model_validate(feedback.verification)
        if feedback.verification
        else None
    )
    messages = [
        FeedbackMessage.model_validate(item)
        for item in (feedback.messages or [])
        if isinstance(item, dict)
    ]
    return FeedbackDetail(
        id=feedback.id,
        run_id=feedback.run_id,
        document_id=feedback.document_id,
        category=feedback.category,
        target=feedback.target or {},
        description=feedback.description,
        expected_value=feedback.expected_value,
        source_quote=feedback.source_quote,
        status=feedback.status,  # type: ignore[arg-type]
        messages=messages,
        triage=triage,
        proposal=proposal,
        candidate=candidate,
        verification=verification,
        created_at=_iso(feedback.created_at) or "",
        updated_at=_iso(feedback.updated_at or feedback.created_at) or "",
        resolved_at=_iso(feedback.resolved_at),
    )


class FeedbackService:
    async def create(self, payload: FeedbackCreate) -> FeedbackDetail:
        key = _dedupe_key(payload)
        async with SessionLocal() as session:
            run = await session.get(Run, payload.run_id)
            if run is None:
                raise FeedbackError("RUN_NOT_FOUND", f"run not found: {payload.run_id}", 404)
            existing = await session.execute(
                select(Feedback).where(Feedback.dedupe_key == key)
            )
            found = existing.scalars().first()
            if found is not None:
                return _detail(found)
            feedback = Feedback(
                document_id=run.document_id,
                run_id=run.id,
                dedupe_key=key,
                category=payload.category,
                target=payload.target,
                description=payload.description,
                expected_value=payload.expected_value,
                source_quote=payload.source_quote,
                status="open",
                root_cause={},
                messages=[
                    FeedbackMessage(
                        role="user",
                        content=payload.description,
                        at=_iso(_now()) or "",
                    ).model_dump()
                ],
                triage={},
                proposal={},
                verification={},
                candidate={},
            )
            session.add(feedback)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                existing = await session.execute(
                    select(Feedback).where(Feedback.dedupe_key == key)
                )
                found = existing.scalars().first()
                if found is not None:
                    return _detail(found)
                raise
            return _detail(feedback)

    async def list(
        self,
        *,
        status: str = "",
        document_id: str = "",
        run_id: str = "",
    ) -> list[FeedbackDetail]:
        async with SessionLocal() as session:
            statement = select(Feedback)
            if status:
                statement = statement.where(Feedback.status == status)
            if document_id:
                statement = statement.where(Feedback.document_id == document_id)
            if run_id:
                statement = statement.where(Feedback.run_id == run_id)
            result = await session.execute(statement.order_by(Feedback.created_at.desc()))
            return [_detail(item) for item in result.scalars()]

    async def get(self, feedback_id: str) -> FeedbackDetail:
        async with SessionLocal() as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            return _detail(feedback)

    async def process(self, feedback_id: str) -> FeedbackDetail:
        async with SessionLocal() as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            if feedback.status not in {"open", "needs_more_info"}:
                raise FeedbackError(
                    "FEEDBACK_STATE_INVALID",
                    f"feedback is {feedback.status}",
                    409,
                )
            feedback.status = "processing"
            _message(feedback, "agent", "Feedback accepted; running triage.")
            feedback.updated_at = _now()
            await session.commit()
            run = await session.get(Run, feedback.run_id)
            if run is None:
                return await self._fail(feedback_id, "RUN_NOT_FOUND", "run not found")
            target = dict(feedback.target or {})
            context = await self._context(run, feedback, target)
        try:
            triage = await self._triage(feedback, context)
            if triage.needs_human:
                return await self._needs_more_info(
                    feedback_id, "Triage requires human review.", triage=triage
                )
            proposal = await self._repair(feedback, triage, context)
            if proposal.needs_human or proposal.scope != "recipe":
                return await self._needs_more_info(
                    feedback_id,
                    "Repair proposal needs human handling.",
                    triage=triage,
                    proposal=proposal,
                )
            candidate = await self._build_candidate(feedback, context, proposal)
            verification = await self._verify(feedback, context, candidate)
            async with SessionLocal() as session:
                feedback = await session.get(Feedback, feedback_id)
                if feedback is None:
                    raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
                feedback.triage = triage.model_dump(mode="json")
                feedback.proposal = proposal.model_dump(mode="json")
                feedback.candidate = candidate.model_dump(mode="json")
                feedback.verification = verification.model_dump(mode="json")
                feedback.root_cause = triage.model_dump(mode="json")
                feedback.status = "verified" if verification.passed else "needs_more_info"
                feedback.updated_at = _now()
                _message(
                    feedback,
                    "agent",
                    (
                        f"Verification {'passed' if verification.passed else 'failed'}: "
                        f"{verification.user_summary}"
                    ),
                )
                await session.commit()
                return _detail(feedback)
        except FeedbackError as exc:
            return await self._fail(feedback_id, exc.code, str(exc))
        except Exception as exc:  # noqa: BLE001 - keep feedback inspectable
            logger.exception("feedback processing failed: %s", feedback_id)
            return await self._fail(feedback_id, "FEEDBACK_PROCESS_FAILED", str(exc)[:500])

    async def verification(self, feedback_id: str) -> VerificationPackage:
        async with SessionLocal() as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            if not feedback.verification:
                raise FeedbackError("VERIFICATION_NOT_FOUND", "verification not ready", 404)
            return VerificationPackage.model_validate(feedback.verification)

    async def verify(
        self, feedback_id: str, payload: FeedbackVerifyIn
    ) -> FeedbackDetail:
        if not payload.actor.strip():
            raise FeedbackError("ACTOR_REQUIRED", "actor is required")
        async with SessionLocal() as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            candidate = (
                CandidateRef.model_validate(feedback.candidate)
                if feedback.candidate
                else None
            )
            if candidate is None:
                raise FeedbackError("CANDIDATE_NOT_FOUND", "candidate not ready", 409)
            run = await session.get(Run, feedback.run_id)
            if payload.decision == "reject":
                try:
                    await self._registry_discard(candidate, payload.actor, payload.reason)
                except FeedbackError as exc:
                    raise exc
                feedback.status = "discarded"
                feedback.resolved_at = _now()
                feedback.updated_at = _now()
                _message(feedback, "agent", f"Candidate discarded: {payload.reason}")
                session.add(
                    Promotion(
                        feedback_id=feedback.id,
                        recipe_id=candidate.recipe_id,
                        from_version=candidate.base_version,
                        to_version=candidate.candidate_version,
                        channel="candidate",
                        action="discard",
                        actor=payload.actor,
                        note=payload.reason,
                    )
                )
                if run is not None:
                    await _append_event(
                        session,
                        run,
                        "feedback.discarded",
                        "feedback",
                        "discarded",
                        {
                            "feedback_id": feedback.id,
                            "recipe_id": candidate.recipe_id,
                            "version": candidate.candidate_version,
                            "actor": payload.actor,
                        },
                    )
                await session.commit()
                return _detail(feedback)

            verification = (
                VerificationPackage.model_validate(feedback.verification)
                if feedback.verification
                else None
            )
            if feedback.status != "verified" or verification is None or not verification.passed:
                raise FeedbackError(
                    "VERIFICATION_NOT_PASSED",
                    "approval requires a passed verification",
                    409,
                )
            stable = await self._registry_resolve(candidate.recipe_id, "stable")
            await self._registry_promote(
                candidate, payload.actor, payload.reason or "feedback approval"
            )
            feedback.status = "promoted"
            feedback.resolved_at = _now()
            feedback.updated_at = _now()
            _message(
                feedback,
                "agent",
                f"Promoted {candidate.recipe_id}@{candidate.candidate_version} to stable.",
            )
            session.add(
                Promotion(
                    feedback_id=feedback.id,
                    recipe_id=candidate.recipe_id,
                    from_version=stable.get("version", candidate.base_version),
                    to_version=candidate.candidate_version,
                    channel="stable",
                    action="promote",
                    actor=payload.actor,
                    note=payload.reason,
                )
            )
            if run is not None:
                await _append_event(
                    session,
                    run,
                    "feedback.promoted",
                    "feedback",
                    "promoted",
                    {
                        "feedback_id": feedback.id,
                        "recipe_id": candidate.recipe_id,
                        "from_version": stable.get("version", candidate.base_version),
                        "to_version": candidate.candidate_version,
                        "actor": payload.actor,
                    },
                )
            await session.commit()
            return _detail(feedback)

    # -- context / agents -------------------------------------------------
    async def _context(
        self, run: Run, feedback: Feedback, target: dict[str, Any]
    ) -> dict[str, Any]:
        result_payload = await _artifact_json(run.id, "result")
        records_payload = await _artifact_json(run.id, "records")
        diagnostics_payload = await _artifact_json(run.id, "diagnostics")
        result = result_payload or {}
        records = (records_payload or {}).get("records") or []
        diagnostics = (diagnostics_payload or {}).get("diagnostics") or []
        recipes = result.get("recipes") or []
        target_recipe_id = str(target.get("recipe_id") or "")
        if not target_recipe_id and recipes:
            target_recipe_id = str(recipes[0].get("recipe_id") or "")
        if not target_recipe_id:
            raise FeedbackError("RECIPE_NOT_RESOLVED", "cannot determine target recipe")
        stable = await self._registry_resolve(target_recipe_id, "stable")
        manifest = await self._registry_get(
            f"/internal/recipes/{target_recipe_id}/versions/{stable['version']}"
        )
        tables = result.get("tables") or []
        target_table_id = str(target.get("table_id") or "")
        if not target_table_id and tables:
            target_table_id = str(tables[0].get("table_id") or "")
        return {
            "result": result,
            "records": records,
            "diagnostics": diagnostics,
            "tables": tables,
            "recipe": manifest,
            "stable": stable,
            "target_recipe_id": target_recipe_id,
            "target_table_id": target_table_id,
            "run_summary": {
                "status": run.status,
                "stage": run.stage,
                "recipe_channel": run.recipe_channel,
                "records": len(records),
                "tables": len(tables),
                "diagnostics": diagnostics[:20],
            },
        }

    async def _triage(
        self, feedback: Feedback, context: dict[str, Any]
    ) -> TriageDecision:
        task = AgentTask(
            task_id=f"feedback-{feedback.id}-triage",
            trace_id=feedback.run_id,
            role="triage",
            objective="Classify the feedback root cause and repair scope.",
            inputs={
                "feedback": _feedback_input(feedback),
                "run": context["run_summary"],
                "recipe": context["recipe"],
            },
            output_schema={},
            tools=[],
            budget=AgentBudget(
                max_steps=2,
                max_tool_calls=0,
                max_tokens=16000,
                wall_time_seconds=settings.feedback_timeout_seconds,
            ),
        )
        result = await self._call_agent(task)
        try:
            return TriageDecision.model_validate(result.output)
        except ValueError as exc:
            raise FeedbackError(
                "TRIAGE_INVALID", f"invalid triage output: {exc}"
            ) from exc

    async def _repair(
        self,
        feedback: Feedback,
        triage: TriageDecision,
        context: dict[str, Any],
    ) -> RepairProposal:
        task = AgentTask(
            task_id=f"feedback-{feedback.id}-repair",
            trace_id=feedback.run_id,
            role="repair",
            objective="Propose a minimal recipe candidate patch and test plan.",
            inputs={
                "feedback": _feedback_input(feedback),
                "triage": triage.model_dump(mode="json"),
                "recipe": context["recipe"],
            },
            output_schema={},
            tools=[],
            budget=AgentBudget(
                max_steps=2,
                max_tool_calls=0,
                max_tokens=16000,
                wall_time_seconds=settings.feedback_timeout_seconds,
            ),
        )
        result = await self._call_agent(task)
        try:
            return RepairProposal.model_validate(result.output)
        except ValueError as exc:
            raise FeedbackError(
                "REPAIR_INVALID", f"invalid repair output: {exc}"
            ) from exc

    async def _call_agent(self, task: AgentTask) -> AgentResult:
        url = f"{settings.agent_url.rstrip('/')}/internal/agent:run"
        try:
            async with httpx.AsyncClient(timeout=settings.feedback_timeout_seconds) as client:
                response = await client.post(url, json=task.model_dump(mode="json"))
        except httpx.HTTPError as exc:
            raise FeedbackError(
                "AGENT_UNAVAILABLE", f"agent service unavailable: {exc}", 503
            ) from exc
        if response.status_code != 200:
            raise FeedbackError(
                "AGENT_ERROR",
                f"agent service error {response.status_code}: {response.text[:300]}",
                502,
            )
        result = AgentResult.model_validate(response.json())
        if result.status != "completed":
            raise FeedbackError(
                "AGENT_FAILED",
                result.error_message or f"agent finished with {result.status}",
                502,
            )
        return result

    # -- candidate / verification -----------------------------------------
    async def _build_candidate(
        self,
        feedback: Feedback,
        context: dict[str, Any],
        proposal: RepairProposal,
    ) -> CandidateRef:
        recipe_id = context["target_recipe_id"]
        base_version = str(context["recipe"].get("version") or "")
        if not base_version:
            raise FeedbackError("RECIPE_NOT_RESOLVED", "base recipe version missing")
        versions = await self._registry_get(f"/internal/recipes/{recipe_id}")
        existing = {
            str(item.get("version"))
            for item in versions.get("versions") or []
            if isinstance(item, dict)
        }
        candidate_version = _next_version(base_version, existing)
        payload = {
            "candidate_version": candidate_version,
            "patch": proposal.patch,
            "actor": f"feedback:{feedback.id}",
            "note": proposal.summary,
        }
        response = await self._registry_post(
            f"/internal/recipes/{recipe_id}/versions/{base_version}/candidate",
            payload,
        )
        return CandidateRef(
            recipe_id=recipe_id,
            base_version=base_version,
            candidate_version=str(response.get("version") or candidate_version),
            digest=str(response.get("digest") or ""),
            patch=proposal.patch,
        )

    async def _verify(
        self,
        feedback: Feedback,
        context: dict[str, Any],
        candidate: CandidateRef,
    ) -> VerificationPackage:
        measure = str((feedback.target or {}).get("measure") or "")
        if not measure:
            raise FeedbackError(
                "TARGET_MEASURE_MISSING", "verification requires target.measure"
            )
        async with SessionLocal() as session:
            run = await session.get(Run, feedback.run_id)
            if run is None:
                raise FeedbackError("RUN_NOT_FOUND", "run not found", 404)
        request = await build_sandbox_request(
            run,
            recipe_override=RecipeRef(
                recipe_id=candidate.recipe_id,
                version=candidate.candidate_version,
                digest=candidate.digest,
            ),
            table_id=context.get("target_table_id"),
        )
        result = await _call_sandbox(request)
        before_records = context["records"]
        before_diagnostics = context["diagnostics"]
        if result.status != "succeeded":
            return VerificationPackage(
                proposal_id=feedback.id,
                before_run=feedback.run_id,
                after_run=f"{feedback.run_id}:candidate",
                diff=VerificationDiff(),
                regression=RegressionStats(documents=1, new_errors=1),
                affected_targets=[
                    {"recipe_id": candidate.recipe_id, "measure": measure}
                ],
                user_summary=f"candidate sandbox failed: {result.error_code}",
                artifacts=[],
                passed=False,
            )
        after_records = await _output_json(result, "records")
        after_diagnostics = await _output_json(result, "diagnostics")
        before_map = {
            str(item.get("record_id")): item
            for item in before_records
            if isinstance(item, dict)
        }
        after_map = {
            str(item.get("record_id")): item
            for item in (after_records.get("records") or [])
            if isinstance(item, dict)
        }
        added: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        changed: list[dict[str, Any]] = []
        for record_id, after in after_map.items():
            before = before_map.get(record_id)
            after_props = (after.get("properties") or {}).get(measure)
            before_props = (before or {}).get("properties") or {}
            before_value = before_props.get(measure)
            if after_props is not None and before_value is None:
                added.append(
                    {
                        "record_id": record_id,
                        "measure": measure,
                        "after": after_props,
                    }
                )
            elif after_props is not None and after_props != before_value:
                changed.append(
                    {
                        "record_id": record_id,
                        "measure": measure,
                        "before": before_value,
                        "after": after_props,
                    }
                )
        for record_id, before in before_map.items():
            if measure in (before.get("properties") or {}) and record_id not in after_map:
                removed.append(
                    {
                        "record_id": record_id,
                        "measure": measure,
                        "before": (before.get("properties") or {}).get(measure),
                    }
                )
        target_fixed = bool(added or changed)
        before_errors = sum(
            1 for item in before_diagnostics if item.get("severity") == "error"
        )
        after_errors = sum(
            1
            for item in (after_diagnostics.get("diagnostics") or [])
            if item.get("severity") == "error"
        )
        new_errors = max(0, after_errors - before_errors)
        passed = target_fixed and new_errors == 0 and not removed
        artifacts = [
            item.storage_key for item in result.outputs.values() if item.storage_key
        ]
        return VerificationPackage(
            proposal_id=feedback.id,
            before_run=feedback.run_id,
            after_run=f"{feedback.run_id}:candidate:{candidate.candidate_version}",
            diff=VerificationDiff(added=added, removed=removed, changed=changed),
            regression=RegressionStats(
                documents=1,
                field_f1_delta=1.0 if target_fixed else 0.0,
                new_errors=new_errors,
            ),
            affected_targets=[
                {
                    "recipe_id": candidate.recipe_id,
                    "measure": measure,
                    "table_id": context.get("target_table_id"),
                }
            ],
            user_summary=(
                f"Target {measure}: "
                f"{'fixed' if target_fixed else 'not fixed'}; "
                f"new errors={new_errors}."
            ),
            artifacts=artifacts,
            passed=passed,
        )

    # -- registry ---------------------------------------------------------
    async def _registry_get(self, path: str) -> dict[str, Any]:
        url = f"{settings.recipe_registry_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise FeedbackError(
                "REGISTRY_UNAVAILABLE", f"recipe registry unavailable: {exc}", 503
            ) from exc
        if response.status_code != 200:
            raise FeedbackError(
                "REGISTRY_ERROR",
                f"registry error {response.status_code}: {response.text[:300]}",
                502,
            )
        return response.json()

    async def _registry_post(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{settings.recipe_registry_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise FeedbackError(
                "REGISTRY_UNAVAILABLE", f"recipe registry unavailable: {exc}", 503
            ) from exc
        if response.status_code not in {200, 201}:
            raise FeedbackError(
                "REGISTRY_ERROR",
                f"registry error {response.status_code}: {response.text[:300]}",
                409 if response.status_code == 409 else 502,
            )
        return response.json()

    async def _registry_resolve(self, recipe_id: str, channel: str) -> dict[str, Any]:
        return await self._registry_post(
            "/internal/recipes/resolve",
            {"recipe_id": recipe_id, "channel": channel},
        )

    async def _registry_promote(
        self, candidate: CandidateRef, actor: str, note: str
    ) -> None:
        await self._registry_post(
            f"/internal/recipes/{candidate.recipe_id}/versions/"
            f"{candidate.candidate_version}/promote",
            {"channel": "stable", "actor": actor, "note": note},
        )

    async def _registry_discard(
        self, candidate: CandidateRef, actor: str, reason: str
    ) -> None:
        await self._registry_post(
            f"/internal/recipes/{candidate.recipe_id}/versions/"
            f"{candidate.candidate_version}/discard",
            {"actor": actor, "reason": reason},
        )

    # -- state helpers ----------------------------------------------------
    async def _needs_more_info(
        self,
        feedback_id: str,
        message: str,
        *,
        triage: TriageDecision | None = None,
        proposal: RepairProposal | None = None,
    ) -> FeedbackDetail:
        async with SessionLocal() as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            if triage is not None:
                feedback.triage = triage.model_dump(mode="json")
                feedback.root_cause = triage.model_dump(mode="json")
            if proposal is not None:
                feedback.proposal = proposal.model_dump(mode="json")
            feedback.status = "needs_more_info"
            feedback.updated_at = _now()
            _message(feedback, "agent", message)
            await session.commit()
            return _detail(feedback)

    async def _fail(
        self, feedback_id: str, code: str, message: str
    ) -> FeedbackDetail:
        async with SessionLocal() as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            feedback.status = "needs_more_info"
            feedback.updated_at = _now()
            _message(feedback, "agent", f"{code}: {message}")
            await session.commit()
            return _detail(feedback)


def _feedback_input(feedback: Feedback) -> dict[str, Any]:
    return {
        "category": feedback.category,
        "target": feedback.target or {},
        "description": feedback.description,
        "expected_value": feedback.expected_value,
        "source_quote": feedback.source_quote,
    }


def _message(feedback: Feedback, role: str, content: str) -> None:
    messages = list(feedback.messages or [])
    messages.append(
        FeedbackMessage(role=role, content=content, at=_iso(_now()) or "").model_dump()
    )
    feedback.messages = messages


async def _artifact_json(run_id: str, role: str) -> Any:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id, Artifact.role == role)
            .order_by(Artifact.created_at.desc())
        )
        artifact = result.scalars().first()
    if artifact is None:
        return None
    data = await get_store().get_bytes(artifact.storage_key)
    return json.loads(data)


async def _output_json(result: Any, role: str) -> dict[str, Any]:
    output = result.outputs.get(role)
    if output is None:
        return {}
    data = await get_store().get_bytes(output.storage_key)
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else {}


def _next_version(base: str, existing: set[str]) -> str:
    major, minor, patch = (int(part) for part in base.split("."))
    candidate = f"{major}.{minor}.{patch + 1}"
    while candidate in existing:
        patch += 1
        candidate = f"{major}.{minor}.{patch + 1}"
    return candidate


async def _append_event(
    session,
    run: Run,
    event_type: str,
    stage: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    result = await session.execute(
        select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run.id)
    )
    sequence = (result.scalar() or 0) + 1
    session.add(
        RunEvent(
            run_id=run.id,
            sequence=sequence,
            type=event_type,
            stage=stage,
            status=status,
            payload=payload,
        )
    )
