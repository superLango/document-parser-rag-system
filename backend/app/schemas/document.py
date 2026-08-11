"""Phase 1 文档/任务 Schema。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kb_id: UUID
    filename: str
    file_type: str | None = None
    file_size: int
    sha256: str
    status: str
    process_status: str
    progress_page: int | None = None
    progress_total: int | None = None
    page_count: int = 0
    markdown_path: str | None = None
    layout_path: str | None = None
    pages_cleaned_at: datetime | None = None
    error: dict | None = None
    # S4/D8 独立索引状态（解析状态与索引状态互不覆盖）
    index_status: str = "not_indexed"
    index_progress: int | None = None
    index_total: int | None = None
    index_error: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None


class DocumentTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kb_id: UUID
    document_id: UUID
    task_id: str
    type: str
    filename: str | None = None
    status: str
    attempts: int
    heartbeat_at: datetime | None = None
    checkpoint: dict = {}
    error: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None


class UploadDocumentOut(BaseModel):
    document: DocumentOut
    task: DocumentTaskOut
