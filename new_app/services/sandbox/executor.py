"""Executor abstraction shared by Docker and Kubernetes backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from hanson_contracts import RuntimeInfo

from .config import Settings
from .workspace import Workspace


class ExecutorError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class RawExecution:
    exit_code: int = 0
    oom: bool = False
    timed_out: bool = False
    files: dict[str, bytes] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    image_digest: str = ""
    runtime: str = ""
    isolation: dict[str, Any] = field(default_factory=dict)
    detail: str = ""


class Executor(Protocol):
    async def execute(self, workspace: Workspace) -> RawExecution: ...

    async def info(self) -> RuntimeInfo: ...

    async def close(self) -> None: ...


def build_executor(settings: Settings) -> Executor:
    if settings.executor == "kubernetes":
        from .k8s_executor import KubernetesExecutor

        return KubernetesExecutor(settings)
    from .docker_executor import DockerExecutor

    return DockerExecutor(settings)
