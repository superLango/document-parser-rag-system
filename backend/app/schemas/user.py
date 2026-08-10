"""用户与认证 Schema。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.rbac import RoleBrief


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1)
    email: str | None = None
    full_name: str | None = None


class ProfileUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    avatar: str | None = None


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=1)


class PasswordResetRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=1)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str | None = None
    password: str = Field(min_length=1)
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    is_superuser: bool = False
    role_codes: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    role_codes: list[str] | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str | None = None
    is_active: bool
    is_superuser: bool
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    notes: str | None = None
    avatar: str | None = None
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    password_changed_at: datetime | None = None
    created_at: datetime
    roles: list[RoleBrief] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
