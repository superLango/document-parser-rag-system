# ruff: noqa: B008
from fastapi import APIRouter, HTTPException
from hanson_contracts import AgentResult, AgentResumeRequest, AgentTask

from .runtime import AgentRuntime

router = APIRouter(prefix="/internal/agent")

_runtime: AgentRuntime | None = None


def set_runtime(runtime: AgentRuntime | None) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> AgentRuntime:
    if _runtime is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "AGENT_UNAVAILABLE", "message": "agent runtime not ready"},
        )
    return _runtime


@router.post(":run", response_model=AgentResult)
async def run(task: AgentTask) -> AgentResult:
    try:
        return await get_runtime().run(task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(":resume", response_model=AgentResult)
async def resume(request: AgentResumeRequest) -> AgentResult:
    try:
        return await get_runtime().resume(request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/health")
async def health() -> dict:
    return await get_runtime().health()
