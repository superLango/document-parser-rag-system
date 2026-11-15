# ruff: noqa: B008
import os
import uuid
from collections.abc import AsyncIterator

import httpx
from fastapi import (
    APIRouter,
    Body,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from services.common import create_app

ORCHESTRATION_URL = os.getenv("ORCHESTRATION_URL", "http://localhost:18001")
RECIPE_REGISTRY_URL = os.getenv("RECIPE_REGISTRY_URL", "http://localhost:18005")


class CreateRunRequest(BaseModel):
    recipe_channel: str = "stable"
    parse_profile: str = "standard"


class ReparseRequest(BaseModel):
    parser_version: str | None = None
    reuse_ocr: bool = False


class DictionaryImportRequest(BaseModel):
    entries: list[dict] = Field(default_factory=list)
    replace: bool = False


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


@router.get("/documents/{document_id}/file")
async def get_document_file(document_id: str) -> Response:
    response = await _request(
        "GET", f"/internal/documents/{document_id}/file", timeout=120
    )
    # 服务默认 DENY；结果页需要在同源 iframe 内嵌原文。
    response.headers["x-frame-options"] = "SAMEORIGIN"
    return response


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


@router.get("/runs/{run_id}/intelligence")
async def get_intelligence(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/intelligence")


@router.get("/runs/{run_id}/review")
async def get_review(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/review")


@router.get("/runs/{run_id}/ocr")
async def get_ocr(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/ocr")


@router.get("/runs/{run_id}/cross-standard")
async def get_cross_standard(run_id: str) -> Response:
    return await _request("GET", f"/internal/runs/{run_id}/cross-standard")


@router.get("/library/standards")
async def list_library_standards(q: str = Query(default="")) -> Response:
    return await _request("GET", "/internal/library/standards", params={"q": q})


@router.post("/runs/{run_id}/accept")
async def accept_run(
    run_id: str,
    actor: str = Query(default="operator"),
    note: str = Query(default=""),
) -> Response:
    return await _request(
        "POST",
        f"/internal/runs/{run_id}/accept",
        params={"actor": actor, "note": note},
    )


@router.post("/runs/{run_id}/reject")
async def reject_run(
    run_id: str,
    actor: str = Query(default="operator"),
    reason: str = Query(default=""),
) -> Response:
    return await _request(
        "POST",
        f"/internal/runs/{run_id}/reject",
        params={"actor": actor, "reason": reason},
    )


@router.get("/documents/{document_id}/snapshot")
async def get_document_snapshot(document_id: str) -> Response:
    return await _request("GET", f"/internal/documents/{document_id}/snapshot")


@router.post("/runs/{run_id}/reparse", status_code=202)
async def reparse_run(
    run_id: str,
    payload: ReparseRequest | None = Body(default=None),
) -> Response:
    body = payload or ReparseRequest()
    return await _request(
        "POST", f"/internal/runs/{run_id}/reparse", json=body.model_dump()
    )


@router.get("/runs/{run_id}/diff")
async def run_diff(run_id: str, against: str = Query(...)) -> Response:
    return await _request(
        "GET", f"/internal/runs/{run_id}/diff", params={"against": against}
    )


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


@router.post("/dictionary/import")
async def import_dictionary(body: DictionaryImportRequest) -> Response:
    return await _request(
        "POST", "/internal/dictionary/import", json=body.model_dump()
    )


@router.get("/recipes")
async def list_recipes() -> Response:

    return await _registry_request("GET", "/internal/recipes")


@router.get("/recipes/{recipe_id}")
async def get_recipe(recipe_id: str) -> Response:
    return await _registry_request("GET", f"/internal/recipes/{recipe_id}")


@router.post("/recipes/{recipe_id}/rollback")
async def rollback_recipe(recipe_id: str, payload: dict = Body(...)) -> Response:
    return await _request(
        "POST", f"/internal/recipes/{recipe_id}/rollback", json=payload, timeout=60
    )


@router.get("/shadow/documents")
async def list_shadow_documents() -> Response:
    return await _request("GET", "/internal/shadow/documents")


@router.post("/shadow/documents", status_code=201)
async def add_shadow_document(payload: dict = Body(...)) -> Response:
    return await _request("POST", "/internal/shadow/documents", json=payload)


@router.delete("/shadow/documents/{document_id}", status_code=204)
async def delete_shadow_document(document_id: str) -> Response:
    return await _request("DELETE", f"/internal/shadow/documents/{document_id}")


@router.get("/shadow/batches")
async def list_shadow_batches() -> Response:
    return await _request("GET", "/internal/shadow/batches")


@router.post("/shadow/batches", status_code=201)
async def create_shadow_batch(payload: dict = Body(...)) -> Response:
    return await _request("POST", "/internal/shadow/batches", json=payload)


@router.get("/shadow/batches/{batch_id}")
async def get_shadow_batch(batch_id: str) -> Response:
    return await _request("GET", f"/internal/shadow/batches/{batch_id}")


@router.post("/shadow/batches/{batch_id}/promote")
async def promote_shadow_batch(batch_id: str, payload: dict = Body(...)) -> Response:
    return await _request(
        "POST", f"/internal/shadow/batches/{batch_id}/promote", json=payload
    )


@router.post("/shadow/batches/{batch_id}/abandon")
async def abandon_shadow_batch(batch_id: str, payload: dict = Body(...)) -> Response:
    return await _request(
        "POST", f"/internal/shadow/batches/{batch_id}/abandon", json=payload
    )


@router.post("/shadow/batches/{batch_id}/run")
async def run_shadow_batch(batch_id: str) -> Response:
    return await _request(
        "POST", f"/internal/shadow/batches/{batch_id}/run", timeout=60
    )


@router.post("/feedback", status_code=201)
async def create_feedback(payload: dict = Body(...)) -> Response:
    return await _request("POST", "/internal/feedback", json=payload)


@router.get("/issues/ledger")
async def issue_ledger() -> Response:
    return await _request("GET", "/internal/issues/ledger", timeout=60)


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


@router.post("/feedback/{feedback_id}/approve-code")
async def approve_code(
    feedback_id: str,
    payload: dict = Body(...),
    x_internal_token: str = Header(default=""),
) -> Response:
    # 前端“应用修复结果”没有独立审批令牌时，使用网关侧配置的令牌。
    token = x_internal_token or os.getenv("INTERNAL_API_TOKEN", "")
    return await _request(
        "POST",
        f"/internal/feedback/{feedback_id}/approve-code",
        json=payload,
        headers={"X-Internal-Token": token},
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


integration_router = APIRouter(prefix="/api/v1/integration")


def _integration_headers() -> dict[str, str]:
    return {"x-request-id": uuid.uuid4().hex}


@integration_router.post("/upload")
async def integration_upload(
    file: UploadFile = File(...),
    kb_id: str = Query(...),
    prompt_id: str = Query(...),
) -> Response:
    data = await file.read()
    files = {
        "file": (
            file.filename or "document.pdf",
            data,
            file.content_type or "application/pdf",
        )
    }
    return await _request(
        "POST",
        "/internal/integration/upload",
        files=files,
        params={"kb_id": kb_id, "prompt_id": prompt_id},
        headers=_integration_headers(),
        timeout=600,
    )


@integration_router.get("/tasks/{task_id}/status")
async def integration_status(task_id: str) -> Response:
    return await _request(
        "GET",
        f"/internal/integration/tasks/{task_id}/status",
        headers=_integration_headers(),
    )


@integration_router.get("/tasks/{task_id}/result")
async def integration_result(task_id: str) -> Response:
    return await _request(
        "GET",
        f"/internal/integration/tasks/{task_id}/result",
        headers=_integration_headers(),
        timeout=120,
    )


@integration_router.post("/tasks/{task_id}/retrigger")
async def integration_retrigger(task_id: str) -> Response:
    return await _request(
        "POST",
        f"/internal/integration/tasks/{task_id}/retrigger",
        headers=_integration_headers(),
        timeout=60,
    )


@integration_router.get("/tasks/{task_id}/session-token")
async def integration_session_token(task_id: str) -> Response:
    return await _request(
        "GET",
        f"/internal/integration/tasks/{task_id}/session-token",
        headers=_integration_headers(),
    )


app: FastAPI = create_app("api-gateway")
app.include_router(router)
app.include_router(integration_router)

INTEGRATION_ERROR_CODES = {
    400: 10001,
    401: 20001,
    403: 20003,
    404: 30017,
    409: 30019,
    413: 10001,
    422: 10001,
    429: 10017,
}


def _integration_error(request: Request, status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": INTEGRATION_ERROR_CODES.get(status_code, 50000),
            "message": message,
            "data": None,
            "trace_id": request.headers.get("x-request-id") or uuid.uuid4().hex,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if request.url.path.startswith("/api/v1/integration"):
        return _integration_error(request, exc.status_code, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def _validation_exception(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if request.url.path.startswith("/api/v1/integration"):
        return _integration_error(request, 400, "参数校验失败")
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})
