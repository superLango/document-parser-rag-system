"""RBAC Schema：角色、权限点、权限矩阵。"""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RoleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    is_system: bool


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None = None
    is_system: bool
    sort_order: int
    created_at: datetime


class RoleWithPermissions(RoleOut):
    permissions: list[str] = []


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    resource_type: str | None = None
    description: str | None = None


class RoleCreate(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,49}", v):
            raise ValueError("角色编码须以小写字母开头，仅含小写字母/数字/下划线，长度 3-50")
        return v


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class RolePermissionsUpdate(BaseModel):
    permission_codes: list[str] = Field(default_factory=list)

    @field_validator("permission_codes")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class UserRoleAssign(BaseModel):
    role_codes: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("role_codes")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))
