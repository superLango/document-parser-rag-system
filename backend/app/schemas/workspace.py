"""P2 Schema：工作空间、群组、群组-知识库授权。"""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.workspace import GROUP_KB_ROLES, WORKSPACE_ROLES


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=3, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    config: dict = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,49}", v):
            raise ValueError("工作空间编码须以小写字母开头，仅含小写字母/数字/下划线")
        return v


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    config: dict | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    description: str | None = None
    owner_id: UUID
    config: dict = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    my_role: str | None = None
    member_count: int = 0


class WorkspaceMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    user_id: UUID
    username: str | None = None
    full_name: str | None = None
    role: str
    status: str
    created_at: datetime


class WorkspaceMemberAdd(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in WORKSPACE_ROLES:
            raise ValueError(f"非法角色：{v}")
        return v


class WorkspaceMemberRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in WORKSPACE_ROLES:
            raise ValueError(f"非法角色：{v}")
        return v


class WorkspaceTransferRequest(BaseModel):
    target_user_id: UUID


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=3, max_length=50)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,49}", v):
            raise ValueError("群组编码须以小写字母开头，仅含小写字母/数字/下划线")
        return v


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    code: str
    description: str | None = None
    created_at: datetime
    member_count: int = 0


class GroupMemberAdd(BaseModel):
    username: str = Field(min_length=1, max_length=50)


class KbGroupGrant(BaseModel):
    group_id: UUID
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in GROUP_KB_ROLES:
            raise ValueError(f"非法角色：{v}，可选 {sorted(GROUP_KB_ROLES)}")
        return v
