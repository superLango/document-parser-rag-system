# ruff: noqa: B008
import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from .db import SessionLocal
from .models import Artifact, Document, DocumentVersion, Run, RunEvent, RunStage
from .schemas import (
    CreateRunIn,
    DocumentOut,
    RunEventOut,
    RunOut,
    RunResultOut,
    RunStageOut,
    RunTimelineOut,
)
from .state import is_terminal
from .workflow import cancel, get_store, schedule

router = APIRouter(prefix="/internal")


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
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        runs = await session.execute(select(Run.id).where(Run.document_id == document_id))
        if runs.first() is not None:
            raise HTTPException(status_code=409, detail="document has runs")
        await get_store().delete(document.storage_key)
        await session.delete(document)
        await session.commit()


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
            select(RunStage).where(RunStage.run_id == run_id).order_by(RunStage.started_at)
        )
        events = await session.execute(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
        )
        return RunTimelineOut(
            run=RunOut.model_validate(run),
            stages=[RunStageOut.model_validate(item) for item in stages.scalars()],
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
