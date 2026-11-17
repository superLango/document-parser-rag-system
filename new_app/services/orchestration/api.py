# ruff: noqa: B008
import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from . import shadow as shadow_service
from .db import SessionLocal
from .idempotency import build_key
from .models import (
    Artifact,
    Document,
    DocumentVersion,
    Feedback,
    Finding,
    IntegrationTask,
    Run,
    RunEvent,
    RunStage,
)
from .models import ReviewReport as ReviewReportRow
from .rundiff import diff_run_ids
from .schemas import (
    CreateRunIn,
    DocumentOut,
    ReparseIn,
    RunEventOut,
    RunOut,
    RunResultOut,
    RunStageOut,
    RunTimelineOut,
)
from .shadow import ShadowError, add_document, remove_document
from .snapshots import capture_run_snapshot, latest_snapshot
from .state import TERMINAL_STATES, RunState, ensure_transition, is_terminal
from .workflow import (
    append_event,
    cancel,
    get_store,
    now,
    schedule,
    validate_parser_version,
)

logger = logging.getLogger(__name__)

OCR_ARTIFACT_ROLES = {"ocr", "markdown.md", "pages.json", "tables.json", "layout.json"}


def _is_ocr_artifact(role: str) -> bool:
    return role in OCR_ARTIFACT_ROLES or role.endswith(".png")


def _ascii_filename(filename: str) -> str:
    """Latin-1 fallback name for Content-Disposition; keeps the extension."""
    name = str(filename or "document")
    stem, dot, suffix = name.rpartition(".")
    ascii_stem = stem.encode("ascii", "ignore").decode("ascii").strip() or "document"
    ascii_suffix = suffix.encode("ascii", "ignore").decode("ascii")
    return f"{ascii_stem}.{ascii_suffix}" if dot and ascii_suffix else ascii_stem

router = APIRouter(prefix="/internal")

# 阶段展示顺序固定为业务链路顺序，避免依赖时间戳（系统时钟回跳会把顺序打乱）。
STAGE_ORDER = {"ocr": 1, "routing": 2, "sandbox": 3, "cross_standard": 4, "review": 5}


async def _get_document(document_id: str) -> Document:
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        return document


async def _get_run(run_id: str) -> Run:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run


def _idempotency_key(
    document: Document,
    channel: str,
    parser_version: str | None,
    *,
    prefix: str,
) -> str:
    """同一文档/内容/通道/parser pin 的重复请求映射到同一个 run。"""
    return build_key(
        prefix=prefix,
        document_id=document.id,
        sha256=document.sha256,
        channel=channel,
        parser_version=parser_version,
    )


async def _find_run_by_key(session, key: str) -> Run | None:
    result = await session.execute(select(Run).where(Run.idempotency_key == key))
    return result.scalars().first()


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile = File(...)) -> DocumentOut:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    sha256 = hashlib.sha256(data).hexdigest()
    filename = file.filename or "upload.bin"
    content_type = file.content_type or "application/octet-stream"

    async with SessionLocal() as session:
        existing = await session.execute(select(Document).where(Document.sha256 == sha256))
        document = existing.scalars().first()
        if document is not None:
            return DocumentOut.model_validate(document)

        document_id = str(uuid4())
        storage_key = f"documents/{document_id}/{filename}"
        await get_store().put_bytes(storage_key, data, content_type)
        document = Document(
            id=document_id,
            filename=filename,
            content_type=content_type,
            size=len(data),
            sha256=sha256,
            storage_key=storage_key,
        )
        session.add(document)
        session.add(
            DocumentVersion(
                document_id=document_id,
                version=1,
                storage_key=storage_key,
                sha256=sha256,
            )
        )
        await session.commit()
        return DocumentOut.model_validate(document)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents() -> list[DocumentOut]:
    async with SessionLocal() as session:
        result = await session.execute(select(Document).order_by(Document.created_at.desc()))
        documents = list(result.scalars())
        # 按创建时间升序写入，同一文档以最新的对接任务为准
        tasks = dict(
            (
                await session.execute(
                    select(IntegrationTask.document_id, IntegrationTask.task_id).order_by(
                        IntegrationTask.created_at
                    )
                )
            ).all()
        )
        return [
            DocumentOut.model_validate(item).model_copy(update={"task_id": tasks.get(item.id)})
            for item in documents
        ]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str) -> DocumentOut:
    return DocumentOut.model_validate(await _get_document(document_id))


@router.get("/documents/{document_id}/file")
async def get_document_file(document_id: str) -> Response:
    """返回原始文档字节，供前端内嵌 PDF/原文查看。"""
    document = await _get_document(document_id)
    try:
        data = await get_store().get_bytes(document.storage_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="document file missing") from exc
    return Response(
        content=data,
        media_type=document.content_type or "application/pdf",
        headers={
            # HTTP 头只能是 latin-1；中文文件名必须走 RFC 5987，否则
            # Starlette 编码失败会返回 500 Internal Server Error。
            "Content-Disposition": (
                f'inline; filename="{_ascii_filename(document.filename)}"; '
                f"filename*=UTF-8''{quote(document.filename)}"
            ),
            "Cache-Control": "private, max-age=60",
            # 前端结果页需要同源内嵌原文。
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str) -> None:
    await _get_document(document_id)

    terminal = [state.value for state in TERMINAL_STATES]
    async with SessionLocal() as session:
        result = await session.execute(
            select(Run.id).where(
                Run.document_id == document_id, Run.status.notin_(terminal)
            )
        )
        active_run_ids = list(result.scalars())

    # 先停掉未完成的 run，避免删除后仍有任务写入产物。
    for run_id in active_run_ids:
        await cancel(run_id)

    async with SessionLocal() as session:
        keys_result = await session.execute(
            select(Artifact.storage_key)
            .join(Run, Artifact.run_id == Run.id)
            .where(Run.document_id == document_id)
        )
        object_keys = set(keys_result.scalars())

        document = await session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        object_keys.add(document.storage_key)

        # 子表由数据库外键 ON DELETE CASCADE 清理。
        await session.delete(document)
        await session.commit()

    store = get_store()
    for key in object_keys:
        try:
            await store.delete(key)
        except Exception:
            logger.warning("failed to delete object %s", key, exc_info=True)


@router.post("/documents/{document_id}/runs", response_model=RunOut, status_code=201)
async def create_run(document_id: str, payload: CreateRunIn) -> RunOut:
    document = await _get_document(document_id)
    key = _idempotency_key(document, payload.recipe_channel, None, prefix="run")
    async with SessionLocal() as session:
        run = await _find_run_by_key(session, key)
        if run is not None:
            return RunOut.model_validate(run)
        run = Run(
            document_id=document_id,
            document_version=1,
            status="RECEIVED",
            stage="RECEIVED",
            trace_id=str(uuid4()),
            recipe_channel=payload.recipe_channel,
            idempotency_key=key,
        )
        session.add(run)
        await session.flush()
        await append_event(
            session,
            run,
            "run.created",
            "RECEIVED",
            "created",
            {
                "document_id": document_id,
                "document_sha256": document.sha256,
                "recipe_channel": payload.recipe_channel,
                "parser_version": None,
                "parse_profile": payload.parse_profile,
            },
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            run = await _find_run_by_key(session, key)
            if run is None:
                raise
            return RunOut.model_validate(run)
        result = RunOut.model_validate(run)
    schedule(run.id)
    return result


@router.get("/runs", response_model=list[RunOut])
async def list_runs() -> list[RunOut]:
    async with SessionLocal() as session:
        result = await session.execute(select(Run).order_by(Run.created_at.desc()))
        runs = list(result.scalars())
        # 机器解析结束时间 = 最后一个阶段结束时间。待人工审核时 finished_at 为空、审核后才写入，
        # 文档库「解析时长」用它才不会显示“解析中”或把等待人工的时间算进去。
        last_stage_end = select(RunStage.run_id, func.max(RunStage.finished_at)).group_by(
            RunStage.run_id
        )
        ends = dict((await session.execute(last_stage_end)).all())
        return [
            RunOut.model_validate(item).model_copy(update={"parsed_at": ends.get(item.id)})
            for item in runs
        ]


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str) -> RunOut:
    return RunOut.model_validate(await _get_run(run_id))


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: str) -> RunOut:
    await cancel(run_id)
    return RunOut.model_validate(await _get_run(run_id))


async def _event_rows(run_id: str, after: int) -> list[RunEventOut]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.sequence > after)
            .order_by(RunEvent.sequence)
        )
        return [RunEventOut.model_validate(item) for item in result.scalars()]


@router.get("/runs/{run_id}/events", response_model=list[RunEventOut])
async def list_events(run_id: str, after: int = Query(default=0, ge=0)) -> list[RunEventOut]:
    await _get_run(run_id)
    return await _event_rows(run_id, after)


@router.get("/runs/{run_id}/events/stream")
async def stream_events(run_id: str, after: int = Query(default=0, ge=0)) -> StreamingResponse:
    await _get_run(run_id)

    async def event_stream() -> AsyncIterator[str]:
        last = after
        while True:
            events = await _event_rows(run_id, last)
            for event in events:
                last = event.sequence
                data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                yield f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n"
            run = await _get_run(run_id)
            if is_terminal(run.status) and not events:
                yield "event: done\ndata: {\"status\": \"terminal\"}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}/result", response_model=RunResultOut)
async def get_result(run_id: str) -> RunResultOut:
    run = await _get_run(run_id)
    if not run.result_key:
        return RunResultOut(run_id=run.id, status=run.status, result=None)
    data = await get_store().get_bytes(run.result_key)
    return RunResultOut(
        run_id=run.id,
        status=run.status,
        result=json.loads(data.decode("utf-8")),
    )


@router.get("/runs/{run_id}/timeline", response_model=RunTimelineOut)
async def get_timeline(run_id: str) -> RunTimelineOut:
    run = await _get_run(run_id)
    async with SessionLocal() as session:
        stages = await session.execute(
            select(RunStage).where(RunStage.run_id == run_id)
        )
        events = await session.execute(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
        )
        return RunTimelineOut(
            run=RunOut.model_validate(run),
            stages=[
                RunStageOut.model_validate(item)
                for item in sorted(
                    stages.scalars(), key=lambda s: STAGE_ORDER.get(s.stage, 99)
                )
            ],
            events=[RunEventOut.model_validate(item) for item in events.scalars()],
        )


@router.get("/runs/{run_id}/artifacts", response_model=list[dict])
async def list_artifacts(run_id: str) -> list[dict]:
    await _get_run(run_id)
    async with SessionLocal() as session:
        result = await session.execute(
            select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at)
        )
        return [
            {
                "role": item.role,
                "storage_key": item.storage_key,
                "sha256": item.sha256,
                "bytes": item.bytes,
            }
            for item in result.scalars()
        ]


async def _artifact_payload(run_id: str, role: str) -> dict | None:
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
    payload = json.loads(data.decode("utf-8"))
    return payload if isinstance(payload, dict) else None


@router.get("/runs/{run_id}/records")
async def get_records(run_id: str) -> dict:
    await _get_run(run_id)
    payload = await _artifact_payload(run_id, "records")
    if payload is None:
        raise HTTPException(status_code=404, detail="records not ready")
    return payload


@router.get("/runs/{run_id}/intelligence")
async def get_intelligence(run_id: str) -> dict:
    """Document-understanding artifacts for the trace panel."""
    await _get_run(run_id)
    intelligence = await _artifact_payload(run_id, "document_intelligence")
    inventory = await _artifact_payload(run_id, "inventory")
    references = await _artifact_payload(run_id, "references")
    clauses = await _artifact_payload(run_id, "clauses")
    if intelligence is None and inventory is None and references is None:
        raise HTTPException(status_code=404, detail="document intelligence not ready")
    return {
        "document_intelligence": intelligence or {},
        "inventory": inventory or {},
        "references": references or {},
        "clauses": clauses or {},
    }


@router.get("/runs/{run_id}/ocr")
async def get_ocr(run_id: str) -> dict:
    await _get_run(run_id)
    payload = await _artifact_payload(run_id, "ocr")
    if payload is None:
        raise HTTPException(status_code=404, detail="ocr not ready")
    return payload


@router.get("/runs/{run_id}/review")
async def get_review(run_id: str) -> dict:
    await _get_run(run_id)
    async with SessionLocal() as session:
        result = await session.execute(
            select(ReviewReportRow)
            .where(ReviewReportRow.run_id == run_id)
            .order_by(ReviewReportRow.created_at.desc())
        )
        report = result.scalars().first()
        if report is None:
            raise HTTPException(status_code=404, detail="review not ready")
        findings = await session.execute(
            select(Finding)
            .where(Finding.run_id == run_id)
            .order_by(Finding.created_at)
        )
        return {
            "run_id": run_id,
            "status": report.status,
            "ruleset_version": report.ruleset_version,
            "stats": report.stats,
            "degraded": report.degraded,
            "findings": [
                {
                    "id": item.id,
                    "source": item.source,
                    "category": item.category,
                    "severity": item.severity,
                    "target": item.target,
                    "message": item.message or "",
                    "rule_id": item.rule_id or "",
                    "observed": item.observed,
                    "expected": item.expected,
                    "evidence_refs": item.evidence_refs,
                    "confidence": item.confidence,
                    "status": item.status,
                }
                for item in findings.scalars()
            ],
        }


@router.post("/runs/{run_id}/accept")
async def accept_run(
    run_id: str,
    actor: str = Query("operator"),
    note: str = Query(""),
) -> dict:
    """Human approval gate: accept a run and move it to STRUCTURED_READY."""
    try:
        snapshot = await capture_run_snapshot(run_id, actor)
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "RUN_NOT_READY", "message": str(exc)}
        ) from exc
    await _approve_run(run_id, actor, note)
    payload = snapshot.model_dump(mode="json")
    payload["run_status"] = RunState.STRUCTURED_READY.value
    return payload


@router.post("/runs/{run_id}/reject")
async def reject_run(
    run_id: str,
    actor: str = Query("operator"),
    reason: str = Query(""),
) -> dict:
    """Human rejection gate: keep the run out of the delivery path."""
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status == RunState.HUMAN_REJECTED.value:
            return {"run_id": run.id, "status": run.status}
        if run.status != RunState.HUMAN_REVIEW.value:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RUN_NOT_IN_HUMAN_REVIEW",
                    "message": f"run is {run.status}",
                },
            )
        ensure_transition(run.status, RunState.HUMAN_REJECTED)
        run.status = RunState.HUMAN_REJECTED.value
        run.stage = RunState.HUMAN_REJECTED.value
        run.progress = 100
        run.finished_at = now()
        await append_event(
            session,
            run,
            "run.human_rejected",
            RunState.HUMAN_REJECTED.value,
            "rejected",
            {"actor": actor, "reason": reason},
        )
        await session.commit()
        return {"run_id": run.id, "status": run.status}


async def _approve_run(run_id: str, actor: str, note: str) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status == RunState.STRUCTURED_READY.value:
            return
        if run.status == RunState.REVIEW_PASSED.value:
            ensure_transition(run.status, RunState.HUMAN_REVIEW)
            run.status = RunState.HUMAN_REVIEW.value
            run.stage = RunState.HUMAN_REVIEW.value
            await append_event(
                session,
                run,
                "run.human_review_required",
                RunState.HUMAN_REVIEW.value,
                "waiting",
                {"actor": "system"},
            )
        if run.status != RunState.HUMAN_REVIEW.value:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RUN_NOT_IN_HUMAN_REVIEW",
                    "message": f"run is {run.status}",
                },
            )
        ensure_transition(run.status, RunState.HUMAN_APPROVED)
        run.status = RunState.HUMAN_APPROVED.value
        run.stage = RunState.HUMAN_APPROVED.value
        run.progress = max(int(run.progress or 0), 98)
        await append_event(
            session,
            run,
            "run.human_approved",
            RunState.HUMAN_APPROVED.value,
            "approved",
            {"actor": actor, "note": note},
        )
        ensure_transition(run.status, RunState.STRUCTURED_READY)
        run.status = RunState.STRUCTURED_READY.value
        run.stage = RunState.STRUCTURED_READY.value
        run.progress = 100
        run.finished_at = now()
        result = await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.role == "result")
            .order_by(Artifact.created_at.desc())
        )
        artifact = result.scalars().first()
        run.result_key = artifact.storage_key if artifact else run.result_key
        await append_event(
            session,
            run,
            "run.completed",
            RunState.STRUCTURED_READY.value,
            "completed",
            {"result_key": run.result_key, "actor": actor},
        )
        await session.commit()


@router.post("/runs/{run_id}/reparse", response_model=RunOut, status_code=202)
async def reparse_run(run_id: str, payload: ReparseIn | None = None) -> RunOut:
    """Re-run the same document with stable recipes and an optional parser pin."""
    parser_version = (payload.parser_version if payload else None) or None
    reuse_ocr = bool(payload.reuse_ocr) if payload else False
    if parser_version:
        try:
            await validate_parser_version(parser_version)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "PARSER_VERSION_UNKNOWN", "message": str(exc)},
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "REGISTRY_UNAVAILABLE", "message": str(exc)},
            ) from exc
    async with SessionLocal() as session:
        original = await session.get(Run, run_id)
        if original is None:
            raise HTTPException(status_code=404, detail="run not found")
        document = await session.get(Document, original.document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        # HUMAN_REVIEW/HUMAN_APPROVED 是等待人工的驻留状态，允许基于其结果重解析。
        repairable_states = {
            RunState.HUMAN_REVIEW.value,
            RunState.HUMAN_APPROVED.value,
        }
        if not is_terminal(original.status) and original.status not in repairable_states:
            raise HTTPException(
                status_code=409,
                detail={"code": "RUN_NOT_READY", "message": "run is not finished"},
            )
        key = _idempotency_key(
            document,
            "stable",
            parser_version,
            prefix="reparse-ocr" if reuse_ocr else "reparse",
        )
        existing = await _find_run_by_key(session, key)
        if existing is not None:
            return RunOut.model_validate(existing)
        run = Run(
            document_id=original.document_id,
            document_version=original.document_version,
            status="RECEIVED",
            stage="RECEIVED",
            trace_id=str(uuid4()),
            recipe_channel="stable",
            parser_version=parser_version,
            idempotency_key=key,
        )
        session.add(run)
        await session.flush()
        if reuse_ocr:
            artifacts = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id == run_id)
                )
            ).scalars().all()
            for artifact in artifacts:
                if not _is_ocr_artifact(artifact.role):
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
                "document_sha256": document.sha256,
                "recipe_channel": "stable",
                "parser_version": parser_version,
                "source_run_id": run_id,
            },
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await _find_run_by_key(session, key)
            if existing is None:
                raise
            return RunOut.model_validate(existing)
        created = RunOut.model_validate(run)
    schedule(run.id, skip_ocr=reuse_ocr)
    return created


@router.get("/runs/{run_id}/diff")
async def run_diff(run_id: str, against: str = Query(...)) -> dict:
    async with SessionLocal() as session:
        before = await session.get(Run, run_id)
        after = await session.get(Run, against)
    if before is None or after is None:
        raise HTTPException(status_code=404, detail="run not found")
    if before.document_id != after.document_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "DOCUMENT_MISMATCH",
                "message": "runs must belong to the same document",
            },
        )
    if not is_terminal(before.status) or not is_terminal(after.status):
        raise HTTPException(
            status_code=409,
            detail={"code": "RUN_NOT_READY", "message": "both runs must be finished"},
        )
    diff = await diff_run_ids(run_id, against)
    return {"before_run": run_id, "after_run": against, "diff": diff}


@router.get("/documents/{document_id}/snapshot")
async def get_document_snapshot(document_id: str) -> dict:
    snapshot = await latest_snapshot(document_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SNAPSHOT_NOT_FOUND", "message": "accepted snapshot not found"},
        )
    return snapshot.model_dump(mode="json")


@router.get("/runs/{run_id}/pages/{page_no}/image")
async def get_page_image(run_id: str, page_no: int) -> Response:
    await _get_run(run_id)
    payload = await _artifact_payload(run_id, "ocr")
    if payload is None:
        raise HTTPException(status_code=404, detail="ocr not ready")
    page = next(
        (
            item
            for item in payload.get("pages") or []
            if int(item.get("page_no") or 0) == page_no
        ),
        None,
    )
    key = str((page or {}).get("image_key") or "")
    if not key:
        raise HTTPException(status_code=404, detail="page image not available")
    try:
        data = await get_store().get_bytes(key)
    except Exception as exc:  # noqa: BLE001 - storage errors map to 404
        raise HTTPException(status_code=404, detail="page image not found") from exc
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


class ShadowDocumentIn(BaseModel):
    document_id: str
    actor: str = "operator"
    note: str = ""


class ShadowBatchIn(BaseModel):
    recipe_id: str
    from_version: str
    candidate_version: str
    feedback_id: str | None = None
    required_documents: int = 0
    actor: str = "operator"
    note: str = ""


class RollbackIn(BaseModel):
    channel: str = "stable"
    actor: str = "operator"
    note: str = ""


class ShadowActionIn(BaseModel):
    actor: str = "operator"
    note: str = ""


def _shadow_error(exc: ShadowError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/shadow/documents")
async def list_shadow_documents() -> list[dict]:
    return await shadow_service.list_documents()


@router.post("/shadow/documents", status_code=201)
async def add_shadow_document(payload: ShadowDocumentIn) -> dict:
    try:
        return await add_document(
            payload.document_id, actor=payload.actor, note=payload.note
        )
    except ShadowError as exc:
        raise _shadow_error(exc) from exc


@router.delete("/shadow/documents/{document_id}", status_code=204)
async def delete_shadow_document(document_id: str) -> Response:
    if not await remove_document(document_id):
        raise HTTPException(status_code=404, detail="shadow document not found")
    return Response(status_code=204)


@router.get("/shadow/batches")
async def list_shadow_batches() -> list[dict]:
    return await shadow_service.list_batches()


@router.post("/shadow/batches", status_code=201)
async def create_shadow_batch(payload: ShadowBatchIn) -> dict:
    return await shadow_service.create_batch(
        recipe_id=payload.recipe_id,
        from_version=payload.from_version,
        candidate_version=payload.candidate_version,
        feedback_id=payload.feedback_id,
        required_documents=payload.required_documents,
        actor=payload.actor,
        note=payload.note,
    )


@router.get("/shadow/batches/{batch_id}")
async def get_shadow_batch(batch_id: str) -> dict:
    try:
        return await shadow_service.get_batch(batch_id)
    except ShadowError as exc:
        raise _shadow_error(exc) from exc


@router.post("/shadow/batches/{batch_id}/run")
async def run_shadow_batch(batch_id: str) -> dict:
    try:
        await shadow_service.get_batch(batch_id)
        shadow_service.schedule(batch_id)
        return await shadow_service.get_batch(batch_id)
    except ShadowError as exc:
        raise _shadow_error(exc) from exc


@router.post("/shadow/batches/{batch_id}/promote")
async def promote_shadow_batch(batch_id: str, payload: ShadowActionIn) -> dict:
    try:
        return await shadow_service.promote_batch(
            batch_id, actor=payload.actor, note=payload.note
        )
    except ShadowError as exc:
        raise _shadow_error(exc) from exc


@router.post("/shadow/batches/{batch_id}/abandon")
async def abandon_shadow_batch(batch_id: str, payload: ShadowActionIn) -> dict:
    try:
        return await shadow_service.abandon_batch(
            batch_id, actor=payload.actor, note=payload.note
        )
    except ShadowError as exc:
        raise _shadow_error(exc) from exc


@router.post("/recipes/{recipe_id}/rollback")
async def rollback_recipe(recipe_id: str, payload: RollbackIn) -> dict:
    try:
        return await shadow_service.rollback(
            recipe_id,
            channel=payload.channel,
            actor=payload.actor,
            note=payload.note,
        )
    except ShadowError as exc:
        raise _shadow_error(exc) from exc


ABNORMAL_RUN_STATUSES = {
    "FAILED",
    "REVIEW_FAILED",
    "UNROUTED",
    "CANCELLED",
    "HUMAN_REJECTED",
}


@router.get("/issues/ledger")
async def issue_ledger() -> dict:
    """问题台账：问题反馈 + 异常文档，用于后续导出优化清单。"""
    async with SessionLocal() as session:
        documents = list((await session.execute(select(Document))).scalars())
        runs = list(
            (
                await session.execute(
                    select(Run).order_by(Run.created_at.desc())
                )
            ).scalars()
        )
        feedback = list(
            (
                await session.execute(
                    select(Feedback).order_by(Feedback.created_at.desc())
                )
            ).scalars()
        )

    names = {document.id: document.filename for document in documents}
    latest: dict[str, Run] = {}
    for run in runs:
        latest.setdefault(run.document_id, run)

    feedback_rows = [
        {
            "id": item.id,
            "created_at": item.created_at.isoformat() if item.created_at else "",
            "document_id": item.document_id,
            "document": names.get(item.document_id, item.document_id),
            "run_id": item.run_id,
            "category": item.category,
            "status": item.status,
            "description": item.description,
            "measure": str((item.target or {}).get("measure") or ""),
            "recipe_id": str((item.target or {}).get("recipe_id") or ""),
            "reporter": str((item.target or {}).get("reporter") or ""),
        }
        for item in feedback
        # 审核门自动生成的 DOC-* 反馈属于异常文档，不混进人工问题反馈台账。
        if not str((item.target or {}).get("rule_id") or "").startswith("DOC-")
    ]

    abnormal_documents = []
    for document in documents:
        run = latest.get(document.id)
        if run is None:
            continue
        if run.status not in ABNORMAL_RUN_STATUSES and not run.error_code:
            continue
        abnormal_documents.append(
            {
                "document_id": document.id,
                "document": document.filename,
                "run_id": run.id,
                "status": run.status,
                "stage": run.stage,
                "error_code": run.error_code or "",
                "parsed_at": (
                    run.finished_at.isoformat()
                    if run.finished_at
                    else (run.created_at.isoformat() if run.created_at else "")
                ),
                "recipe_channel": run.recipe_channel,
                "parser_version": run.parser_version or "",
            }
        )

    return {
        "feedback": feedback_rows,
        "abnormal_documents": abnormal_documents,
        "summary": {
            "feedback": len(feedback_rows),
            "open_feedback": sum(
                1 for item in feedback_rows if item["status"] in {"open", "needs_more_info"}
            ),
            "abnormal_documents": len(abnormal_documents),
        },
    }
