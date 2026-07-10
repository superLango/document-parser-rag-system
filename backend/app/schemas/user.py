"""用户与认证 Schema 模块。

定义用户资源的请求与响应模型，以及 JWT Token 响应。
对应 User ORM 模型。

命名约定：UserBase / UserCreate / UserResponse。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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

    扩展 UserBase，增加密码字段。

    Attributes:
        password: 明文密码（创建后将被哈希存储）。
    """

    password: str


class UserResponse(UserBase):
    """用户响应模型。

    扩展 UserBase，增加数据库生成的字段。
    通过 from_attributes=True 支持从 ORM 模型实例转换。
    注意：不返回 password 字段。

    Attributes:
        id: 用户唯一标识。
        is_active: 是否启用。
        created_at: 创建时间。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT Token 响应模型。

    登录成功后返回，客户端在后续请求的 Authorization 头中携带 access_token。

    Attributes:
        access_token: JWT 访问令牌。
        token_type: 令牌类型，默认 "bearer"。
        expires_in: 过期时间（秒）。
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
