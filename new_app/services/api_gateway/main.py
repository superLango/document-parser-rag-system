# ruff: noqa: B008
import os
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from services.common import create_app

ORCHESTRATION_URL = os.getenv("ORCHESTRATION_URL", "http://localhost:18001")
RECIPE_REGISTRY_URL = os.getenv("RECIPE_REGISTRY_URL", "http://localhost:18005")


class CreateRunRequest(BaseModel):
    recipe_channel: str = "stable"
    parse_profile: str = "standard"


router = APIRouter(prefix="/v1")


async def _request(method: str, path: str, timeout: float = 30, **kwargs) -> Response:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, f"{ORCHESTRATION_URL}{path}", **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"orchestration unavailable: {exc}") from exc

    if response.status_code == 204:
        return Response(status_code=204)
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return JSONResponse(status_code=response.status_code, content=response.json())
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type or None,
    )


async def _registry_request(
    method: str, path: str, timeout: float = 30, **kwargs
) -> Response:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method, f"{RECIPE_REGISTRY_URL}{path}", **kwargs
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"recipe registry unavailable: {exc}"
        ) from exc
    return JSONResponse(status_code=response.status_code, content=response.json())


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api-gateway", "version": "0.0.0"}


@router.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...)) -> Response:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    files = {
        "file": (
            file.filename or "upload.bin",
            data,
            file.content_type or "application/octet-stream",
        )
    }
    return await _request("POST", "/internal/documents", files=files)


@router.get("/documents")
async def list_documents() -> Response:
    return await _request("GET", "/internal/documents")


@router.get("/documents/{document_id}")
async def get_document(document_id: str) -> Response:
    return await _request("GET", f"/internal/documents/{document_id}")


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str) -> Response:
    return await _request("DELETE", f"/internal/documents/{document_id}")


@router.post("/documents/{document_id}/runs", status_code=201)
async def create_run(
    document_id: str,
    payload: CreateRunRequest | None = Body(default=None),
) -> Response:
    body = payload or CreateRunRequest()
    return await _request(
        "POST",
        f"/internal/documents/{document_id}/runs",
        json=body.model_dump(),
    )


@router.get("/runs")
async def list_runs() -> Response:
    return await _request("GET", "/internal/runs")


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}")


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> Response:
    return await _request("POST", f"/internal/runs/{run_id}/cancel")


@router.get("/runs/{run_id}/result")
async def get_result(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/result")


@router.get("/runs/{run_id}/timeline")
async def get_timeline(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/timeline")


@router.get("/runs/{run_id}/artifacts")
async def get_artifacts(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/artifacts")


@router.get("/runs/{run_id}/records")
async def get_records(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/records")


@router.get("/runs/{run_id}/review")
async def get_review(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/review")


@router.get("/runs/{run_id}/ocr")
async def get_ocr(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/ocr")


@router.get("/runs/{run_id}/pages/{page_no}/image")
async def get_page_image(run_id: str, page_no: int) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/pages/{page_no}/image")


@router.get("/dictionary")
async def get_dictionary(
    type: str = Query(default=""),
    q: str = Query(default=""),
    family: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
) -> Response:
    return await _request(
        "GET",
        "/internal/dictionary",
        params={
            "type": type,
            "q": q,
            "family": family,
            "status": status,
            "limit": limit,
        },
    )


@router.get("/recipes")
async def list_recipes() -> Response:
    return await _registry_request("GET", "/internal/recipes")


@router.get("/recipes/{recipe_id}")
async def get_recipe(recipe_id: str) -> Response:
    return await _registry_request("GET", f"/internal/recipes/{recipe_id}")


@router.post("/recipes/{recipe_id}/rollback")
async def rollback_recipe(recipe_id: str, payload: dict = Body(...)) -> Response:
    return await _registry_request(
        "POST", f"/internal/recipes/{recipe_id}/rollback", json=payload
    )


@router.post("/feedback", status_code=201)
async def create_feedback(payload: dict = Body(...)) -> Response:
    return await _request("POST", "/internal/feedback", json=payload)


@router.get("/feedback")
async def list_feedback(
    status: str = Query(default=""),
    document_id: str = Query(default=""),
    run_id: str = Query(default=""),
) -> Response:
    return await _request(
        "GET",
        "/internal/feedback",
        params={"status": status, "document_id": document_id, "run_id": run_id},
    )


@router.get("/feedback/{feedback_id}")
async def get_feedback(feedback_id: str) -> Response:
    return await _request("GET", f"/internal/feedback/{feedback_id}")


@router.post("/feedback/{feedback_id}/process")
async def process_feedback(feedback_id: str) -> Response:
    return await _request(
        "POST", f"/internal/feedback/{feedback_id}/process", timeout=300
    )


@router.get("/feedback/{feedback_id}/verification")
async def get_feedback_verification(feedback_id: str) -> Response:
    return await _request(
        "GET", f"/internal/feedback/{feedback_id}/verification"
    )


@router.post("/feedback/{feedback_id}/verify")
async def verify_feedback(feedback_id: str, payload: dict = Body(...)) -> Response:
    return await _request(
        "POST",
        f"/internal/feedback/{feedback_id}/verify",
        json=payload,
        timeout=120,
    )


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, after: int = Query(default=0, ge=0)) -> StreamingResponse:
    await _request("GET", f"/internal/runs/{run_id}")

    async def event_stream() -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET",
                f"{ORCHESTRATION_URL}/internal/runs/{run_id}/events/stream",
                params={"after": after},
            ) as response:
                async for chunk in response.aiter_raw():
                    yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


app: FastAPI = create_app("api-gateway")
app.include_router(router)
