"""Feedback lifecycle: triage, repair, candidate verification and promotion."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from hanson_contracts import (
    AgentBudget,
    AgentResult,
    AgentTask,
    CandidateRef,
    CodeApprovalIn,
    FeedbackCreate,
    FeedbackDetail,
    FeedbackMessage,
    FeedbackVerifyIn,
    ObjectInput,
    ParserAssetRef,
    RecipeRef,
    RegressionStats,
    RepairProposal,
    ReviewFinding,
    TriageDecision,
    VerificationDiff,
    VerificationPackage,
)
from sqlalchemy import func, select

from services.code_guard import apply_code_gate, violation_summary

from .. import shadow as shadow_service
from ..artifacts import artifact_json
from ..config import settings
from ..db import SessionLocal
from ..models import Artifact, Feedback, Promotion, Run, RunEvent
from ..snapshots import (
    accepted_scope,
    diff_against_snapshot,
    field_digests,
    latest_snapshot,
    next_patch_chain,
    records_digest,
    save_snapshot_from_verification,
)
from ..workflow import _call_sandbox, append_event, build_sandbox_request, get_store, schedule
from .actions import classify_action
from .context import build_repair_context, choose_target_table, merge_tables
from .coverage import compute_coverage, summarize_coverage
from .diagnosis import diagnose, merge_model_diagnosis, needs_model_attribution
from .document_repair import (
    apply_metadata_override,
    build_metadata_override,
    find_method_evidence,
)
from .gates import evaluate_gates
from .intent import (
    apply_rerank,
    needs_clarification,
    needs_rerank,
    resolve_intent,
)
from .memory import CaseStore, header_fingerprint, select_reusable_case
from .outline import table_headers
from .patching import sanitize_patch
from .promotion import OverlayStore
from .regression import gate as regression_gate
from .repairability import evaluate_repairability
from .suggestions import build_suggestions
from .table_repair import (
    apply_table_repair,
    apply_table_repair_to_ocr,
    extract_table_repair,
    validate_table_repair_spec,
)

logger = logging.getLogger(__name__)

TERMINAL = {"promoted", "discarded"}
# 修复 OCR 后自动应用时，除 "ocr" 外还需要复制的 OCR 派生产物。
OCR_ARTIFACT_ROLES = {"ocr", "markdown.md", "pages.json", "tables.json", "layout.json"}


def feedback_from_findings(
    run_id: str,
    document_id: str,
    findings: list[ReviewFinding],
) -> list[FeedbackCreate]:
    """把文档级门禁命中（DOC-*）转成 feedback 载荷。"""
    payloads: list[FeedbackCreate] = []
    for finding in findings:
        rule_id = str(finding.rule_id or "")
        if not rule_id.startswith("DOC-"):
            continue
        target = dict(finding.target or {})
        target.setdefault("level", "document")
        target["rule_id"] = rule_id
        target["document_id"] = document_id
        target["run_id"] = run_id
        # DOC-* 命中允许自动进入 process；是否真正可自动修复由 repairability 决定。
        target.setdefault("auto_repair", True)
        payloads.append(
            FeedbackCreate(
                run_id=run_id,
                category=finding.category,
                target=target,
                description=finding.message or f"{rule_id} detected",
                expected_value=finding.expected,
                reporter="review",
            )
        )
    return payloads


class FeedbackError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class FeedbackBudgetExceeded(FeedbackError):
    """自动修复预算耗尽：转人工，不继续消耗模型额度。"""

    def __init__(self, message: str = "auto repair budget exhausted") -> None:
        super().__init__("AUTO_BUDGET_EXCEEDED", message, 429)


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
        root_cause=feedback.root_cause or {},
        suggestions=_suggestions(feedback),
        triage=triage,
        proposal=proposal,
        candidate=candidate,
        verification=verification,
        created_at=_iso(feedback.created_at) or "",
        updated_at=_iso(feedback.updated_at or feedback.created_at) or "",
        resolved_at=_iso(feedback.resolved_at),
    )


class FeedbackService:
    def __init__(self, *, auto_budget: AgentBudget | None = None) -> None:
        self._auto_budget = auto_budget
        self._used_tokens = 0
        self._agent_calls = 0
        self._started = time.monotonic()

    @property
    def last_usage(self) -> dict[str, int]:
        return {"tokens": self._used_tokens, "agent_calls": self._agent_calls}

    def _reset_budget(self, budget: AgentBudget) -> None:
        self._auto_budget = budget
        self._used_tokens = 0
        self._agent_calls = 0
        self._started = time.monotonic()

    def _budget_remaining_tokens(self) -> int:
        if self._auto_budget is None:
            return 10**9
        return self._auto_budget.max_tokens - self._used_tokens

    def _budget_remaining_seconds(self) -> float:
        if self._auto_budget is None:
            return settings.feedback_timeout_seconds
        return self._auto_budget.wall_time_seconds - (time.monotonic() - self._started)

    def _task_budget(
        self,
        *,
        max_steps: int,
        max_tool_calls: int,
        max_tokens: int,
        wall_time_seconds: float | None = None,
    ) -> AgentBudget:
        wall = (
            wall_time_seconds
            if wall_time_seconds is not None
            else settings.feedback_timeout_seconds
        )
        if self._auto_budget is None:
            return AgentBudget(
                max_steps=max_steps,
                max_tool_calls=max_tool_calls,
                max_tokens=max_tokens,
                wall_time_seconds=wall,
            )
        return AgentBudget(
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            max_tokens=max(1024, min(max_tokens, self._budget_remaining_tokens())),
            wall_time_seconds=max(1.0, min(wall, self._budget_remaining_seconds())),
        )

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

    async def create_from_review(
        self,
        run_id: str,
        document_id: str,
        findings: list[ReviewFinding],
    ) -> list[FeedbackDetail]:
        created: list[FeedbackDetail] = []
        for payload in feedback_from_findings(run_id, document_id, findings):
            created.append(await self.create(payload))
        return created

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

    async def process(
        self, feedback_id: str, budget: AgentBudget | None = None
    ) -> FeedbackDetail:
        if budget is not None:
            self._reset_budget(budget)
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
            _message(feedback, "agent", "已收到反馈，正在定位问题。")
            feedback.updated_at = _now()
            await session.commit()
            run = await session.get(Run, feedback.run_id)
            if run is None:
                return await self._fail(feedback_id, "RUN_NOT_FOUND", "运行不存在")
            target = dict(feedback.target or {})
        try:
            context = await self._context(run, feedback, target)
            intent = context.get("intent") or {}
            if needs_clarification(intent):
                return await self._clarify(feedback_id, intent)
            triage = await self._triage(feedback, context)
            await self._store_root_cause(feedback_id, triage, context)
            if triage.needs_human:
                return await self._needs_more_info(
                    feedback_id, "问题定位需要人工确认。", triage=triage
                )
            repairability = context.get("repairability") or {}
            decision = str(repairability.get("decision") or "")
            if decision == "data":
                return await self._process_l1(feedback_id, feedback, triage, context)
            if decision == "document_rule":
                return await self._process_document_rule(
                    feedback_id, feedback, triage, context
                )
            if decision in {"engine", "needs_more_info"}:
                prefix = {
                    "engine": "OCR/解析引擎问题",
                    "needs_more_info": "暂不支持自动修复",
                }[decision]
                return await self._needs_more_info(
                    feedback_id,
                    f"{prefix}：{repairability.get('reason') or '未给出原因'}",
                    triage=triage,
                )
            proposal = None
            candidate = None
            verification = None
            reusable = (
                ((context.get("repair_context") or {}).get("history") or {}).get(
                    "reusable_case"
                )
                or {}
            ).get("L2")
            for attempt in range(1, 3):
                context["attempt"] = attempt
                if attempt == 1 and reusable:
                    proposal = _proposal_from_case(reusable)
                else:
                    proposal = await self._repair(feedback, triage, context)
                if proposal.scope == "engine":
                    return await self._process_engine(
                        feedback_id, feedback, triage, context, proposal=proposal
                    )
                if proposal.needs_human or proposal.scope != "recipe":
                    return await self._needs_more_info(
                        feedback_id,
                        "修复方案需要人工处理。",
                        triage=triage,
                        proposal=proposal,
                    )
                if not context.get("target_recipe_id"):
                    return await self._needs_more_info(
                        feedback_id,
                        "未绑定配方，属于文档级问题，需要 OCR/解析引擎修复。",
                        triage=triage,
                        proposal=proposal,
                    )
                constraints = (
                    (context.get("repair_context") or {}).get("constraints") or {}
                )
                sanitized = sanitize_patch(
                    proposal.patch,
                    allowed_operators=repairability.get("allowed_operators") or None,
                    admissible=constraints.get("admissible") or None,
                    max_ops=int(constraints.get("max_ops") or 0) or None,
                )
                if not sanitized["effective"]:
                    details = list(sanitized["problems"])
                    if sanitized["advisory_ops"]:
                        details.append(
                            f"{len(sanitized['advisory_ops'])} 个建议操作不影响验证"
                        )
                    if sanitized["rejected_ops"]:
                        details.append(
                            f"{len(sanitized['rejected_ops'])} 个操作被补丁策略拒绝"
                        )
                    return await self._needs_more_info(
                        feedback_id,
                        "补丁没有可生效的操作。" + "；".join(details),
                        triage=triage,
                        proposal=proposal,
                    )
                proposal = proposal.model_copy(
                    update={
                        "patch": {**proposal.patch, "ops": sanitized["effective_ops"]}
                    }
                )
                candidate = await self._build_candidate(feedback, context, proposal)
                verification = await self._verify(feedback, context, candidate)
                if verification.passed:
                    break
                if attempt < 2:
                    self._remember_attempt(
                        context,
                        attempt,
                        proposal,
                        verification.checks,
                        verification.user_summary,
                        verification=verification,
                    )
                    continue
                break
            if (
                verification is not None
                and verification.passed
                and proposal is not None
            ):
                self._remember_case(
                    feedback,
                    context,
                    patch=proposal.patch,
                    level="L2",
                    action_tier=verification.action_tier,
                )
            async with SessionLocal() as session:
                feedback = await session.get(Feedback, feedback_id)
                if feedback is None:
                    raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
                feedback.triage = triage.model_dump(mode="json")
                feedback.proposal = proposal.model_dump(mode="json")
                feedback.candidate = candidate.model_dump(mode="json")
                feedback.verification = verification.model_dump(mode="json")
                feedback.root_cause = _root_cause_payload(triage, context)
                feedback.status = "verified" if verification.passed else "needs_more_info"
                feedback.updated_at = _now()
                _message(
                    feedback,
                    "agent",
                    (
                        f"验证{'通过' if verification.passed else '未通过'}："
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
            document_id = run.document_id if run is not None else ""
            document_version = run.document_version if run is not None else 1
            if payload.decision == "reject":
                try:
                    await self._registry_discard(candidate, payload.actor, payload.reason)
                except FeedbackError as exc:
                    raise exc
                feedback.status = "discarded"
                feedback.resolved_at = _now()
                feedback.updated_at = _now()
                _message(feedback, "agent", f"候选已丢弃：{payload.reason}")
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
            if verification.requires_confirmation and not payload.confirm_accepted_change:
                raise FeedbackError(
                    "ACCEPTED_REGION_CHANGED",
                    "accepted fields changed; set confirm_accepted_change=true to apply",
                    409,
                )
            stable = await self._registry_resolve(candidate.recipe_id, "stable")
            regression = regression_gate(
                os.getenv(
                    "HANSON_REGRESSION_BASELINE",
                    "services/orchestration/data/feedback/regression-baseline.json",
                ),
                os.getenv(
                    "HANSON_REGRESSION_CURRENT",
                    "services/orchestration/data/feedback/regression-current.json",
                ),
            )
            if not regression["passed"]:
                raise FeedbackError(
                    "REGRESSION_FAILED",
                    f"promotion blocked: {regression['detail']}",
                    409,
                )
            await self._registry_promote(
                candidate,
                payload.actor,
                payload.reason or "feedback approval",
                channel="shadow",
            )
            batch = await self._start_shadow(feedback, candidate, stable)
            feedback.status = "shadow"
            feedback.updated_at = _now()
            _message(
                feedback,
                "agent",
                (
                    f"已将 {candidate.recipe_id}@{candidate.candidate_version} "
                    f"提升到 shadow 通道；"
                    f"待 {batch.get('required_documents')} 份文档验证通过后自动晋升。"
                ),
            )
            session.add(
                Promotion(
                    feedback_id=feedback.id,
                    recipe_id=candidate.recipe_id,
                    from_version=stable.get("version", candidate.base_version),
                    to_version=candidate.candidate_version,
                    channel="shadow",
                    action="promote",
                    actor=payload.actor,
                    note=payload.reason,
                )
            )
            if run is not None:
                await _append_event(
                    session,
                    run,
                    "feedback.shadow",
                    "feedback",
                    "shadow",
                    {
                        "feedback_id": feedback.id,
                        "recipe_id": candidate.recipe_id,
                        "from_version": stable.get("version", candidate.base_version),
                        "to_version": candidate.candidate_version,
                        "shadow_batch_id": batch.get("id"),
                        "actor": payload.actor,
                    },
                )
            await session.commit()
            applied_run_id = await self._apply_recipe_run(feedback, candidate)
            if applied_run_id:
                async with SessionLocal() as session:
                    row = await session.get(Feedback, feedback_id)
                    if row is not None:
                        root = row.root_cause if isinstance(row.root_cause, dict) else {}
                        row.root_cause = {**root, "applied_run_id": applied_run_id}
                        row.updated_at = _now()
                        _message(
                            row,
                            "agent",
                            f"已应用修复结果，新运行 {applied_run_id[:8]} 正在解析。",
                        )
                        await session.commit()
                        feedback = row
            if batch.get("id"):
                shadow_service.schedule(str(batch["id"]))
            if document_id and verification.accepted_fields:
                try:
                    await save_snapshot_from_verification(
                        verification,
                        document_id=document_id,
                        document_version=document_version,
                        run_id=feedback.run_id,
                        feedback_id=feedback.id,
                        actor=payload.actor,
                    )
                except Exception:  # noqa: BLE001 - promotion already committed
                    logger.exception(
                        "failed to save accepted snapshot for feedback %s", feedback.id
                    )
            return _detail(feedback)

    async def _apply_recipe_run(
        self, feedback: Feedback, candidate: CandidateRef
    ) -> str:
        """用户应用配方修复后，用候选版本派生一个可查看的运行。"""
        async with SessionLocal() as session:
            original = await session.get(Run, feedback.run_id)
        if original is None or not candidate.candidate_version:
            return ""
        idempotency = f"candidate-{feedback.id}"
        async with SessionLocal() as session:
            existing = (
                await session.execute(
                    select(Run).where(Run.idempotency_key == idempotency)
                )
            ).scalars().first()
            if existing is not None:
                return existing.id
            artifacts = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id == original.id)
                )
            ).scalars().all()
            run = Run(
                document_id=original.document_id,
                document_version=original.document_version,
                status="RECEIVED",
                stage="RECEIVED",
                trace_id=str(uuid4()),
                recipe_channel="candidate",
                parser_version=original.parser_version,
                idempotency_key=idempotency,
                repair_of=original.id,
                repair_attempt=(original.repair_attempt or 0) + 1,
                recipe_override={
                    "recipe_id": candidate.recipe_id,
                    "candidate_version": candidate.candidate_version,
                    "digest": candidate.digest,
                },
            )
            session.add(run)
            await session.flush()
            for artifact in artifacts:
                if artifact.role not in OCR_ARTIFACT_ROLES:
                    continue
                session.add(
                    Artifact(
                        run_id=run.id,
                        role=artifact.role,
                        storage_key=artifact.storage_key,
                        sha256=artifact.sha256,
                        bytes=artifact.bytes,
                    )
                )
            await append_event(
                session,
                run,
                "run.created",
                "RECEIVED",
                "created",
                {
                    "document_id": original.document_id,
                    "source_run_id": original.id,
                    "feedback_id": feedback.id,
                    "repair": "l2_recipe_candidate",
                    "candidate_version": candidate.candidate_version,
                },
            )
            await session.commit()
            run_id = run.id
        schedule(run_id, skip_ocr=True)
        return run_id

    # -- context / agents -------------------------------------------------
    async def _context(
        self, run: Run, feedback: Feedback, target: dict[str, Any]
    ) -> dict[str, Any]:
        result_payload = await artifact_json(run.id, "result")
        records_payload = await artifact_json(run.id, "records")
        diagnostics_payload = await artifact_json(run.id, "diagnostics")
        result = result_payload or {}
        records = (records_payload or {}).get("records") or []
        diagnostics = (diagnostics_payload or {}).get("diagnostics") or []
        recipes = result.get("recipes") or []
        ocr_payload = await artifact_json(run.id, "ocr") or {}
        tables = merge_tables(
            result.get("tables") or [],
            ocr_payload.get("tables") or [],
        )
        intent = resolve_intent(
            feedback.description or "",
            tables,
            records,
            diagnostics,
            target=target,
        )
        if needs_rerank(intent):
            intent = await self._rerank_intent(feedback, intent, tables)
        feedback_input = {**_feedback_input(feedback), "feedback_id": feedback.id}
        # 文档级门禁没有 table_id 时先定位真正失败的表，再用该表的配方修复；
        # 否则会默认拿 result.recipes[0]，对多配方文档属于修错对象。
        target_table_hint = choose_target_table(
            feedback=feedback_input,
            tables=tables,
            diagnostics=diagnostics,
            records=records,
            intent=intent,
        )
        target_recipe_id = str(
            target.get("recipe_id")
            or target_table_hint.get("recipe_id")
            or ""
        )
        if not target_recipe_id and recipes:
            target_recipe_id = str(recipes[0].get("recipe_id") or "")
        if not target_recipe_id and not str(target.get("rule_id") or "").startswith(
            "DOC-"
        ):
            raise FeedbackError("RECIPE_NOT_RESOLVED", "cannot determine target recipe")
        if target_recipe_id:
            stable = await self._registry_resolve(target_recipe_id, "stable")
            manifest = await self._registry_get(
                f"/internal/recipes/{target_recipe_id}/versions/{stable['version']}"
            )
        else:
            # 文档级门禁可能来自未命中任何配方的文档（例如整篇 0 表格）。
            # 这类反馈由 agent 判定为 ocr/engine 层处理，不绑定配方。
            stable = {}
            manifest = {}
        repair_context = build_repair_context(
            feedback=feedback_input,
            tables=tables,
            records=records,
            diagnostics=diagnostics,
            recipe=manifest,
            intent=intent,
        )
        diagnosis = diagnose(
            intent=intent,
            repair_context=repair_context,
            tables=tables,
            records=records,
            diagnostics=diagnostics,
            pages=ocr_payload.get("pages") or [],
            description=feedback.description or "",
        )
        if needs_model_attribution(diagnosis):
            diagnosis = await self._attribute_diagnosis(
                feedback,
                intent,
                diagnosis,
                repair_context,
                tables,
                records,
                diagnostics,
            )
        if diagnosis.get("expected"):
            repair_context.setdefault("problem", {})["expected"] = diagnosis["expected"]
        target_table = next(
            (
                item
                for item in tables
                if str(item.get("table_id") or "")
                == str(
                    ((repair_context.get("problem") or {}).get("target") or {}).get(
                        "table_id"
                    )
                    or ""
                )
            ),
            {},
        )
        rule_id = str(((repair_context.get("task") or {}).get("rule_id")) or "")
        try:
            fingerprint = header_fingerprint(target_table)
            similar = (
                CaseStore().find(
                    fingerprint, str(intent.get("concept_id") or "")
                )
                if fingerprint
                else []
            )
            overlay = (
                OverlayStore().find(fingerprint, rule_id=rule_id)
                if fingerprint
                else []
            )
        except Exception:  # noqa: BLE001 - memory is best effort
            similar = []
            overlay = []
        repair_context.setdefault("history", {})["similar_cases"] = similar
        repair_context["history"]["learned_overlay"] = {
            "entries": len(overlay),
            "rule_id": rule_id,
        }
        reusable = {
            level: case
            for level in ("L1", "L2")
            if (
                case := select_reusable_case(
                    overlay + similar, rule_id=rule_id, level=level
                )
            )
        }
        repair_context["history"]["reusable_case"] = reusable
        repairability = evaluate_repairability(
            {
                "intent": intent,
                "diagnosis": diagnosis,
                "repair_context": repair_context,
            }
        )
        target_table_id = str(
            repair_context["problem"]["target"].get("table_id")
            or target.get("table_id")
            or ""
        )
        if not target_table_id and tables:
            target_table_id = str(tables[0].get("table_id") or "")
        target_table = next(
            (
                item
                for item in tables
                if str(item.get("table_id") or "") == target_table_id
            ),
            {},
        )
        return {
            "result": result,
            "records": records,
            "diagnostics": diagnostics,
            "tables": tables,
            "recipe": manifest,
            "stable": stable,
            "target_recipe_id": target_recipe_id,
            "target_table_id": target_table_id,
            "target_table": target_table,
            "intent": intent,
            "diagnosis": diagnosis,
            "repairability": repairability,
            "repair_context": repair_context,
            "run_summary": {
                "status": run.status,
                "stage": run.stage,
                "recipe_channel": run.recipe_channel,
                "records": len(records),
                "tables": len(tables),
                "table": _table_summary(target_table),
                "intent": intent,
                "diagnosis": diagnosis,
                "repairability": repairability,
                "repair_context_hash": repair_context.get("context_hash"),
                "diagnostics": diagnostics[:20],
            },
        }

    async def _rerank_intent(
        self,
        feedback: Feedback,
        intent: dict[str, Any],
        tables: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Ask the model to pick one table when rule scores are tied."""
        task = AgentTask(
            task_id=f"feedback-{feedback.id}-rerank",
            trace_id=feedback.run_id,
            role="intent_rerank",
            objective="Pick the single table the feedback refers to.",
            inputs={
                "utterance": feedback.description or "",
                "category": intent.get("category"),
                "scope": intent.get("scope"),
                "candidates": list(intent.get("candidate_targets") or [])[:5],
                "outline": [_outline_summary(table) for table in tables][:20],
            },
            output_schema={},
            tools=[],
            budget=self._task_budget(
                max_steps=1,
                max_tool_calls=0,
                max_tokens=4000,
                wall_time_seconds=min(60, settings.feedback_timeout_seconds),
            ),
        )
        result = await self._call_agent_optional(task)
        if result is None:
            return apply_rerank(
                intent, {"model_used": False, "reason": "agent unavailable"}
            )
        return apply_rerank(intent, result.output or {})

    async def _attribute_diagnosis(
        self,
        feedback: Feedback,
        intent: dict[str, Any],
        diagnosis: dict[str, Any],
        repair_context: dict[str, Any],
        tables: list[dict[str, Any]],
        records: list[dict[str, Any]],
        diagnostics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Ask the model for multi-cause attribution when rules are unsure."""
        table_id = str(
            ((repair_context.get("problem") or {}).get("target") or {}).get(
                "table_id"
            )
            or ""
        )
        table = next(
            (
                item
                for item in tables
                if str(item.get("table_id") or "") == table_id
            ),
            {},
        )
        task = AgentTask(
            task_id=f"feedback-{feedback.id}-diagnosis",
            trace_id=feedback.run_id,
            role="diagnosis",
            objective="Attribute the feedback to one root cause with evidence.",
            inputs={
                "feedback": _feedback_input(feedback),
                "intent": intent,
                "rule_id": str(
                    (repair_context.get("task") or {}).get("rule_id") or ""
                ),
                "rule_diagnosis": diagnosis,
                "table": _table_summary(table),
                "diagnostics": diagnostics[:20],
                "records": _tool_records(records, table_id, limit=5),
            },
            output_schema={},
            tools=[],
            budget=self._task_budget(
                max_steps=1,
                max_tool_calls=0,
                max_tokens=4000,
                wall_time_seconds=min(60, settings.feedback_timeout_seconds),
            ),
        )
        result = await self._call_agent_optional(task)
        output = result.output if result is not None else {"model_used": False}
        return merge_model_diagnosis(diagnosis, output or {}, table_id=table_id)

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
                "intent": context.get("intent") or {},
                "diagnosis": context.get("diagnosis") or {},
            },
            output_schema={},
            tools=[],
            budget=self._task_budget(
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
        table_id = str(context.get("target_table_id") or "")
        diagnostics = [
            item
            for item in context.get("diagnostics") or []
            if not table_id
            or str((item.get("detail") or {}).get("table_id") or "") == table_id
        ][:20]
        task = AgentTask(
            task_id=f"feedback-{feedback.id}-repair",
            trace_id=feedback.run_id,
            role="repair",
            objective="Propose a minimal recipe candidate patch and test plan.",
            inputs={
                "feedback": _feedback_input(feedback),
                "triage": triage.model_dump(mode="json"),
                "recipe": context["recipe"],
                "diagnostics": diagnostics,
                "table": _table_summary(context.get("target_table") or {}),
                "intent": context.get("intent") or {},
                "diagnosis": context.get("diagnosis") or {},
                "repair_context": context.get("repair_context") or {},
                "tables": _tool_tables(
                    context.get("tables") or [],
                    str(context.get("target_table_id") or ""),
                ),
                "records": _tool_records(
                    context.get("records") or [],
                    str(context.get("target_table_id") or ""),
                ),
            },
            output_schema={},
            tools=["get_table", "get_records"],
            budget=self._task_budget(
                max_steps=4,
                max_tool_calls=3,
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
        if self._auto_budget is not None:
            if self._budget_remaining_tokens() < 1024:
                raise FeedbackBudgetExceeded(
                    "auto repair token budget exhausted; routed to human"
                )
            if self._budget_remaining_seconds() <= 0:
                raise FeedbackBudgetExceeded(
                    "auto repair time budget exhausted; routed to human"
                )
        url = f"{settings.agent_url.rstrip('/')}/internal/agent:run"
        timeout = settings.feedback_timeout_seconds
        if self._auto_budget is not None:
            timeout = max(1.0, min(timeout, self._budget_remaining_seconds()))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
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
        self._used_tokens += int(result.usage.total_tokens or 0)
        self._agent_calls += 1
        if result.status != "completed":
            raise FeedbackError(
                "AGENT_FAILED",
                result.error_message or f"agent finished with {result.status}",
                502,
            )
        return result

    async def _call_agent_optional(self, task: AgentTask) -> AgentResult | None:
        """Optional model pass: never fail the feedback because of it."""
        try:
            return await self._call_agent(task)
        except FeedbackError as exc:
            logger.info("optional agent %s skipped: %s", task.role, exc)
            return None

    # -- candidate / verification -----------------------------------------
    async def _build_candidate(
        self,
        feedback: Feedback,
        context: dict[str, Any],
        proposal: RepairProposal,
    ) -> CandidateRef:
        recipe_id = context["target_recipe_id"]
        stable_version = str(context["recipe"].get("version") or "")
        if not stable_version:
            raise FeedbackError("RECIPE_NOT_RESOLVED", "base recipe version missing")
        info = await self._registry_get(f"/internal/recipes/{recipe_id}")
        # 已有待确认 candidate 时以它为基线，后续反馈在同一个 candidate 上增量叠加。
        base_version = str((info.get("channels") or {}).get("candidate") or stable_version)
        previous = await self._candidate_for_version(feedback, recipe_id, base_version)
        chain = next_patch_chain(
            previous.patch_chain if previous is not None else None,
            previous.candidate_version if previous is not None else "",
            feedback.id,
            base_version,
        )
        existing = {
            str(item.get("version"))
            for item in info.get("versions") or []
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
            patch_chain=chain,
        )

    async def _candidate_for_version(
        self, feedback: Feedback, recipe_id: str, version: str
    ) -> CandidateRef | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Feedback)
                .where(Feedback.id != feedback.id)
                .order_by(Feedback.updated_at.desc())
                .limit(100)
            )
            rows = result.scalars().all()
        for row in rows:
            if not row.candidate:
                continue
            try:
                candidate = CandidateRef.model_validate(row.candidate)
            except ValueError:
                continue
            if candidate.recipe_id == recipe_id and candidate.candidate_version == version:
                return candidate
        return None

    async def _verify(
        self,
        feedback: Feedback,
        context: dict[str, Any],
        candidate: CandidateRef,
    ) -> VerificationPackage:
        target = feedback.target or {}
        measure = str(target.get("measure") or "")
        rule_id = str(target.get("rule_id") or "")
        level = str(target.get("level") or ("field" if measure else "document"))
        async with SessionLocal() as session:
            run = await session.get(Run, feedback.run_id)
            if run is None:
                raise FeedbackError("RUN_NOT_FOUND", "run not found", 404)
        accepted = await latest_snapshot(run.document_id)
        request = await build_sandbox_request(
            run,
            recipe_override=RecipeRef(
                recipe_id=candidate.recipe_id,
                version=candidate.candidate_version,
                digest=candidate.digest,
            ),
            table_id=None if level == "document" else context.get("target_table_id"),
        )
        result = await _call_sandbox(request)
        before_records = context["records"]
        before_diagnostics = context["diagnostics"]
        label = measure or rule_id or "document"
        if result.status != "succeeded":
            return VerificationPackage(
                proposal_id=feedback.id,
                before_run=feedback.run_id,
                after_run=f"{feedback.run_id}:candidate",
                diff=VerificationDiff(),
                regression=RegressionStats(documents=1, new_errors=1),
                affected_targets=[
                    {"recipe_id": candidate.recipe_id, "target": label}
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
        after_diag_items = [
            item
            for item in (after_diagnostics.get("diagnostics") or [])
            if isinstance(item, dict)
        ]
        if measure:
            added, removed, changed = _field_diff(before_map, after_map, measure)
            target_fixed = bool(added or changed)
        else:
            added, removed, changed = _document_diff(before_map, after_map)
            target_fixed = _document_target_fixed(
                rule_id,
                before_records,
                list(after_map.values()),
                before_diagnostics,
                after_diag_items,
            )
        before_errors = sum(
            1 for item in before_diagnostics if item.get("severity") == "error"
        )
        after_errors = sum(
            1 for item in after_diag_items if item.get("severity") == "error"
        )
        new_errors = max(0, after_errors - before_errors)
        acceptance = (
            ((context.get("repair_context") or {}).get("task") or {}).get("acceptance")
            or {}
        )
        after_list = list(after_map.values())
        coverage_text = _coverage_text(context)
        before_coverage = compute_coverage(before_records, text=coverage_text)
        after_coverage = compute_coverage(after_list, text=coverage_text)
        metric = str(acceptance.get("metric") or "")
        if metric == "complete_items":
            target_fixed = (
                after_coverage["complete_rows"] > before_coverage["complete_rows"]
            )
        elif metric == "required_items":
            target_fixed = (
                after_coverage["required_present"]
                > before_coverage["required_present"]
            )
        required_no_loss = True
        if metric in {"complete_items", "required_items"}:
            required_no_loss = (
                after_coverage["required_present"]
                >= before_coverage["required_present"]
            )
        gate = evaluate_gates(
            target_fixed=target_fixed,
            new_errors=new_errors,
            removed=bool(removed),
            evidence_grounded=bool((context.get("diagnosis") or {}).get("evidence"))
            or bool(acceptance),
            reproduced=_reproduced(
                before_records, before_diagnostics, acceptance, context
            ),
            required_no_loss=required_no_loss,
            iterations=int(context.get("attempt") or 1),
            acceptance=acceptance,
        )
        passed = gate["decision"] == "accept"
        artifacts = [
            item.storage_key for item in result.outputs.values() if item.storage_key
        ]
        changed_in_accepted = diff_against_snapshot(accepted, after_list)
        accepted_tables, accepted_fields = accepted_scope(after_list)
        requires_confirmation = bool(changed_in_accepted)
        summary = (
            f"目标 {label}："
            f"{'已修复' if target_fixed else '未修复'}；"
            f"新增错误 {new_errors} 条；门禁 {gate['decision']}。"
        )
        action = classify_action(
            level="L2",
            ops=list((candidate.patch or {}).get("ops") or []),
        )
        if changed_in_accepted:
            summary += (
                f" {len(changed_in_accepted)} 个已接受字段发生变化，"
                "需要用户确认。"
            )
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
                    "target": label,
                    "level": level,
                    "table_id": context.get("target_table_id"),
                    "patch_chain": list(candidate.patch_chain),
                }
            ],
            user_summary=summary,
            artifacts=artifacts,
            passed=passed,
            record_count=len(after_list),
            records_digest=records_digest(after_list),
            accepted_tables=accepted_tables,
            accepted_fields=accepted_fields,
            field_digests=field_digests(after_list),
            changed_in_accepted=changed_in_accepted,
            requires_confirmation=requires_confirmation,
            checks=gate["checks"],
            decision=gate["decision"],
            action_tier=action["tier"],
            coverage_before=summarize_coverage(before_coverage),
            coverage_after=summarize_coverage(after_coverage),
            after_diagnostics=_diagnostic_summary(after_diag_items),
        )

    # -- document-level metadata repair ------------------------------------
    async def _process_document_rule(
        self,
        feedback_id: str,
        feedback: Feedback,
        triage: TriageDecision,
        context: dict[str, Any],
    ) -> FeedbackDetail:
        """按检验表/正文证据补齐试验方法或取样，并派生新运行。"""
        intent = context.get("intent") or {}
        subject = str(intent.get("subject") or intent.get("concept") or "")
        field = str(intent.get("field") or "试验方法")
        records = context.get("records") or []
        table_id = str(context.get("target_table_id") or "")
        profile = str((context.get("target_table") or {}).get("profile") or "")
        table_id, profile = _resolve_record_scope(records, subject, table_id, profile)
        async with SessionLocal() as session:
            run = await session.get(Run, feedback.run_id)
        if run is None:
            return await self._needs_more_info(
                feedback_id, "原运行不存在，无法定位证据。", triage=triage
            )
        inventory = await artifact_json(run.id, "inventory")
        evidence = find_method_evidence(inventory, subject, field)
        if not evidence:
            engine_triage = triage.model_copy(
                update={
                    "root_cause": "extraction_rule",
                    "repair_scope": "engine",
                    "summary": "文档级字段缺失，需要解析器规则修复",
                }
            )
            return await self._process_engine(
                feedback_id, feedback, engine_triage, context
            )
        override = build_metadata_override(table_id, profile, evidence)
        preview = copy.deepcopy(records)
        if not apply_metadata_override(preview, override):
            return await self._needs_more_info(
                feedback_id,
                f"当前结果已包含{field or '该字段'}，未发现缺失。",
                triage=triage,
            )
        applied_run_id = await self._apply_metadata_repair(
            feedback, override, table_id
        )
        summary = "；".join(f"{key}={value}" for key, value in evidence.items())
        async with SessionLocal() as session:
            stored = await session.get(Feedback, feedback_id)
            if stored is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            stored.triage = triage.model_dump(mode="json")
            stored.proposal = {
                "root_cause": "extraction_rule",
                "scope": "data",
                "summary": f"按检验表补齐{field}：{summary}",
                "document_repair": override,
                "needs_human": False,
                "confidence": 0.8,
            }
            stored.verification = {}
            stored.candidate = {}
            stored.root_cause = {
                **_root_cause_payload(triage, context),
                "document_repair": override,
                "applied_run_id": applied_run_id,
            }
            stored.status = "applied"
            stored.updated_at = _now()
            _message(
                stored,
                "agent",
                (
                    f"已按检验表/正文补齐{field}（{summary}）；"
                    f"新运行 {applied_run_id[:8]} 正在解析。"
                ),
            )
            await session.commit()
            return _detail(stored)

    async def _apply_metadata_repair(
        self,
        feedback: Feedback,
        override: dict[str, Any],
        table_id: str,
    ) -> str:
        """派生新运行，并在审查阶段应用文档级元数据覆盖。"""
        async with SessionLocal() as session:
            original = await session.get(Run, feedback.run_id)
        if original is None:
            return ""
        data = json.dumps(override, ensure_ascii=False, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        key = f"runs/{original.id}/l1/{feedback.id}-metadata.json"
        await get_store().put_bytes(key, data, "application/json")
        idempotency = f"meta-{feedback.id}"
        async with SessionLocal() as session:
            existing = (
                await session.execute(
                    select(Run).where(Run.idempotency_key == idempotency)
                )
            ).scalars().first()
            if existing is not None:
                return existing.id
            artifacts = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id == original.id)
                )
            ).scalars().all()
            run = Run(
                document_id=original.document_id,
                document_version=original.document_version,
                status="RECEIVED",
                stage="RECEIVED",
                trace_id=str(uuid4()),
                recipe_channel=original.recipe_channel,
                parser_version=original.parser_version,
                idempotency_key=idempotency,
                repair_of=original.id,
                repair_attempt=(original.repair_attempt or 0) + 1,
                recipe_override=original.recipe_override,
            )
            session.add(run)
            await session.flush()
            for artifact in artifacts:
                if artifact.role not in OCR_ARTIFACT_ROLES:
                    continue
                session.add(
                    Artifact(
                        run_id=run.id,
                        role=artifact.role,
                        storage_key=artifact.storage_key,
                        sha256=artifact.sha256,
                        bytes=artifact.bytes,
                    )
                )
            session.add(
                Artifact(
                    run_id=run.id,
                    role="metadata_override",
                    storage_key=key,
                    sha256=digest,
                    bytes=len(data),
                )
            )
            await append_event(
                session,
                run,
                "run.created",
                "RECEIVED",
                "created",
                {
                    "document_id": original.document_id,
                    "source_run_id": original.id,
                    "feedback_id": feedback.id,
                    "repair": "document_metadata",
                    "table_id": table_id,
                    "fields": override.get("fields") or {},
                },
            )
            await session.commit()
            run_id = run.id
        schedule(run_id, skip_ocr=True)
        return run_id

    # -- L3 code proposal + verification ----------------------------------
    async def _process_engine(
        self,
        feedback_id: str,
        feedback: Feedback,
        triage: TriageDecision,
        context: dict[str, Any],
        *,
        proposal: RepairProposal | None = None,
    ) -> FeedbackDetail:
        """生成解析器代码方案：安全门禁 → 沙箱验证 → 等待用户应用。"""
        if proposal is None:
            proposal = await self._repair(feedback, triage, context)
        if proposal.scope != "engine" or proposal.needs_human:
            return await self._needs_more_info(
                feedback_id,
                "未能生成可验证的解析器代码方案，需要人工处理。",
                triage=triage,
                proposal=proposal,
            )
        proposal = apply_code_gate(proposal)
        guard = proposal.guard
        if guard is None or not guard.passed:
            detail = violation_summary(guard) if guard else "补丁为空"
            return await self._needs_more_info(
                feedback_id,
                f"L3 代码方案未通过安全门禁：{detail}",
                triage=triage,
                proposal=proposal,
            )
        verification, candidate_version = await self._verify_code_proposal(
            feedback, proposal, context
        )
        root_cause = _root_cause_payload(triage, context)
        if candidate_version:
            root_cause["code_candidate_version"] = candidate_version
        async with SessionLocal() as session:
            stored = await session.get(Feedback, feedback_id)
            if stored is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            stored.triage = triage.model_dump(mode="json")
            stored.proposal = proposal.model_dump(mode="json")
            stored.verification = verification.model_dump(mode="json")
            stored.root_cause = root_cause
            stored.status = "verified" if verification.passed else "needs_more_info"
            stored.updated_at = _now()
            _message(
                stored,
                "agent",
                (
                    "代码修复方案已通过安全门禁和沙箱验证；"
                    "点击“应用修复结果”后将发布到 shadow 通道。"
                    if verification.passed
                    else f"代码修复方案验证未通过：{verification.user_summary}"
                ),
            )
            await session.commit()
            return _detail(stored)

    async def _verify_code_proposal(
        self,
        feedback: Feedback,
        proposal: RepairProposal,
        context: dict[str, Any],
    ) -> tuple[VerificationPackage, str]:
        """发布临时解析包并用目标文档重跑，只把证据写回反馈。"""
        code_patch = proposal.code_patch
        if code_patch is None or not code_patch.files:
            return _failed_verification(feedback, "缺少代码文件"), ""
        version = await self._next_free_parser_version()
        manifest = build_code_asset_manifest(
            code_patch.model_dump(mode="json"), version=version
        )
        files = {item.path: item.content for item in code_patch.files}
        try:
            published = await self._registry_post(
                "/internal/assets", {"manifest": manifest, "files": files}
            )
            version = str(published.get("version") or version)
        except FeedbackError as exc:
            return _failed_verification(feedback, f"解析包发布失败：{exc}"), ""
        async with SessionLocal() as session:
            run = await session.get(Run, feedback.run_id)
        if run is None:
            return _failed_verification(feedback, "原运行不存在"), version
        try:
            request = await build_sandbox_request(run)
            request = request.model_copy(
                update={
                    "parser": ParserAssetRef(
                        asset_id=settings.parser_asset_id, version=version
                    )
                }
            )
            result = await _call_sandbox(request)
        except Exception as exc:  # noqa: BLE001 - 返回可读失败而不是 500
            return _failed_verification(feedback, f"沙箱执行失败：{exc}"), version
        if result.status != "succeeded":
            return (
                _failed_verification(
                    feedback, f"沙箱执行失败：{result.error_code}"
                ),
                version,
            )
        after_payload = await _output_json(result, "records")
        after_records = list(after_payload.get("records") or [])
        after_diag_payload = await _output_json(result, "diagnostics")
        after_diag = list(after_diag_payload.get("diagnostics") or [])
        before_records = list(context.get("records") or [])
        before_diag = list(context.get("diagnostics") or [])
        intent = context.get("intent") or {}
        field = str(intent.get("field") or "")
        before_filled = _field_filled_count(before_records, field)
        after_filled = _field_filled_count(after_records, field)
        before_errors = sum(
            1 for item in before_diag if item.get("severity") == "error"
        )
        after_errors = sum(
            1 for item in after_diag if item.get("severity") == "error"
        )
        no_loss = len(after_records) >= len(before_records)
        target_fixed = (
            after_filled > before_filled if field else len(after_records) > 0
        )
        passed = bool(no_loss and target_fixed and after_errors <= before_errors)
        label = field or "目标内容"
        summary = (
            f"L3 代码方案验证{'通过' if passed else '未通过'}："
            f"{label} {before_filled}→{after_filled}；"
            f"记录 {len(before_records)}→{len(after_records)}；"
            f"错误 {before_errors}→{after_errors}。"
        )
        checks = [
            {"name": "sandbox", "passed": True, "detail": version},
            {
                "name": "target_field",
                "passed": target_fixed,
                "detail": f"{label} {before_filled}→{after_filled}",
            },
            {
                "name": "no_data_loss",
                "passed": no_loss,
                "detail": f"{len(before_records)}→{len(after_records)}",
            },
            {
                "name": "no_new_errors",
                "passed": after_errors <= before_errors,
                "detail": f"{before_errors}→{after_errors}",
            },
        ]
        verification = VerificationPackage(
            proposal_id=feedback.id,
            before_run=feedback.run_id,
            after_run=f"{feedback.run_id}:l3:{version}",
            regression=RegressionStats(
                documents=1,
                field_f1_delta=1.0 if target_fixed else 0.0,
                new_errors=max(0, after_errors - before_errors),
            ),
            affected_targets=[
                {
                    "recipe_id": str(context.get("target_recipe_id") or ""),
                    "measure": field,
                    "table_id": str(context.get("target_table_id") or ""),
                }
            ],
            user_summary=summary,
            artifacts=[
                item.storage_key
                for item in result.outputs.values()
                if item.storage_key
            ],
            passed=passed,
            checks=checks,
            decision="accept" if passed else "rollback",
        )
        return verification, version

    async def _next_free_parser_version(self) -> str:
        info = await self._registry_get("/internal/assets/parser/parser_core")
        versions = {
            str(item.get("version") or "")
            for item in (info.get("versions") or [])
            if isinstance(item, dict)
        }
        channels = info.get("channels") or {}
        base = str(channels.get("candidate") or channels.get("stable") or "1.0.0")
        version = next_patch_version(base)
        while version in versions:
            version = next_patch_version(version)
        return version

    # -- L1 table repair ---------------------------------------------------
    async def _process_l1(
        self,
        feedback_id: str,
        feedback: Feedback,
        triage: TriageDecision,
        context: dict[str, Any],
    ) -> FeedbackDetail:
        proposal = None
        verification = None
        clean: dict[str, Any] | None = None
        table_id = str(context.get("target_table_id") or "")
        reusable = (
            ((context.get("repair_context") or {}).get("history") or {}).get(
                "reusable_case"
            )
            or {}
        ).get("L1")
        for attempt in range(1, 3):
            if attempt == 1 and reusable:
                proposal = _proposal_from_case(reusable)
            else:
                proposal = await self._repair(feedback, triage, context)
            if proposal.needs_human:
                return await self._needs_more_info(
                    feedback_id,
                    "L1 表级修复方案需要人工处理。",
                    triage=triage,
                    proposal=proposal,
                )
            table_id, spec = extract_table_repair(proposal.patch, table_id)
            table = next(
                (
                    item
                    for item in context.get("tables") or []
                    if str(item.get("table_id") or "") == table_id
                ),
                context.get("target_table") or {},
            )
            clean, problems = validate_table_repair_spec(spec, table)
            if not clean:
                if attempt < 2:
                    self._remember_attempt(
                        context,
                        attempt,
                        proposal,
                        [],
                        (
                            "spec rejected: "
                            + "；".join(problems)
                            + "；allowed keys: header_rows, replace_rows, "
                            "patch_cells, delete_rows"
                        ),
                        reason="spec_rejected",
                    )
                    continue
                return await self._needs_more_info(
                    feedback_id,
                    "表级修复参数被拒绝：" + "；".join(problems),
                    triage=triage,
                    proposal=proposal,
                )
            if _same_table(table, apply_table_repair(table, clean)):
                if attempt < 2:
                    self._remember_attempt(
                        context,
                        attempt,
                        proposal,
                        [],
                        (
                            "spec is a no-op: repaired table is identical; "
                            "change header_rows/patch_cells or return needs_human"
                        ),
                        reason="no_op",
                    )
                    continue
                return await self._needs_more_info(
                    feedback_id,
                    "表级修复参数没有实际改动：修复后的表与原表一致。",
                    triage=triage,
                    proposal=proposal,
                )
            verification = await self._run_l1_table_repair(
                feedback, context, clean, table_id
            )
            if verification.passed:
                break
            if attempt < 2:
                self._remember_attempt(
                    context,
                    attempt,
                    proposal,
                    verification.checks,
                    verification.user_summary,
                    verification=verification,
                )
                continue
            break
        if verification is None or proposal is None or clean is None:
            return await self._needs_more_info(
                feedback_id,
                "L1 修复未能生成可执行的表级修复。",
                triage=triage,
            )
        applied_run_id = ""
        if verification.passed:
            self._remember_case(
                feedback,
                context,
                patch={"table_repair": {"table_id": table_id, "spec": clean}},
                level="L1",
                action_tier=verification.action_tier,
            )
            applied_run_id = await self._apply_l1_repair(
                feedback, clean, table_id
            )
        async with SessionLocal() as session:
            stored = await session.get(Feedback, feedback_id)
            if stored is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            stored.triage = triage.model_dump(mode="json")
            stored.proposal = {
                **proposal.model_dump(mode="json"),
                "table_repair": {"table_id": table_id, "spec": clean},
            }
            stored.candidate = {}
            stored.verification = verification.model_dump(mode="json")
            stored.root_cause = _root_cause_payload(triage, context)
            stored.status = "verified" if verification.passed else "needs_more_info"
            stored.updated_at = _now()
            if applied_run_id:
                stored.root_cause = {
                    **(stored.root_cause or {}),
                    "applied_run_id": applied_run_id,
                }
            _message(
                stored,
                "agent",
                (
                    f"L1 验证{'通过' if verification.passed else '未通过'}："
                    f"{verification.user_summary}"
                    + (
                        f"；已自动应用修复，新运行 {applied_run_id[:8]} 正在解析。"
                        if applied_run_id
                        else ""
                    )
                ),
            )
            await session.commit()
            return _detail(stored)

    async def _apply_l1_repair(
        self, feedback: Feedback, spec: dict[str, Any], table_id: str
    ) -> str:
        """自动应用 L1 表修复：用修复后的 OCR 派生新的解析运行。"""
        async with SessionLocal() as session:
            original = await session.get(Run, feedback.run_id)
        if original is None:
            return ""
        ocr = await artifact_json(original.id, "ocr")
        if not ocr:
            return ""
        repaired = apply_table_repair_to_ocr(ocr, table_id, spec)
        data = json.dumps(repaired, ensure_ascii=False, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        key = f"runs/{original.id}/l1/{feedback.id}-{digest[:12]}-apply.json"
        await get_store().put_bytes(key, data, "application/json")
        idempotency = f"l1-{feedback.id}"
        async with SessionLocal() as session:
            existing = (
                await session.execute(
                    select(Run).where(Run.idempotency_key == idempotency)
                )
            ).scalars().first()
            if existing is not None:
                return existing.id
            artifacts = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id == original.id)
                )
            ).scalars().all()
            run = Run(
                document_id=original.document_id,
                document_version=original.document_version,
                status="RECEIVED",
                stage="RECEIVED",
                trace_id=str(uuid4()),
                recipe_channel=original.recipe_channel,
                parser_version=original.parser_version,
                idempotency_key=idempotency,
                repair_of=original.id,
                repair_attempt=(original.repair_attempt or 0) + 1,
                recipe_override=original.recipe_override,
            )
            session.add(run)
            await session.flush()
            copied = 0
            for artifact in artifacts:
                if artifact.role not in OCR_ARTIFACT_ROLES:
                    continue
                if artifact.role == "ocr":
                    session.add(
                        Artifact(
                            run_id=run.id,
                            role="ocr",
                            storage_key=key,
                            sha256=digest,
                            bytes=len(data),
                        )
                    )
                else:
                    session.add(
                        Artifact(
                            run_id=run.id,
                            role=artifact.role,
                            storage_key=artifact.storage_key,
                            sha256=artifact.sha256,
                            bytes=artifact.bytes,
                        )
                    )
                copied += 1
            await append_event(
                session,
                run,
                "run.created",
                "RECEIVED",
                "created",
                {
                    "document_id": original.document_id,
                    "source_run_id": original.id,
                    "feedback_id": feedback.id,
                    "repair": "l1_table_repair",
                    "table_id": table_id,
                    "ocr_artifacts": copied,
                },
            )
            await session.commit()
            run_id = run.id
        schedule(run_id, skip_ocr=True)
        return run_id

    def _remember_attempt(
        self,
        context: dict[str, Any],
        attempt: int,
        proposal: RepairProposal,
        checks: list[dict[str, Any]],
        summary: str,
        *,
        verification: VerificationPackage | None = None,
        reason: str = "",
    ) -> None:
        history = (context.get("repair_context") or {}).setdefault("history", {})
        entry: dict[str, Any] = {
            "attempt": attempt,
            "patch": proposal.patch,
            "checks": checks,
            "verification": summary,
        }
        if reason:
            entry["reason"] = reason
        if verification is not None:
            entry["decision"] = verification.decision
            entry["coverage"] = {
                "before": verification.coverage_before,
                "after": verification.coverage_after,
                "delta": _coverage_delta(
                    verification.coverage_before, verification.coverage_after
                ),
            }
            if verification.after_diagnostics:
                entry["after_diagnostics"] = verification.after_diagnostics
        history.setdefault("previous_attempts", []).append(entry)

    async def _run_l1_table_repair(
        self,
        feedback: Feedback,
        context: dict[str, Any],
        spec: dict[str, Any],
        table_id: str,
    ) -> VerificationPackage:
        async with SessionLocal() as session:
            run = await session.get(Run, feedback.run_id)
        if run is None:
            raise FeedbackError("RUN_NOT_FOUND", "run not found", 404)
        ocr = await artifact_json(run.id, "ocr")
        if not ocr:
            raise FeedbackError("OCR_NOT_FOUND", "ocr artifact missing", 404)
        repaired = apply_table_repair_to_ocr(ocr, table_id, spec)
        data = json.dumps(repaired, ensure_ascii=False, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        key = f"runs/{run.id}/l1/{feedback.id}-{digest[:12]}.json"
        await get_store().put_bytes(key, data, "application/json")
        request = await build_sandbox_request(run, table_id=table_id)
        request = request.model_copy(
            update={"ocr": ObjectInput(storage_key=key, sha256=digest)}
        )
        result = await _call_sandbox(request)
        target = {"recipe_id": context.get("target_recipe_id"), "table_id": table_id}
        if result.status != "succeeded":
            return VerificationPackage(
                proposal_id=feedback.id,
                before_run=feedback.run_id,
                after_run=f"{feedback.run_id}:l1",
                regression=RegressionStats(documents=1, new_errors=1),
                affected_targets=[{**target, "level": "L1"}],
                user_summary=f"L1 沙箱执行失败：{result.error_code}",
                passed=False,
                checks=[
                    {
                        "name": "sandbox",
                        "passed": False,
                        "detail": result.error_code or "sandbox failed",
                    }
                ],
                decision="rollback",
            )
        after_records_payload = await _output_json(result, "records")
        after_diag_payload = await _output_json(result, "diagnostics")
        after_records = after_records_payload.get("records") or []
        after_diag = after_diag_payload.get("diagnostics") or []
        before_records = context.get("records") or []
        before_diag = context.get("diagnostics") or []
        scoped_before = [
            item
            for item in before_records
            if str(item.get("table_id") or "") == table_id
        ] or before_records
        scoped_after = [
            item
            for item in after_records
            if str(item.get("table_id") or "") == table_id
        ] or after_records
        before_map = {
            str(item.get("record_id")): item
            for item in scoped_before
            if isinstance(item, dict)
        }
        after_map = {
            str(item.get("record_id")): item
            for item in scoped_after
            if isinstance(item, dict)
        }
        added, removed, changed = _document_diff(before_map, after_map)
        rule_id = str(
            ((context.get("repair_context") or {}).get("task") or {}).get("rule_id")
            or ""
        )
        target_fixed = _document_target_fixed(
            rule_id, scoped_before, scoped_after, before_diag, after_diag
        )
        before_errors = sum(
            1 for item in before_diag if item.get("severity") == "error"
        )
        after_errors = sum(1 for item in after_diag if item.get("severity") == "error")
        new_errors = max(0, after_errors - before_errors)
        acceptance = (
            ((context.get("repair_context") or {}).get("task") or {}).get("acceptance")
            or {}
        )
        coverage_text = _coverage_text(context)
        before_coverage = compute_coverage(scoped_before, text=coverage_text)
        after_coverage = compute_coverage(scoped_after, text=coverage_text)
        metric = str(acceptance.get("metric") or "")
        if metric == "complete_items":
            target_fixed = (
                after_coverage["complete_rows"] > before_coverage["complete_rows"]
            )
        elif metric == "required_items":
            target_fixed = (
                after_coverage["required_present"]
                > before_coverage["required_present"]
            )
        required_no_loss = True
        if metric in {"complete_items", "required_items"}:
            required_no_loss = (
                after_coverage["required_present"]
                >= before_coverage["required_present"]
            )
        gate = evaluate_gates(
            target_fixed=target_fixed,
            new_errors=new_errors,
            removed=_semantic_removed(scoped_before, scoped_after),
            evidence_grounded=True,
            reproduced=True,
            required_no_loss=required_no_loss,
            iterations=1,
            acceptance=acceptance,
            level="L1",
        )
        summary = (
            f"L1 表 {table_id}："
            f"{'已修复' if target_fixed else '未修复'}；"
            f"新增错误 {new_errors} 条；门禁 {gate['decision']}。"
        )
        action = classify_action(level="L1", operator="table_repair.add")
        return VerificationPackage(
            proposal_id=feedback.id,
            before_run=feedback.run_id,
            after_run=f"{feedback.run_id}:l1:{digest[:12]}",
            diff=VerificationDiff(added=added, removed=removed, changed=changed),
            regression=RegressionStats(
                documents=1,
                field_f1_delta=1.0 if target_fixed else 0.0,
                new_errors=new_errors,
            ),
            affected_targets=[{**target, "level": "L1", "table_id": table_id}],
            user_summary=summary,
            artifacts=[item.storage_key for item in result.outputs.values() if item.storage_key],
            passed=gate["passed"],
            record_count=len(after_records),
            records_digest=records_digest(after_records),
            checks=gate["checks"],
            decision=gate["decision"],
            action_tier=action["tier"],
            coverage_before=summarize_coverage(before_coverage),
            coverage_after=summarize_coverage(after_coverage),
            after_diagnostics=_diagnostic_summary(after_diag),
        )

    def _remember_case(
        self,
        feedback: Feedback,
        context: dict[str, Any],
        *,
        patch: dict[str, Any],
        level: str,
        action_tier: str,
    ) -> None:
        table = context.get("target_table") or {}
        try:
            fingerprint = header_fingerprint(table)
            if not fingerprint:
                return
            CaseStore().remember(
                {
                    "fingerprint": fingerprint,
                    "concept_id": str(
                        (context.get("intent") or {}).get("concept_id") or ""
                    ),
                    "rule_id": str(
                        ((context.get("repair_context") or {}).get("task") or {}).get(
                            "rule_id"
                        )
                        or ""
                    ),
                    "level": level,
                    "operator": (
                        "table_repair.add" if level == "L1" else "recipe.binding_override"
                    ),
                    "patch": patch,
                    "root_cause": str(
                        (context.get("diagnosis") or {}).get("root_cause") or ""
                    ),
                    "action_tier": action_tier,
                    "feedback_id": feedback.id,
                    "verified_at": _iso(_now()),
                }
            )
        except Exception:  # noqa: BLE001 - memory is best effort
            logger.warning("failed to remember repair case", exc_info=True)

    # -- L3 code approval --------------------------------------------------
    async def approve_code(
        self, feedback_id: str, payload: CodeApprovalIn
    ) -> FeedbackDetail:
        """Human approval: publish the parser bundle to shadow, never stable."""
        async with SessionLocal() as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            proposal = RepairProposal.model_validate(feedback.proposal or {})
            verification = (
                VerificationPackage.model_validate(feedback.verification)
                if feedback.verification
                else None
            )
            feedback_ref = feedback.id
            root = feedback.root_cause if isinstance(feedback.root_cause, dict) else {}
            candidate_version = str(root.get("code_candidate_version") or "")
        proposal = apply_code_gate(proposal)
        blockers = code_release_blockers(
            proposal,
            confirm=payload.confirm,
            verification=verification,
            verification_id=payload.verification_id,
            feedback_id=feedback_ref,
        )
        if blockers:
            raise FeedbackError("CODE_RELEASE_BLOCKED", "；".join(blockers), 409)
        release = await self._publish_code_release(
            proposal, payload, version=candidate_version or None
        )
        applied_run_id = await self._apply_code_release_run(
            feedback, release["version"]
        )
        async with SessionLocal() as session:
            row = await session.get(Feedback, feedback_id)
            if row is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            root = row.root_cause if isinstance(row.root_cause, dict) else {}
            row.root_cause = {
                **root,
                "code_release": {**release, "actor": payload.actor, "reason": payload.reason},
                "applied_run_id": applied_run_id,
            }
            row.status = "promoted"
            row.updated_at = _now()
            _message(
                row,
                "agent",
                (
                    f"已应用修复结果：代码补丁 parser_core@{release['version']} "
                    f"已发布到 {release['channel']} 通道，稳定通道未变更；"
                    + (
                        f"新运行 {applied_run_id[:8]} 正在解析。"
                        if applied_run_id
                        else "请在 shadow 批次中继续验证。"
                    )
                ),
            )
            await session.commit()
            return _detail(row)

    async def _apply_code_release_run(
        self, feedback: Feedback, parser_version: str
    ) -> str:
        """用户应用代码修复后，用新解析包派生一个可查看的运行。"""
        async with SessionLocal() as session:
            original = await session.get(Run, feedback.run_id)
        if original is None or not parser_version:
            return ""
        idempotency = f"code-{feedback.id}"
        async with SessionLocal() as session:
            existing = (
                await session.execute(
                    select(Run).where(Run.idempotency_key == idempotency)
                )
            ).scalars().first()
            if existing is not None:
                return existing.id
            artifacts = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id == original.id)
                )
            ).scalars().all()
            run = Run(
                document_id=original.document_id,
                document_version=original.document_version,
                status="RECEIVED",
                stage="RECEIVED",
                trace_id=str(uuid4()),
                recipe_channel=original.recipe_channel,
                parser_version=parser_version,
                idempotency_key=idempotency,
                repair_of=original.id,
                repair_attempt=(original.repair_attempt or 0) + 1,
                recipe_override=original.recipe_override,
            )
            session.add(run)
            await session.flush()
            for artifact in artifacts:
                if artifact.role not in OCR_ARTIFACT_ROLES:
                    continue
                session.add(
                    Artifact(
                        run_id=run.id,
                        role=artifact.role,
                        storage_key=artifact.storage_key,
                        sha256=artifact.sha256,
                        bytes=artifact.bytes,
                    )
                )
            await append_event(
                session,
                run,
                "run.created",
                "RECEIVED",
                "created",
                {
                    "document_id": original.document_id,
                    "source_run_id": original.id,
                    "feedback_id": feedback.id,
                    "repair": "l3_code_release",
                    "parser_version": parser_version,
                },
            )
            await session.commit()
            run_id = run.id
        schedule(run_id, skip_ocr=True)
        return run_id

    async def _publish_code_release(
        self, proposal: RepairProposal, payload: CodeApprovalIn, *, version: str | None = None
    ) -> dict[str, Any]:
        info = await self._registry_get("/internal/assets/parser/parser_core")
        stable = str((info.get("channels") or {}).get("stable") or "1.0.0")
        digest = ""
        if version:
            # 验证阶段已经发布过同名版本，直接复用，避免重复发布。
            detail = await self._registry_get(
                f"/internal/assets/parser/parser_core/versions/{version}"
            )
            published_version = version
            digest = str((detail.get("manifest") or {}).get("checksum") or "")
        else:
            version = next_patch_version(stable)
            code_patch = (
                proposal.code_patch.model_dump(mode="json")
                if proposal.code_patch is not None
                else {}
            )
            manifest = build_code_asset_manifest(code_patch, version=version)
            files = {
                item.path: item.content for item in (proposal.code_patch.files or [])
            }
            published = await self._registry_post(
                "/internal/assets", {"manifest": manifest, "files": files}
            )
            published_version = str(published.get("version") or version)
            digest = str(published.get("digest") or "")
        await self._registry_post(
            f"/internal/assets/parser/parser_core/versions/"
            f"{published_version}/promote",
            {
                "channel": "shadow",
                "actor": payload.actor,
                "note": payload.reason or "用户应用修复结果：发布到 shadow",
            },
        )
        return {
            "kind": "parser",
            "asset_id": "parser_core",
            "version": published_version,
            "digest": digest,
            "from_version": stable,
            "channel": "shadow",
        }

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
        self,
        candidate: CandidateRef,
        actor: str,
        note: str,
        *,
        channel: str = "stable",
    ) -> None:
        await self._registry_post(
            f"/internal/recipes/{candidate.recipe_id}/versions/"
            f"{candidate.candidate_version}/promote",
            {"channel": channel, "actor": actor, "note": note},
        )

    async def _start_shadow(
        self,
        feedback: Feedback,
        candidate: CandidateRef,
        stable: dict[str, Any],
    ) -> dict[str, Any]:
        """审批通过后进入 shadow 灰度，连续 N 份文档无回退再晋升 stable。"""
        batch = await shadow_service.create_batch(
            recipe_id=candidate.recipe_id,
            from_version=str(stable.get("version") or candidate.base_version),
            candidate_version=candidate.candidate_version,
            feedback_id=feedback.id,
            actor="shadow",
            note=f"feedback approval: {feedback.id}",
        )
        return batch

    async def _registry_discard(
        self, candidate: CandidateRef, actor: str, reason: str
    ) -> None:
        await self._registry_post(
            f"/internal/recipes/{candidate.recipe_id}/versions/"
            f"{candidate.candidate_version}/discard",
            {"actor": actor, "reason": reason},
        )

    # -- state helpers ----------------------------------------------------
    async def _clarify(
        self, feedback_id: str, intent: dict[str, Any]
    ) -> FeedbackDetail:
        """Stop before triage/repair and ask one question with options."""
        question = str(intent.get("clarifying_question") or "").strip()
        async with SessionLocal() as session:
            row = await session.get(Feedback, feedback_id)
            if row is None:
                raise FeedbackError("FEEDBACK_NOT_FOUND", "feedback not found", 404)
            row.root_cause = {
                "intent": _intent_summary(intent),
                "clarification": intent.get("clarification") or {},
                "suggestions": build_suggestions(intent=intent),
            }
            row.status = "needs_more_info"
            row.updated_at = _now()
            _message(
                row,
                "agent",
                f"需要澄清：{question}"
                if question
                else "需要澄清：请补充具体表或字段。",
            )
            await session.commit()
            return _detail(row)

    async def _store_root_cause(
        self,
        feedback_id: str,
        triage: TriageDecision,
        context: dict[str, Any],
    ) -> None:
        """Persist intent/diagnosis early so metrics survive later branches."""
        async with SessionLocal() as session:
            row = await session.get(Feedback, feedback_id)
            if row is None:
                return
            payload = _root_cause_payload(triage, context)
            payload["suggestions"] = build_suggestions(
                intent=context.get("intent") or {},
                diagnosis=context.get("diagnosis") or {},
                repairability=context.get("repairability") or {},
                repair_context=context.get("repair_context") or {},
            )
            row.root_cause = payload
            await session.commit()

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
                existing = (
                    feedback.root_cause
                    if isinstance(feedback.root_cause, dict)
                    else {}
                )
                if existing.get("intent") or isinstance(existing.get("triage"), dict):
                    feedback.root_cause = {
                        **existing,
                        "triage": triage.model_dump(mode="json"),
                    }
                else:
                    feedback.root_cause = {
                        "triage": triage.model_dump(mode="json")
                    }
            if proposal is not None:
                feedback.proposal = proposal.model_dump(mode="json")
            root = (
                feedback.root_cause
                if isinstance(feedback.root_cause, dict)
                else {}
            )
            existing = [
                dict(item)
                for item in (root.get("suggestions") or [])
                if isinstance(item, dict)
            ]
            feedback.root_cause = {
                **root,
                "suggestions": _suggestions_from_root(root, proposal) or existing,
            }
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
            _message(feedback, "agent", f"{code}：{message}")
            await session.commit()
            return _detail(feedback)


def next_patch_version(current: str) -> str:
    parts = str(current or "").split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
    return "1.0.0"


def code_release_blockers(
    proposal: RepairProposal,
    *,
    confirm: bool,
    verification: VerificationPackage | None = None,
    verification_id: str = "",
    feedback_id: str = "",
) -> list[str]:
    blockers: list[str] = []
    if not confirm:
        blockers.append("confirm 必须为 true")
    if proposal.scope != "engine":
        blockers.append("proposal scope 不是 engine")
    guard = proposal.guard
    if guard is None or not guard.passed:
        blockers.append("安全门未通过")
    if proposal.code_patch is None or not proposal.code_patch.files:
        blockers.append("缺少代码文件")
    if verification is None or not verification.passed:
        blockers.append("缺少通过的验证包")
    if not verification_id:
        blockers.append("缺少 verification_id")
    elif feedback_id and verification_id != feedback_id:
        blockers.append("verification_id 与 feedback 不匹配")
    if verification is not None and verification.regression.new_errors > 0:
        blockers.append("回归引入新错误")
    has_tests = bool(proposal.test_plan) or any(
        item.path.split("/")[-1].startswith("test_")
        for item in (proposal.code_patch.files if proposal.code_patch else [])
    )
    if not has_tests:
        blockers.append("缺少候选测试")
    return blockers


def build_code_asset_manifest(
    code_patch: dict[str, Any],
    *,
    version: str,
    kind: str = "parser",
    asset_id: str = "parser_core",
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for item in code_patch.get("files") or []:
        path = str(item.get("path") or "")
        if not path:
            continue
        content = str(item.get("content") or "")
        files.append(
            {
                "path": path,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
    entry_modules = [
        item["path"]
        for item in files
        if item["path"].endswith(".py")
        and not item["path"].split("/")[-1].startswith("test_")
    ][:3]
    tests = [
        item["path"]
        for item in files
        if item["path"].split("/")[-1].startswith("test_")
    ]
    return {
        "schema_version": "1.0",
        "kind": kind,
        "asset_id": asset_id,
        "version": version,
        "runtime_api": "sandbox-engine/1",
        "python": "3.12",
        "stdlib_only": True,
        "entry_modules": entry_modules,
        "files": files,
        "tests": tests,
    }


def _suggestions(feedback: Feedback) -> list[dict[str, Any]]:
    root = feedback.root_cause if isinstance(feedback.root_cause, dict) else {}
    return [
        dict(item)
        for item in (root.get("suggestions") or [])
        if isinstance(item, dict)
    ]


def _suggestions_from_root(
    root: dict[str, Any], proposal: RepairProposal | None = None
) -> list[dict[str, Any]]:
    target = root.get("target") or {}
    repair_context = {
        "problem": {"target": target},
        "recipe": {"unbound_columns": root.get("unbound_columns") or []},
        "constraints": {"admissible": root.get("admissible") or {}},
    }
    return build_suggestions(
        intent=root.get("intent") or {},
        diagnosis=root.get("diagnosis") or {},
        repairability=root.get("repairability") or {},
        repair_context=repair_context,
        proposal=proposal,
    )


def _proposal_from_case(case: dict[str, Any]) -> RepairProposal:
    level = str(case.get("level") or "L2")
    return RepairProposal(
        proposal_id=f"case-{case.get('feedback_id') or 'reuse'}",
        root_cause=str(case.get("root_cause") or "unknown"),  # type: ignore[arg-type]
        scope="data" if level == "L1" else "recipe",
        summary=(
            "Reuse verified case "
            f"{case.get('feedback_id') or ''} for the same table shape."
        ),
        patch=dict(case.get("patch") or {}),
        test_plan=["target reparse", "regression sample", "target metric check"],
        risk="low",
        needs_human=False,
        confidence=0.9,
    )


SUBJECT_PROFILES = {
    "化学成分": "chemical_composition",
    "室温拉伸": "mechanical_properties",
    "高温拉伸": "mechanical_properties",
    "弯曲": "mechanical_properties",
    "夏比冲击": "mechanical_properties",
    "冲击": "mechanical_properties",
}


def _resolve_record_scope(
    records: list[dict[str, Any]],
    subject: str,
    table_id: str,
    profile: str,
) -> tuple[str, str]:
    """当意图没有落到具体表时，按 subject 选择真正有记录的表。"""
    if any(str(item.get("table_id") or "") == table_id for item in records):
        return table_id, profile
    preferred = SUBJECT_PROFILES.get(subject, "")
    pool = [
        item
        for item in records
        if not preferred or str(item.get("profile") or "") == preferred
    ] or records
    if not pool:
        return table_id, profile
    return (
        str(pool[0].get("table_id") or table_id),
        str(pool[0].get("profile") or profile),
    )


def _intent_summary(intent: dict[str, Any]) -> dict[str, Any]:
    return {
        "concept_id": intent.get("concept_id"),
        "concept": intent.get("concept"),
        "subject": intent.get("subject"),
        "field": intent.get("field"),
        "measures": list(intent.get("measures") or [])[:8],
        "category": intent.get("category"),
        "verdict": intent.get("verdict"),
        "scope": intent.get("scope"),
        "confidence": intent.get("confidence"),
        "candidate_targets": [
            {
                "table_id": item.get("table_id"),
                "page_no": item.get("page_no"),
                "confidence": item.get("confidence"),
            }
            for item in (intent.get("candidate_targets") or [])[:5]
        ],
        "clarifying_question": intent.get("clarifying_question"),
        "clarification": intent.get("clarification"),
        "assumption": intent.get("assumption"),
        "rerank": intent.get("rerank") or {},
    }


def _root_cause_payload(
    triage: TriageDecision, context: dict[str, Any] | None
) -> dict[str, Any]:
    """Persist the intent/diagnosis summary used by the metrics report."""
    intent = (context or {}).get("intent") or {}
    diagnosis = (context or {}).get("diagnosis") or {}
    repair_context = (context or {}).get("repair_context") or {}
    target = (repair_context.get("problem") or {}).get("target") or {}
    return {
        "triage": triage.model_dump(mode="json"),
        "intent": _intent_summary(intent),
        "target": {
            "table_id": target.get("table_id"),
            "page_no": target.get("page_no"),
        },
        "unbound_columns": list(
            ((repair_context.get("recipe") or {}).get("unbound_columns")) or []
        ),
        "admissible": ((repair_context.get("constraints") or {}).get("admissible"))
        or {},
        "diagnosis": {
            "root_cause": diagnosis.get("root_cause"),
            "action": diagnosis.get("action"),
            "scope": diagnosis.get("scope"),
            "expected": diagnosis.get("expected"),
            "source": diagnosis.get("source"),
            "needs_model": diagnosis.get("needs_model"),
            "model_attribution": diagnosis.get("model_attribution") or {},
            "rule_change": diagnosis.get("rule_change"),
            "evidence_count": len(diagnosis.get("evidence") or []),
        },
        "repairability": (context or {}).get("repairability") or {},
    }


def _table_summary(table: dict[str, Any]) -> dict[str, Any]:
    headers = table_headers(table)
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    return {
        "table_id": str(table.get("table_id") or ""),
        "page_no": int(table.get("page_no") or 0),
        "caption": table.get("caption"),
        "profile": table.get("profile"),
        "orientation": table.get("orientation"),
        "headers": headers[:80],
        "header_paths": (table.get("header_paths") or [])[:4],
        "rows": rows[:5],
        "records": table.get("records"),
        "diagnostics": sorted(
            {
                str(item.get("code") or "")
                for item in table.get("diagnostics") or []
                if isinstance(item, dict)
            }
        ),
    }


def _outline_summary(table: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_id": str(table.get("table_id") or ""),
        "page_no": int(table.get("page_no") or 0),
        "caption": table.get("caption"),
        "profile": table.get("profile"),
        "headers": table_headers(table)[:20],
        "records": table.get("records"),
    }


def _coverage_text(context: dict[str, Any]) -> str:
    parts: list[str] = []
    for table in context.get("tables") or []:
        parts.append(str(table.get("caption") or ""))
        parts.extend(table_headers(table))
    return " ".join(parts)


def _same_table(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before_rows = before.get("rows") if isinstance(before.get("rows"), list) else []
    after_rows = after.get("rows") if isinstance(after.get("rows"), list) else []
    return (
        before.get("header_rows") == after.get("header_rows")
        and before_rows == after_rows
    )


def _semantic_removed(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> bool:
    """Record ids are row-index based; compare grade+condition to avoid false losses."""

    def key(record: dict[str, Any]) -> tuple[str, str] | None:
        grade = str(record.get("grade") or "").strip()
        if not grade or grade == "~":
            return None
        return (grade, str(record.get("condition_key") or ""))

    before_keys = {value for record in before if (value := key(record))}
    after_keys = {value for record in after if (value := key(record))}
    if before_keys or after_keys:
        return bool(before_keys - after_keys)
    return len(after) < len(before)


def _tool_tables(
    tables: list[dict[str, Any]],
    target_table_id: str = "",
    max_rows: int = 200,
) -> list[dict[str, Any]]:
    """Tool-facing table copies: full rows for the target table only.

    Large documents carry dozens of tables; shipping every row overflows the
    model context. Other tables keep metadata so the agent can call
    ``get_table`` when it actually needs them.
    """
    payload: list[dict[str, Any]] = []
    for table in tables:
        table_id = str(table.get("table_id") or "")
        rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        item: dict[str, Any] = {
            "table_id": table.get("table_id"),
            "page_no": table.get("page_no"),
            "caption": table.get("caption"),
            "profile": table.get("profile"),
            "orientation": table.get("orientation"),
            "n_rows": len(rows),
        }
        if not target_table_id or table_id == target_table_id:
            item.update(
                {
                    "header_paths": table.get("header_paths") or [],
                    "headers": table_headers(table)[:80],
                    "units": table.get("units") or [],
                    "rows": rows[:max_rows],
                    "truncated": len(rows) > max_rows,
                }
            )
        payload.append(item)
    return payload


def _tool_records(
    records: list[dict[str, Any]], table_id: str, limit: int = 300
) -> list[dict[str, Any]]:
    scoped = [
        item
        for item in records
        if not table_id or str(item.get("table_id") or "") == table_id
    ][:limit]
    return [
        {
            "record_id": item.get("record_id"),
            "table_id": item.get("table_id"),
            "grade": item.get("grade"),
            "condition_key": item.get("condition_key"),
            "properties": {
                name: {
                    "raw": (value or {}).get("raw"),
                    "unit": (value or {}).get("unit"),
                    "value": (value or {}).get("value"),
                }
                for name, value in (item.get("properties") or {}).items()
            },
        }
        for item in scoped
    ]


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


def _failed_verification(
    feedback: Feedback, reason: str
) -> VerificationPackage:
    return VerificationPackage(
        proposal_id=feedback.id,
        before_run=feedback.run_id,
        passed=False,
        regression=RegressionStats(documents=1, new_errors=1),
        user_summary=reason,
        checks=[{"name": "sandbox", "passed": False, "detail": reason}],
        decision="rollback",
    )


FIELD_ALIASES = {
    "取样": ("取样说明", "位置", "取样数量"),
    "取样说明": ("取样说明",),
    "取样位置": ("位置",),
    "取样数量": ("取样数量",),
}


def _field_filled_count(records: list[dict[str, Any]], field: str) -> int:
    if not field:
        return 0
    keys = FIELD_ALIASES.get(field, (field,))
    count = 0
    for record in records:
        for prop in (record.get("properties") or {}).values():
            if not isinstance(prop, dict):
                continue
            meta = prop.get("meta") or {}
            if any(str(meta.get(key) or "").strip() for key in keys):
                count += 1
                break
        else:
            conditions = record.get("conditions") or {}
            if any(str(conditions.get(key) or "").strip() for key in keys):
                count += 1
    return count


async def _output_json(result: Any, role: str) -> dict[str, Any]:
    output = result.outputs.get(role)
    if output is None:
        return {}
    data = await get_store().get_bytes(output.storage_key)
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else {}


def _field_diff(
    before_map: dict[str, dict[str, Any]],
    after_map: dict[str, dict[str, Any]],
    measure: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for record_id, after in after_map.items():
        before_value = ((before_map.get(record_id) or {}).get("properties") or {}).get(
            measure
        )
        after_value = (after.get("properties") or {}).get(measure)
        if after_value is not None and before_value is None:
            added.append({"record_id": record_id, "measure": measure, "after": after_value})
        elif after_value is not None and after_value != before_value:
            changed.append(
                {
                    "record_id": record_id,
                    "measure": measure,
                    "before": before_value,
                    "after": after_value,
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
    return added, removed, changed


def _document_diff(
    before_map: dict[str, dict[str, Any]],
    after_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    added = [{"record_id": rid} for rid in after_map if rid not in before_map]
    removed = [{"record_id": rid} for rid in before_map if rid not in after_map]
    changed = [
        {
            "record_id": rid,
            "before": len(before_map[rid].get("properties") or {}),
            "after": len(after_map[rid].get("properties") or {}),
        }
        for rid in after_map.keys() & before_map.keys()
        if (before_map[rid].get("properties") or {})
        != (after_map[rid].get("properties") or {})
    ]
    return added, removed, changed


def _document_target_fixed(
    rule_id: str,
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
    before_diagnostics: list[dict[str, Any]],
    after_diagnostics: list[dict[str, Any]],
) -> bool:
    if rule_id in {"DOC-NO-RECORDS", "DOC-LOW-COVERAGE"}:
        return len(after_records) > len(before_records)
    if rule_id == "DOC-UNBOUND-COLUMNS":
        return _diagnostic_count(
            after_diagnostics, "MEASURE_COLUMN_MISSING"
        ) < _diagnostic_count(before_diagnostics, "MEASURE_COLUMN_MISSING")
    if rule_id == "DOC-DUP-KEYS":
        return _duplicate_key_count(after_records) < _duplicate_key_count(before_records)
    if rule_id == "DOC-UNIT-MISSING":
        return _missing_unit_ratio(after_records) < _missing_unit_ratio(before_records)
    return len(after_records) > 0 and len(after_records) >= len(before_records)


def _diagnostic_count(diagnostics: list[dict[str, Any]], code: str) -> int:
    return sum(
        1
        for item in diagnostics
        if isinstance(item, dict) and item.get("code") == code
    )


ROW_CODES = {"ROW_SKIPPED", "ROW_KEY_NOT_FOUND", "EMPTY_RECORD_SKIPPED"}
ROW_SAMPLE_LIMIT = 30


def _diagnostic_summary(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    """Bounded after-run diagnostics for retry feedback."""
    counts: dict[str, int] = {}
    rows: dict[str, list[int]] = {}
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
        if code in ROW_CODES:
            index = (item.get("detail") or {}).get("row_index")
            if isinstance(index, int) and not isinstance(index, bool):
                bucket = rows.setdefault(code, [])
                if len(bucket) < ROW_SAMPLE_LIMIT:
                    bucket.append(index)
    return {"counts": counts, "rows": rows}


def _coverage_delta(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """Required-field coverage delta between attempts."""

    def _num(payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    delta = {
        "complete_rows": _num(after, "complete_rows") - _num(before, "complete_rows"),
        "required_present": _num(after, "required_present")
        - _num(before, "required_present"),
    }
    before_missing = {
        str(item.get("field") or "")
        for item in (before.get("missing") or [])
        if isinstance(item, dict)
    }
    after_missing = {
        str(item.get("field") or "")
        for item in (after.get("missing") or [])
        if isinstance(item, dict)
    }
    delta["resolved"] = sorted(before_missing - after_missing)
    delta["still_missing"] = sorted(after_missing)
    return delta


def _duplicate_key_count(records: list[dict[str, Any]], limit: int = 3) -> int:
    counts: dict[tuple[str, str, str], int] = {}
    for record in records:
        grade = str(record.get("grade") or "").strip()
        if not grade or grade == "~":
            continue
        condition = str(record.get("condition_key") or "")
        if not condition and record.get("conditions"):
            condition = json.dumps(
                record["conditions"], ensure_ascii=False, sort_keys=True
            )
        for name in record.get("properties") or {}:
            counts[(grade, name, condition)] = (
                counts.get((grade, name, condition), 0) + 1
            )
    return sum(count - limit for count in counts.values() if count > limit)


def _missing_unit_ratio(records: list[dict[str, Any]]) -> float:
    numeric = 0
    missing = 0
    for record in records:
        for value in (record.get("properties") or {}).values():
            if not isinstance(value, dict):
                continue
            number = value.get("value")
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                continue
            numeric += 1
            if not value.get("unit"):
                missing += 1
    return missing / numeric if numeric else 0.0


def _reproduced(
    before_records: list[dict[str, Any]],
    before_diagnostics: list[dict[str, Any]],
    acceptance: dict[str, Any],
    context: dict[str, Any],
) -> bool:
    metric = str(acceptance.get("metric") or "")
    table_id = str(
        (((context.get("repair_context") or {}).get("problem") or {}).get("target") or {}).get(
            "table_id"
        )
        or ""
    )
    if not metric:
        return True
    if metric == "records":
        return len(before_records) == int(acceptance.get("current") or 0)
    if metric == "MEASURE_COLUMN_MISSING":
        count = sum(
            1
            for item in before_diagnostics
            if item.get("code") == "MEASURE_COLUMN_MISSING"
            and (
                not table_id
                or str((item.get("detail") or {}).get("table_id") or "") == table_id
            )
        )
        return count == int(acceptance.get("current") or 0)
    return True


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
