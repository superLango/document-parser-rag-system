# ruff: noqa: B008
from fastapi import APIRouter, HTTPException
from hanson_contracts import ExecutionRequest, ExecutionResult, RuntimeInfo

from .service import SandboxService

router = APIRouter(prefix="/internal/sandbox")

_service: SandboxService | None = None


def set_service(service: SandboxService | None) -> None:
    global _service
    _service = service


def get_service() -> SandboxService:
    if _service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "SANDBOX_UNAVAILABLE", "message": "sandbox service not ready"},
        )
    return _service


@router.post("/execute", response_model=ExecutionResult)
async def execute(request: ExecutionRequest) -> ExecutionResult:
    return await get_service().execute(request)


@router.get("/runtime", response_model=RuntimeInfo)
async def runtime_info() -> RuntimeInfo:
    service = get_service()
    return await service.executor.info()
