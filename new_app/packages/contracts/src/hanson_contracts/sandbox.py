"""Sandbox execution contract shared by orchestration and the sandbox service.

The contract is deliberately storage-neutral: inputs are referenced by object
storage key, outputs are returned as object storage keys with sha256 digests.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Status = Literal["succeeded", "failed", "timeout", "oom", "invalid_output", "rejected"]

OUTPUT_ROLES = (
    "result",
    "records",
    "evidence",
    "diagnostics",
    "metrics",
    "manifest",
)

ENGINE_API = "sandbox-engine/1"
SCHEMA_VERSION = "1.0"


class ResourceLimits(BaseModel):
    cpu: float = Field(default=1.0, gt=0, le=16)
    memory_mb: int = Field(default=512, ge=32, le=32768)
    pids: int = Field(default=128, ge=8, le=4096)
    timeout_seconds: int = Field(default=120, ge=1, le=1800)
    tmpfs_mb: int = Field(default=64, ge=8, le=1024)


class DocumentRef(BaseModel):
    document_id: str = ""
    filename: str = ""
    storage_key: str = ""
    sha256: str = ""
    size: int = 0
    content_type: str = "application/octet-stream"


class ObjectInput(BaseModel):
    """An input artifact stored in the shared object store."""

    storage_key: str
    sha256: str = ""

    @field_validator("storage_key")
    @classmethod
    def _no_traversal(cls, value: str) -> str:
        if not value or value.startswith("/") or ".." in value.split("/"):
            raise ValueError(f"invalid storage key: {value}")
        return value


class TableAssignment(BaseModel):
    table_id: str
    recipe_id: str
    version: str
    digest: str = ""


class RecipeRef(BaseModel):
    recipe_id: str
    version: str
    digest: str = ""
    # Optional inline package; used for entrypoint recipes and tests. When present
    # the sandbox service validates it against ``digest`` before mounting.
    manifest: dict[str, Any] | None = None
    files: dict[str, str] = Field(default_factory=dict)

    @field_validator("files")
    @classmethod
    def _safe_files(cls, value: dict[str, str]) -> dict[str, str]:
        for path in value:
            parts = path.split("/")
            if path.startswith("/") or ".." in parts or "\\" in path:
                raise ValueError(f"invalid recipe file path: {path}")
        return value


class TemplateRef(BaseModel):
    template_id: str
    version: str
    digest: str = ""
    definition: dict[str, Any] | None = None


class EngineRef(BaseModel):
    api: str = ENGINE_API
    version: str = "sandbox-engine/1"
    image: str = ""
    runtime: str = ""


class ExecutionRequest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    trace_id: str
    run_id: str
    document: DocumentRef = Field(default_factory=DocumentRef)
    ocr: ObjectInput
    assignments: list[TableAssignment] = Field(default_factory=list)
    recipe: RecipeRef
    template: TemplateRef
    engine: EngineRef = Field(default_factory=EngineRef)
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("trace_id", "run_id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        if not value or len(value) > 128:
            raise ValueError("trace_id/run_id must be 1..128 characters")
        if any(ch in value for ch in "/\\\x00"):
            raise ValueError("trace_id/run_id must not contain path separators")
        return value


class ExecutionOutput(BaseModel):
    role: str
    storage_key: str
    sha256: str
    bytes: int = 0
    content_type: str = "application/json"


class ExecutionMetrics(BaseModel):
    duration_ms: int = 0
    exit_code: int = 0
    memory_limit_mb: int = 0
    cpu_limit: float = 0.0
    peak_memory_mb: int | None = None


class ExecutionManifest(BaseModel):
    schema_version: str = "sandbox-manifest/1"
    engine_version: str = ""
    engine_image: str = ""
    engine_image_digest: str = ""
    runtime: str = ""
    recipe: dict[str, Any] = Field(default_factory=dict)
    template: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    isolation: dict[str, Any] = Field(default_factory=dict)


class ExecutionDiagnostic(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    detail: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str = ""
    trace_id: str = ""
    status: Status = "failed"
    error_code: str | None = None
    error_message: str = ""
    outputs: dict[str, ExecutionOutput] = Field(default_factory=dict)
    metrics: ExecutionMetrics = Field(default_factory=ExecutionMetrics)
    manifest: ExecutionManifest = Field(default_factory=ExecutionManifest)
    diagnostics: list[ExecutionDiagnostic] = Field(default_factory=list)
    stderr: str = ""


class RuntimeInfo(BaseModel):
    executor: str = ""
    runtime: str = ""
    engine_image: str = ""
    engine_image_digest: str = ""
    available: bool = False
    isolation: dict[str, Any] = Field(default_factory=dict)
    detail: str = ""
