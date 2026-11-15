"""Shadow 灰度：stable 与 candidate 对同一文档双跑，连续 N 份无回退后自动晋升 stable。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from hanson_contracts import AcceptedSnapshot, FeedbackMessage
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import (
    Artifact,
    AuditEvent,
    Document,
    Feedback,
    Promotion,
    Run,
    ShadowBatch,
    ShadowDocument,
    ShadowResult,
)
from .shadow_state import (
    ABANDONED,
    ACTIVE,
    EXPIRED,
    FAILED,
    PENDING,
    PROMOTED,
    READY,
    RUNNING,
    TERMINAL,
    WAITING,
    decide_batch_status,
)
from .snapshots import diff_against_snapshot, latest_snapshot
from .workflow import _call_sandbox, build_sandbox_request, get_store

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def _audit(
    session: Any,
    event_type: str,
    *,
    subject_id: str,
    actor: str,
    payload: dict[str, Any],
    subject_type: str = "recipe",
) -> None:
    """写入跨 run 审计事件（配方晋升/放弃/回滚）。"""
    session.add(
        AuditEvent(
            type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            actor=actor,
            payload=payload,
        )
    )


class ShadowError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value else ""


def _document_dict(row: ShadowDocument) -> dict[str, Any]:
    return {
        "document_id": row.document_id,
        "added_by": row.added_by,
        "note": row.note,
        "created_at": _iso(row.created_at),
    }


def _batch_dict(row: ShadowBatch, results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "recipe_id": row.recipe_id,
        "from_version": row.from_version,
        "candidate_version": row.candidate_version,
        "feedback_id": row.feedback_id,
        "status": row.status,
        "required_documents": row.required_documents,
        "completed": row.completed,
        "failed": row.failed,
        "metrics": row.metrics or {},
        "actor": row.actor,
        "note": row.note,
        "created_at": _iso(row.created_at),
        "deadline_at": _iso(row.deadline_at) or None,
        "finished_at": _iso(row.finished_at) or None,
        "auto_promote": settings.shadow_auto_promote,
        "results": results or [],
    }


def _result_dict(row: ShadowResult) -> dict[str, Any]:
    return {
        "document_id": row.document_id,
        "stable_run_id": row.stable_run_id,
        "shadow_run_id": row.shadow_run_id,
        "passed": row.passed,
        "metrics": row.metrics or {},
        "created_at": _iso(row.created_at),
    }


# -- shadow document set ---------------------------------------------------
async def list_documents() -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(ShadowDocument).order_by(ShadowDocument.created_at)
        )
        return [_document_dict(item) for item in result.scalars()]


async def add_document(
    document_id: str, actor: str = "operator", note: str = ""
) -> dict[str, Any]:
    async with SessionLocal() as session:
        if await session.get(Document, document_id) is None:
            raise ShadowError("DOCUMENT_NOT_FOUND", f"document not found: {document_id}", 404)
        row = await session.get(ShadowDocument, document_id)
        if row is None:
            row = ShadowDocument(document_id=document_id, added_by=actor, note=note)
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _document_dict(row)


async def remove_document(document_id: str) -> bool:
    async with SessionLocal() as session:
        row = await session.get(ShadowDocument, document_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


# -- comparison ------------------------------------------------------------
def compare_shadow(
    baseline_records: list[dict[str, Any]],
    candidate_records: list[dict[str, Any]],
    snapshot: AcceptedSnapshot | None,
    *,
    baseline_diagnostics: list[dict[str, Any]] | None = None,
    candidate_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """双跑对比：记录数不减少、已验收变化数不增加、error 数不增加。"""
    baseline_count = len(baseline_records)
    candidate_count = len(candidate_records)
    baseline_changed = len(diff_against_snapshot(snapshot, baseline_records))
    candidate_changed = len(diff_against_snapshot(snapshot, candidate_records))
    baseline_errors = _error_count(baseline_diagnostics or [])
    candidate_errors = _error_count(candidate_diagnostics or [])
    records_ok = candidate_count >= baseline_count
    accepted_ok = candidate_changed <= baseline_changed
    errors_ok = candidate_errors <= baseline_errors
    return {
        "baseline_records": baseline_count,
        "candidate_records": candidate_count,
        "baseline_accepted_changes": baseline_changed,
        "candidate_accepted_changes": candidate_changed,
        "baseline_errors": baseline_errors,
        "candidate_errors": candidate_errors,
        "records_ok": records_ok,
        "accepted_ok": accepted_ok,
        "errors_ok": errors_ok,
        "passed": records_ok and accepted_ok and errors_ok,
    }


def _error_count(diagnostics: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in diagnostics
        if isinstance(item, dict) and item.get("severity") == "error"
    )


# -- batches ---------------------------------------------------------------
async def create_batch(
    *,
    recipe_id: str,
    from_version: str,
    candidate_version: str,
    feedback_id: str | None = None,
    required_documents: int = 0,
    actor: str = "operator",
    note: str = "",
) -> dict[str, Any]:
    async with SessionLocal() as session:
        existing = await session.execute(
            select(ShadowBatch).where(
                ShadowBatch.recipe_id == recipe_id,
                ShadowBatch.candidate_version == candidate_version,
                ShadowBatch.status.in_(ACTIVE),
            )
        )
        row = existing.scalars().first()
        if row is not None:
            return _batch_dict(row)
        deadline = (
            _now() + timedelta(seconds=settings.shadow_timeout_seconds)
            if settings.shadow_timeout_seconds > 0
            else None
        )
        row = ShadowBatch(
            recipe_id=recipe_id,
            from_version=from_version,
            candidate_version=candidate_version,
            feedback_id=feedback_id,
            status=PENDING,
            required_documents=required_documents or settings.shadow_required_documents,
            actor=actor,
            note=note,
            deadline_at=deadline,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _batch_dict(row)


async def list_batches() -> list[dict[str, Any]]:
    await expire_stale_batches()
    async with SessionLocal() as session:
        result = await session.execute(
            select(ShadowBatch).order_by(ShadowBatch.created_at.desc())
        )
        return [_batch_dict(item) for item in result.scalars()]


async def get_batch(batch_id: str) -> dict[str, Any]:
    await expire_stale_batches(batch_id)
    async with SessionLocal() as session:
        row = await session.get(ShadowBatch, batch_id)
        if row is None:
            raise ShadowError("SHADOW_BATCH_NOT_FOUND", "shadow batch not found", 404)
        result = await session.execute(
            select(ShadowResult)
            .where(ShadowResult.batch_id == batch_id)
            .order_by(ShadowResult.created_at)
        )
        return _batch_dict(row, [_result_dict(item) for item in result.scalars()])


async def run_batch(batch_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        batch = await session.get(ShadowBatch, batch_id)
        if batch is None:
            raise ShadowError("SHADOW_BATCH_NOT_FOUND", "shadow batch not found", 404)
        if batch.status in TERMINAL:
            return await get_batch(batch_id)
        batch.status = RUNNING
        await session.commit()
        recipe_id = batch.recipe_id
        candidate_version = batch.candidate_version

    document_ids = [item["document_id"] for item in await list_documents()]
    for document_id in document_ids:
        if await _has_result(batch_id, document_id):
            continue
        outcome = await _run_document(recipe_id, candidate_version, document_id)
        if outcome is None:
            continue
        await _save_result(batch_id, document_id, outcome)

    await _refresh_counts(batch_id)
    return await _finalize(batch_id)


def schedule(batch_id: str) -> None:
    """后台执行 shadow 批次，HTTP 请求不阻塞等待全部双跑。"""
    task = asyncio.create_task(_run_safe(batch_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run_safe(batch_id: str) -> None:
    try:
        await run_batch(batch_id)
    except Exception:  # noqa: BLE001 - 后台任务失败需落库可查
        logger.exception("shadow batch failed: %s", batch_id)
        async with SessionLocal() as session:
            batch = await session.get(ShadowBatch, batch_id)
            if batch is not None:
                batch.status = FAILED
                batch.finished_at = _now()
                await session.commit()


async def _has_result(batch_id: str, document_id: str) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(
            select(ShadowResult.id).where(
                ShadowResult.batch_id == batch_id,
                ShadowResult.document_id == document_id,
            )
        )
        return result.scalars().first() is not None


async def _run_document(
    recipe_id: str, candidate_version: str, document_id: str
) -> dict[str, Any] | None:
    run = await _latest_succeeded_run(document_id)
    if run is None:
        # 没有可用的 stable 基线，跳过该文档而不是判定回退。
        return None
    baseline_records = (await _artifact_json(run.id, "records") or {}).get("records") or []
    baseline_diagnostics = (
        await _artifact_json(run.id, "diagnostics") or {}
    ).get("diagnostics") or []
    snapshot = await latest_snapshot(document_id)
    try:
        request = await build_sandbox_request(
            run,
            recipe_override=_candidate_ref(recipe_id, candidate_version),
        )
        result = await _call_sandbox(request)
    except Exception as exc:  # noqa: BLE001 - 沙箱异常记为回退
        return {
            "stable_run_id": run.id,
            "shadow_run_id": "",
            "passed": False,
            "metrics": {"error": str(exc)[:300]},
        }
    if result.status != "succeeded":
        return {
            "stable_run_id": run.id,
            "shadow_run_id": "",
            "passed": False,
            "metrics": {"error": result.error_code or result.status},
        }
    candidate_records = (await _output_json(result, "records")).get("records") or []
    candidate_diagnostics = (await _output_json(result, "diagnostics")).get(
        "diagnostics"
    ) or []
    metrics = compare_shadow(
        baseline_records,
        candidate_records,
        snapshot,
        baseline_diagnostics=baseline_diagnostics,
        candidate_diagnostics=candidate_diagnostics,
    )
    return {
        "stable_run_id": run.id,
        "shadow_run_id": f"{run.id}:shadow:{candidate_version}",
        "passed": bool(metrics["passed"]),
        "metrics": metrics,
    }


def _candidate_ref(recipe_id: str, version: str) -> Any:
    from hanson_contracts import RecipeRef

    return RecipeRef(recipe_id=recipe_id, version=version, digest="")


async def _save_result(
    batch_id: str, document_id: str, outcome: dict[str, Any]
) -> None:
    async with SessionLocal() as session:
        session.add(
            ShadowResult(
                batch_id=batch_id,
                document_id=document_id,
                stable_run_id=str(outcome.get("stable_run_id") or ""),
                shadow_run_id=str(outcome.get("shadow_run_id") or ""),
                passed=bool(outcome.get("passed")),
                metrics=dict(outcome.get("metrics") or {}),
            )
        )
        await session.commit()


async def _refresh_counts(batch_id: str) -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(ShadowResult.passed).where(ShadowResult.batch_id == batch_id)
        )
        passed_flags = list(result.scalars())
        batch = await session.get(ShadowBatch, batch_id)
        if batch is None:
            return
        batch.completed = sum(1 for flag in passed_flags if flag)
        batch.failed = sum(1 for flag in passed_flags if not flag)
        await session.commit()


def _feedback_message(feedback: Feedback, content: str) -> None:
    messages = list(feedback.messages or [])
    messages.append(
        FeedbackMessage(role="agent", content=content, at=_iso(_now()) or "").model_dump()
    )
    feedback.messages = messages
    feedback.updated_at = _now()


async def expire_stale_batches(batch_id: str | None = None) -> int:
    """把超过 deadline 的批次置 expired，并让反馈回到可再次审批状态。"""
    if settings.shadow_timeout_seconds <= 0:
        return 0
    now = _now()
    async with SessionLocal() as session:
        query = select(ShadowBatch).where(
            ShadowBatch.status.in_(tuple(ACTIVE)),
            ShadowBatch.deadline_at.is_not(None),
            ShadowBatch.deadline_at <= now,
        )
        if batch_id:
            query = query.where(ShadowBatch.id == batch_id)
        rows = list((await session.execute(query)).scalars())
        for batch in rows:
            batch.status = EXPIRED
            batch.finished_at = now
            batch.metrics = {
                **(batch.metrics or {}),
                "reason": "timeout",
                "deadline_at": _iso(batch.deadline_at),
            }
            if batch.feedback_id:
                feedback = await session.get(Feedback, batch.feedback_id)
                if feedback is not None and feedback.status == "shadow":
                    feedback.status = "verified"
                    _feedback_message(
                        feedback,
                        (
                            f"Shadow batch {batch.id} expired at "
                            f"{_iso(batch.deadline_at)}; candidate is still verified. "
                            "Re-approve to start a new shadow batch or discard it."
                        ),
                    )
        if rows:
            await session.commit()
        return len(rows)


async def _finalize(batch_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        batch = await session.get(ShadowBatch, batch_id)
        if batch is None:
            raise ShadowError("SHADOW_BATCH_NOT_FOUND", "shadow batch not found", 404)
        batch.metrics = {
            "completed": batch.completed,
            "failed": batch.failed,
            "required": batch.required_documents,
            "auto_promote": settings.shadow_auto_promote,
        }
        expired = bool(batch.deadline_at and _now() >= batch.deadline_at)
        status = decide_batch_status(
            completed=batch.completed,
            failed=batch.failed,
            required=batch.required_documents,
            auto_promote=settings.shadow_auto_promote,
            expired=expired,
        )
        if status == FAILED:
            batch.status = FAILED
            batch.finished_at = _now()
            await session.commit()
            return await get_batch(batch_id)
        if status == EXPIRED:
            batch.status = EXPIRED
            batch.finished_at = _now()
            batch.metrics = {**batch.metrics, "reason": "timeout"}
            await session.commit()
            return await get_batch(batch_id)
        if status == PROMOTED:
            try:
                await _promote(
                    batch, session, actor="shadow", note="shadow auto promotion"
                )
            except ShadowError as exc:
                batch.status = FAILED
                batch.finished_at = _now()
                batch.metrics = {**batch.metrics, "error": exc.code}
                await session.commit()
                return await get_batch(batch_id)
            await session.commit()
            return await get_batch(batch_id)
        if status == READY:
            batch.status = READY
            batch.metrics = {**batch.metrics, "waiting_for": "manual_promotion"}
            if batch.feedback_id:
                feedback = await session.get(Feedback, batch.feedback_id)
                if feedback is not None and feedback.status == "shadow":
                    _feedback_message(
                        feedback,
                        (
                            f"Shadow passed {batch.completed}/"
                            f"{batch.required_documents} documents. "
                            "Awaiting manual promotion (admin promote or abandon)."
                        ),
                    )
            await session.commit()
            return await get_batch(batch_id)
        batch.status = WAITING
        await session.commit()
    return await get_batch(batch_id)


async def _promote(
    batch: ShadowBatch,
    session: Any,
    *,
    actor: str = "shadow",
    note: str = "",
) -> None:
    await _registry_promote(
        batch.recipe_id,
        batch.candidate_version,
        "stable",
        actor=actor,
        note=(
            f"{note or 'shadow promotion'}: {batch.completed}/"
            f"{batch.required_documents} documents passed"
        ),
    )
    batch.status = PROMOTED
    batch.finished_at = _now()
    session.add(
        Promotion(
            feedback_id=batch.feedback_id,
            recipe_id=batch.recipe_id,
            from_version=batch.from_version,
            to_version=batch.candidate_version,
            channel="stable",
            action="promote",
            actor=actor,
            note=(
                f"{note or 'shadow promotion'} after {batch.completed} documents; "
                f"batch={batch.id}"
            ),
        )
    )
    _audit(
        session,
        "promotion.completed",
        subject_id=batch.recipe_id,
        actor=actor,
        payload={
            "recipe_id": batch.recipe_id,
            "from_version": batch.from_version,
            "to_version": batch.candidate_version,
            "channel": "stable",
            "batch_id": batch.id,
            "completed": batch.completed,
            "required_documents": batch.required_documents,
            "note": note,
        },
    )
    if batch.feedback_id:
        feedback = await session.get(Feedback, batch.feedback_id)
        if feedback is not None:
            feedback.status = "promoted"
            feedback.resolved_at = _now()
            _feedback_message(
                feedback,
                (
                    f"Shadow passed ({batch.completed} documents); "
                    f"promoted {batch.recipe_id}@{batch.candidate_version} to stable."
                ),
            )


async def promote_batch(
    batch_id: str,
    *,
    actor: str = "operator",
    note: str = "",
) -> dict[str, Any]:
    """人工强制晋升：跳过剩余份数，但要求没有失败文档且已有结果。"""
    if not actor.strip():
        raise ShadowError("SHADOW_ACTOR_REQUIRED", "actor is required", 400)
    async with SessionLocal() as session:
        batch = await session.get(ShadowBatch, batch_id)
        if batch is None:
            raise ShadowError("SHADOW_BATCH_NOT_FOUND", "shadow batch not found", 404)
        if batch.status not in {WAITING, READY}:
            raise ShadowError(
                "SHADOW_NOT_PROMOTABLE",
                f"batch is {batch.status}; only waiting/ready can be promoted",
                409,
            )
        if batch.failed:
            raise ShadowError(
                "SHADOW_HAS_FAILURES",
                f"{batch.failed} shadow documents failed",
                409,
            )
        if batch.completed <= 0:
            raise ShadowError(
                "SHADOW_NO_RESULTS", "batch has no passing results yet", 409
            )
        try:
            await _promote(
                batch,
                session,
                actor=actor,
                note=note or "manual promotion",
            )
        except ShadowError:
            await session.rollback()
            raise
        await session.commit()
    return await get_batch(batch_id)


async def abandon_batch(
    batch_id: str,
    *,
    actor: str = "operator",
    note: str = "",
) -> dict[str, Any]:
    """放弃灰度：候选保留，反馈回到 verified 以便重新审批或丢弃。"""
    if not actor.strip():
        raise ShadowError("SHADOW_ACTOR_REQUIRED", "actor is required", 400)
    async with SessionLocal() as session:
        batch = await session.get(ShadowBatch, batch_id)
        if batch is None:
            raise ShadowError("SHADOW_BATCH_NOT_FOUND", "shadow batch not found", 404)
        if batch.status in TERMINAL:
            raise ShadowError(
                "SHADOW_NOT_ABANDONABLE",
                f"batch is already {batch.status}",
                409,
            )
        batch.status = ABANDONED
        batch.finished_at = _now()
        batch.metrics = {**(batch.metrics or {}), "reason": note or "abandoned"}
        session.add(
            Promotion(
                feedback_id=batch.feedback_id,
                recipe_id=batch.recipe_id,
                from_version=batch.from_version,
                to_version=batch.candidate_version,
                channel="shadow",
                action="abandon",
                actor=actor,
                note=f"{note or 'shadow abandoned'}; batch={batch.id}",
            )
        )
        _audit(
            session,
            "promotion.abandoned",
            subject_id=batch.recipe_id,
            actor=actor,
            payload={
                "recipe_id": batch.recipe_id,
                "from_version": batch.from_version,
                "to_version": batch.candidate_version,
                "channel": "shadow",
                "batch_id": batch.id,
                "note": note,
            },
        )
        if batch.feedback_id:
            feedback = await session.get(Feedback, batch.feedback_id)
            if feedback is not None and feedback.status == "shadow":
                feedback.status = "verified"
                _feedback_message(
                    feedback,
                    (
                        f"Shadow batch {batch.id} abandoned by {actor}. "
                        "Candidate remains verified; re-approve or discard it."
                    ),
                )
        await session.commit()
    return await get_batch(batch_id)


# -- rollback --------------------------------------------------------------
async def rollback(
    recipe_id: str,
    *,
    channel: str = "stable",
    actor: str = "operator",
    note: str = "",
) -> dict[str, Any]:
    """一键回滚：调用 registry 回滚指针，并写入 Promotion 审计。"""
    detail = await _registry_get(f"/internal/recipes/{recipe_id}")
    from_version = str((detail.get("channels") or {}).get(channel) or "")
    ref = await _registry_post(
        f"/internal/recipes/{recipe_id}/rollback",
        {"channel": channel, "actor": actor, "note": note},
    )
    async with SessionLocal() as session:
        session.add(
            Promotion(
                feedback_id=None,
                recipe_id=recipe_id,
                from_version=from_version,
                to_version=str(ref.get("version") or ""),
                channel=channel,
                action="rollback",
                actor=actor,
                note=note,
            )
        )
        _audit(
            session,
            "promotion.rolled_back",
            subject_id=recipe_id,
            actor=actor,
            payload={
                "recipe_id": recipe_id,
                "from_version": from_version,
                "to_version": str(ref.get("version") or ""),
                "channel": channel,
                "note": note,
            },
        )
        await session.commit()
    return ref


# -- storage / registry helpers -------------------------------------------
async def _latest_succeeded_run(document_id: str) -> Run | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Run)
            .where(Run.document_id == document_id, Run.status == "STRUCTURED_READY")
            .order_by(Run.finished_at.desc())
        )
        return result.scalars().first()


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


async def _registry_get(path: str) -> dict[str, Any]:
    url = f"{settings.recipe_registry_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise ShadowError(
            "REGISTRY_UNAVAILABLE", f"recipe registry unavailable: {exc}", 503
        ) from exc
    if response.status_code != 200:
        raise ShadowError(
            "REGISTRY_ERROR",
            f"registry error {response.status_code}: {response.text[:300]}",
            502,
        )
    return response.json()


async def _registry_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.recipe_registry_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise ShadowError(
            "REGISTRY_UNAVAILABLE", f"recipe registry unavailable: {exc}", 503
        ) from exc
    if response.status_code not in {200, 201}:
        raise ShadowError(
            "REGISTRY_ERROR",
            f"registry error {response.status_code}: {response.text[:300]}",
            409 if response.status_code == 409 else 502,
        )
    return response.json()


async def _registry_promote(
    recipe_id: str, version: str, channel: str, *, actor: str, note: str
) -> None:
    await _registry_post(
        f"/internal/recipes/{recipe_id}/versions/{version}/promote",
        {"channel": channel, "actor": actor, "note": note},
    )
