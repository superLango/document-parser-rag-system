"""审计日志 Schema。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None = None
    username: str | None = None
    kb_id: UUID | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    ip: str | None = None
    user_agent: str | None = None
    details: dict | None = None
    trace_id: str | None = None
    created_at: datetime
