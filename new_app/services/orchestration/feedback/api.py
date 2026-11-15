# ruff: noqa: B008
from fastapi import APIRouter, Header, HTTPException, Query
from hanson_contracts import (
    CodeApprovalIn,
    FeedbackCreate,
    FeedbackDetail,
    FeedbackVerifyIn,
    VerificationPackage,
)

from ..config import settings
from .service import FeedbackError, FeedbackService

router = APIRouter(prefix="/internal/feedback")
_service = FeedbackService()


def _require_approval_token(token: str) -> None:
    if not settings.internal_api_token:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "APPROVAL_TOKEN_NOT_CONFIGURED",
                "message": "INTERNAL_API_TOKEN is not configured",
            },
        )
    if token != settings.internal_api_token:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "APPROVAL_TOKEN_INVALID",
                "message": "invalid approval token",
            },
        )


def _error(exc: FeedbackError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.post("", response_model=FeedbackDetail, status_code=201)
async def create_feedback(payload: FeedbackCreate) -> FeedbackDetail:
    try:
        return await _service.create(payload)
    except FeedbackError as exc:
        raise _error(exc) from exc


@router.get("", response_model=list[FeedbackDetail])
async def list_feedback(
    status: str = Query(default=""),
    document_id: str = Query(default=""),
    run_id: str = Query(default=""),
) -> list[FeedbackDetail]:
    return await _service.list(status=status, document_id=document_id, run_id=run_id)


@router.get("/{feedback_id}", response_model=FeedbackDetail)
async def get_feedback(feedback_id: str) -> FeedbackDetail:
    try:
        return await _service.get(feedback_id)
    except FeedbackError as exc:
        raise _error(exc) from exc


@router.post("/{feedback_id}/process", response_model=FeedbackDetail)
async def process_feedback(feedback_id: str) -> FeedbackDetail:
    try:
        return await _service.process(feedback_id)
    except FeedbackError as exc:
        raise _error(exc) from exc


@router.post("/{feedback_id}/approve-code", response_model=FeedbackDetail)
async def approve_code(
    feedback_id: str,
    payload: CodeApprovalIn,
    x_internal_token: str = Header(default=""),
) -> FeedbackDetail:
    _require_approval_token(x_internal_token)
    try:
        return await _service.approve_code(feedback_id, payload)
    except FeedbackError as exc:
        raise _error(exc) from exc


@router.get("/{feedback_id}/verification", response_model=VerificationPackage)
async def get_verification(feedback_id: str) -> VerificationPackage:
    try:
        return await _service.verification(feedback_id)
    except FeedbackError as exc:
        raise _error(exc) from exc


@router.post("/{feedback_id}/verify", response_model=FeedbackDetail)
async def verify_feedback(
    feedback_id: str, payload: FeedbackVerifyIn
) -> FeedbackDetail:
    try:
        return await _service.verify(feedback_id, payload)
    except FeedbackError as exc:
        raise _error(exc) from exc
