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
    page_count: int = 0
    markdown_path: str | None = None
    layout_path: str | None = None
    pages_cleaned_at: datetime | None = None
    error: dict | None = None
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
