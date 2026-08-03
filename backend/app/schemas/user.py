"""用户与认证 Schema 模块（阶段 1.1 扩展）。

定义用户资源的请求与响应模型，以及 JWT Token 响应。
对应 User ORM 模型。

命名约定：UserBase / UserCreate / UserUpdate / UserResponse。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserBase(BaseModel):
    """用户基础属性。

    Attributes:
        username: 用户名。
        email: 邮箱，可为空。
    """

    username: str
    email: str | None = None


class UserCreate(UserBase):
    """用户创建参数。

    扩展 UserBase，增加密码与档案字段。

    Attributes:
        password: 明文密码（创建后将被哈希存储）。
        full_name: 姓名。
        phone: 手机号。
        department: 部门。
        is_superuser: 是否超管（仅超管可创建超管）。
    """

    password: str
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    is_superuser: bool = False


class UserUpdate(BaseModel):
    """用户更新参数（管理员编辑用户）。所有字段可选。"""

    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None


class ProfileUpdate(BaseModel):
    """个人中心信息更新（用户自助）。"""

    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    avatar: str | None = None


class PasswordChangeRequest(BaseModel):
    """修改密码请求（需提供旧密码）。"""

    old_password: str
    new_password: str = Field(min_length=1)


class PasswordResetRequest(BaseModel):
    """密码重置请求（携带重置令牌，无需旧密码）。"""

    token: str
    new_password: str = Field(min_length=1)


class UserResponse(UserBase):
    """用户响应模型。

    扩展 UserBase，增加数据库生成的字段。
    通过 from_attributes=True 支持从 ORM 模型实例转换。
    注意：不返回 password 字段。

    Attributes:
        id: 用户唯一标识。
        is_active: 是否启用。
        is_superuser: 是否超管。
        full_name: 姓名。
        phone: 手机号。
        department: 部门。
        avatar: 头像 URL。
        last_login_at: 最近登录时间。
        created_at: 创建时间。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    is_superuser: bool
    full_name: str | None = None
    phone: str | None = None
    department: str | None = None
    avatar: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT Token 响应模型。

    登录成功后返回，客户端在后续请求的 Authorization 头中携带 access_token。
    refresh_token 用于在 access_token 过期后静默续期（P2-7）。

    Attributes:
        access_token: JWT 访问令牌。
        refresh_token: JWT 刷新令牌（有效期更长，用于换取新 access_token）。
        token_type: 令牌类型，默认 "bearer"。
        expires_in: 过期时间（秒）。
    """

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int


class RegisterRequest(BaseModel):
    """用户注册请求（生产级开放注册，默认创建为普通用户）。"""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1)
    email: str | None = None
    full_name: str | None = None
