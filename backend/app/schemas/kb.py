"""知识库资源级 ACL Schema（P1）。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.knowledge_base import ALL_ROLES, ROLE_OWNER


class KbMemberSeed(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in ALL_ROLES or v == ROLE_OWNER:
            raise ValueError("不能通过邀请授予所有者角色")
        return v


class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    domain_code: str = Field(default="general", min_length=1, max_length=64)
    template_code: str | None = Field(default=None, max_length=64)
    config: dict = Field(default_factory=dict)
    members: list[KbMemberSeed] = Field(default_factory=list, max_length=50)


class KbExternalUpdate(BaseModel):
    enabled: bool = False
    regenerate: bool = False


class KbUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    domain_code: str | None = Field(default=None, min_length=1, max_length=64)
    template_code: str | None = Field(default=None, max_length=64)
    config: dict | None = None


class KbOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    domain_code: str
    template_code: str | None = None
    owner_id: UUID
    config: dict = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None
    my_role: str | None = None
    member_count: int = 0


class KbMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kb_id: UUID
    user_id: UUID
    username: str | None = None
    full_name: str | None = None
    role: str
    status: str
    invited_by: UUID | None = None
    expires_at: datetime | None = None
    created_at: datetime


class KbInviteCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    role: str = "viewer"
    expires_at: datetime | None = None

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in ALL_ROLES or v == ROLE_OWNER:
            raise ValueError("不能通过邀请授予所有者角色")
        return v


class KbMemberRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in ALL_ROLES:
            raise ValueError(f"非法角色：{v}，可选 {sorted(ALL_ROLES)}")
        return v


class KbTransferRequest(BaseModel):
    target_user_id: UUID


class KbInvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    token: str
    kb_id: UUID
    kb_name: str | None = None
    inviter_id: UUID
    inviter_username: str | None = None
    invitee_id: UUID
    role: str
    status: str
    expires_at: datetime | None = None
    created_at: datetime


class KbInvitationAcceptOut(BaseModel):
    kb_id: UUID
    kb_name: str
    role: str
    status: str
