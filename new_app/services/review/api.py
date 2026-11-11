# ruff: noqa: B008
from fastapi import APIRouter, HTTPException
from hanson_contracts import ReviewReport, ReviewRequest

from .service import ReviewService

router = APIRouter(prefix="/internal")

_service: ReviewService | None = None


def set_service(service: ReviewService | None) -> None:
    global _service
    _service = service


def get_service() -> ReviewService:
    if _service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "REVIEW_UNAVAILABLE", "message": "review service not ready"},
        )
    return _service


@router.post("/review", response_model=ReviewReport)
async def review(request: ReviewRequest) -> ReviewReport:
    return await get_service().review(request)


@router.get("/review/rules")
async def rules() -> dict:
    return {
        "ruleset_version": get_service().settings.ruleset_version,
        "rules": [
            "M5-ID-001",
            "M5-ID-002",
            "M5-GRADE-001",
            "M5-PROP-001",
            "M5-PROP-002",
            "M5-EVID-001",
            "M5-EVID-002",
            "M5-VALUE-001",
            "M5-VALUE-002",
            "M5-UNIT-001",
            "M5-DUP-001",
            "M5-TABLE-001",
        ],
    }
