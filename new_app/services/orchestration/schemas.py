from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str
    size: int
    sha256: str
    status: str
    created_at: datetime
    # 仅 /documents 列表填充：最近一次 LIMS 对接任务的 task_id（非对接上传为空）
    task_id: str | None = None


class CreateRunIn(BaseModel):
    recipe_channel: Literal["stable", "candidate", "shadow"] = "stable"
    parse_profile: str = "standard"


class ReparseIn(BaseModel):
    """Optional parser bundle pin for candidate validation runs."""

    parser_version: str | None = None
    reuse_ocr: bool = False


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    document_version: int
    status: str
    stage: str
    progress: int = 0
    trace_id: str
    recipe_channel: str
    engine_version: str
    parser_version: str | None = None
    result_key: str | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # 仅 /runs 列表填充：最后一个阶段的结束时间（机器解析结束）
    parsed_at: datetime | None = None


class RunStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    stage: str
    status: str
    input_refs: dict
    output_refs: dict
    metrics: dict
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class RunEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    sequence: int
    type: str
    stage: str
    status: str
    payload: dict
    occurred_at: datetime


class RunTimelineOut(BaseModel):
    run: RunOut
    stages: list[RunStageOut]
    events: list[RunEventOut]


class RunResultOut(BaseModel):
    run_id: str
    status: str
    result: dict | None = None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    role: str
    storage_key: str
    sha256: str
    bytes: int
    created_at: datetime


class RunListOut(BaseModel):
    items: list[RunOut] = Field(default_factory=list)
    total: int = 0
