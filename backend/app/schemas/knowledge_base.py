"""知识库 Schema 模块。

定义知识库资源（KnowledgeBase）与成员关系（KbMember）的请求/响应模型，
对应 ``app.models.knowledge_base`` ORM 模型。

命名约定：KnowledgeBaseBase / Create / Update / Response；KbMemberBase / Add / Update / Response。

知识库管理 API（方案 §10.1）：
- GET    /kbs/                 我参与的知识库列表
- POST   /kbs/                 新建知识库（自动初始化物理资源 + 成为 owner）
- GET    /kbs/{kb_id}          知识库详情
- PUT    /kbs/{kb_id}          更新基础信息（owner/admin）
- DELETE /kbs/{kb_id}          删除知识库（owner，彻底销毁物理资源）
- PATCH  /kbs/{kb_id}/active   启用/停用（owner/admin）
- GET/POST/PUT/DELETE /kbs/{kb_id}/members  成员管理（owner/admin）
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.knowledge_base import ALL_ROLES, ROLE_OWNER


# ============================================================
# 知识库主表 Schema
# ============================================================
class KnowledgeBaseBase(BaseModel):
    """知识库基础属性。"""

    name: str = Field(..., min_length=1, max_length=100, description="知识库名称")
    description: str | None = Field(None, max_length=500, description="知识库描述")
    domain_code: str = Field(..., min_length=1, max_length=64, description="领域编码")
    template_code: str | None = Field(
        None, max_length=64, description="初始化所用领域模板编码（None=空白知识库）"
    )


class KnowledgeBaseCreate(KnowledgeBaseBase):
    """新建知识库请求。

    Attributes:
        config: 可选的初始配置覆盖项，将与领域模板默认配置合并。
    """

    config: dict = Field(default_factory=dict, description="初始配置覆盖项")


class KnowledgeBaseUpdate(BaseModel):
    """更新知识库基础信息请求（仅 owner/admin 可调用）。

    所有字段可选，未提供的字段保持不变。config 字段不在此处更新
    （配置中心有独立端点 /kbs/{kb_id}/config/*）。
    """

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    sort_order: int | None = Field(None, ge=0)


class KnowledgeBaseActiveUpdate(BaseModel):
    """启用/停用知识库请求。"""

    is_active: bool = Field(..., description="是否启用")


class KnowledgeBaseResponse(KnowledgeBaseBase):
    """知识库响应模型。

    通过 from_attributes=True 支持从 ORM 模型转换。
    额外返回 ``my_role``（当前用户在该 KB 中的角色，超管为 owner），
    便于前端判断可用操作。

    Attributes:
        id: 知识库唯一标识。
        owner_id: 所有者用户 ID。
        config: 全流程配置 JSON。
        is_active: 是否启用。
        sort_order: 排序权重。
        created_at: 创建时间。
        updated_at: 更新时间。
        my_role: 当前用户在该 KB 中的角色（列表接口填充）。
        member_count: 成员数量（详情接口填充）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    config: dict
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime | None = None
    my_role: str | None = None
    member_count: int | None = None


# ============================================================
# 成员管理 Schema
# ============================================================
class KbMemberAdd(BaseModel):
    """添加成员请求。

    Attributes:
        user_id: 待添加用户 ID。
        role: 角色（owner/admin/editor/viewer）。不可添加 owner（每 KB 仅一个 owner）。
    """

    user_id: UUID = Field(..., description="待添加用户 ID")
    role: str = Field(..., description=f"角色，可选 {list(ALL_ROLES)}（不含 owner）")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """校验角色合法且不可为 owner（owner 仅在新建 KB 时自动产生）。"""
        if v not in ALL_ROLES:
            raise ValueError(f"非法角色 {v}，合法角色为 {list(ALL_ROLES)}")
        if v == ROLE_OWNER:
            raise ValueError("不可手动添加 owner 角色（每 KB 仅一个 owner）")
        return v


class KbMemberUpdate(BaseModel):
    """修改成员角色请求。

    Attributes:
        role: 新角色（admin/editor/viewer，不可改为 owner）。
    """

    role: str = Field(..., description=f"新角色，可选 admin/editor/viewer")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """校验角色合法且不可为 owner。"""
        if v not in ALL_ROLES:
            raise ValueError(f"非法角色 {v}，合法角色为 {list(ALL_ROLES)}")
        if v == ROLE_OWNER:
            raise ValueError("不可将成员改为 owner 角色")
        return v


class KbMemberResponse(BaseModel):
    """成员响应模型。

    Attributes:
        id: 成员关系唯一标识。
        kb_id: 所属知识库 ID。
        user_id: 用户 ID。
        username: 用户名（联表查询填充）。
        email: 用户邮箱（联表查询填充）。
        avatar: 用户头像（联表查询填充）。
        role: 角色。
        created_at: 加入时间。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kb_id: UUID
    user_id: UUID
    username: str | None = None
    email: str | None = None
    avatar: str | None = None
    role: str
    created_at: datetime


# ============================================================
# 统计 Schema
# ============================================================
class KnowledgeBaseStatsResponse(BaseModel):
    """知识库统计信息响应。"""

    kb_id: UUID
    kb_name: str
    total_documents: int = 0
    total_chunks: int = 0
    total_tasks: int = 0
    total_members: int = 0
