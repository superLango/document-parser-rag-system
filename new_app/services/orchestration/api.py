# ruff: noqa: B008
import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from .db import SessionLocal
from .models import Artifact, Document, DocumentVersion, Finding, Run, RunEvent, RunStage
from .models import ReviewReport as ReviewReportRow
from .schemas import (
    CreateRunIn,
    DocumentOut,
    RunEventOut,
    RunOut,
    RunResultOut,
    RunStageOut,
    RunTimelineOut,
)
from .state import TERMINAL_STATES, is_terminal
from .workflow import cancel, get_store, schedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")

# 阶段展示顺序固定为业务链路顺序，避免依赖时间戳（系统时钟回跳会把顺序打乱）。
STAGE_ORDER = {"ocr": 1, "routing": 2, "sandbox": 3, "review": 4}


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
        return [DocumentOut.model_validate(item) for item in result.scalars()]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str) -> DocumentOut:
    return DocumentOut.model_validate(await _get_document(document_id))


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
    await _get_document(document_id)
    async with SessionLocal() as session:
        run = Run(
            document_id=document_id,
            document_version=1,
            status="RECEIVED",
            stage="RECEIVED",
            trace_id=str(uuid4()),
            recipe_channel=payload.recipe_channel,
        )
        session.add(run)
        await session.commit()
        result = RunOut.model_validate(run)
    schedule(run.id)
    return result


@router.get("/runs", response_model=list[RunOut])
async def list_runs() -> list[RunOut]:
    async with SessionLocal() as session:
        result = await session.execute(select(Run).order_by(Run.created_at.desc()))
        return [RunOut.model_validate(item) for item in result.scalars()]


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
                    "observed": item.observed,
                    "expected": item.expected,
                    "evidence_refs": item.evidence_refs,
                    "confidence": item.confidence,
                    "status": item.status,
                }
                for item in findings.scalars()
            ],
        }


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
