# ruff: noqa: B008
import hashlib
import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from .adapters.base import OcrBackendError
from .contracts import OcrRequest, OcrResult
from .service import get_store, parse_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")


@router.post("/ocr/parse", response_model=OcrResult)
async def parse(request: OcrRequest) -> OcrResult:
    store = get_store()
    try:
        data = await store.get_bytes(request.storage_key)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"document not found: {request.storage_key}"
        ) from exc
    return await _run(data, request)


@router.post("/ocr/parse-file", response_model=OcrResult)
async def parse_file(
    file: UploadFile = File(...),
    backend: str | None = Query(default=None),
) -> OcrResult:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    filename = file.filename or "upload.bin"
    document_id = hashlib.sha256(data).hexdigest()[:16]
    request = OcrRequest(
        document_id=document_id,
        storage_key="",
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        backend=backend,
    )
    return await _run(data, request)


async def _run(data: bytes, request: OcrRequest) -> OcrResult:
    try:
        return await parse_document(data, request, get_store())
    except OcrBackendError as exc:
        logger.warning("ocr backend failure code=%s detail=%s", exc.code, exc)
        raise HTTPException(
            status_code=502, detail={"code": exc.code, "message": str(exc)}
        ) from exc
