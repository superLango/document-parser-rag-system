"""Pydantic Schema 包。

聚合导出所有资源的请求/响应模型，遵循统一命名约定：
XxxBase / XxxCreate / XxxUpdate / XxxResponse。

子模块：
- common: 通用分页参数与统一响应体
- document: 文档资源
- knowledge_base: 知识库与成员管理
- task: 异步任务
- schema_model: Schema 配置（文件名避开与包名冲突）
- term: 术语库
- user: 用户与认证
"""

from app.schemas.common import ApiResponse, PaginationParams
from app.schemas.document import (
    DocumentBase,
    DocumentCreate,
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdate,
)
from app.schemas.knowledge_base import (
    KbMemberAdd,
    KbMemberResponse,
    KbMemberUpdate,
    KnowledgeBaseActiveUpdate,
    KnowledgeBaseBase,
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseStatsResponse,
    KnowledgeBaseUpdate,
)
from app.schemas.kb_config import (
    ApplyTemplateRequest,
    ApplyTemplateResult,
    KbCategoryCreate,
    KbCategoryResponse,
    KbCategoryUpdate,
    KbConfigResponse,
    KbConfigSectionUpdate,
    KbConfigUpdate,
    KbConfigValidationResult,
    KbFieldTemplateResponse,
    KbHookContent,
    KbHookInfo,
    KbHookReloadResult,
    KbHookUpdate,
    KbRegexRuleResponse,
    KbResourceVerifyResult,
)
from app.schemas.schema_model import (
    SchemaConfigBase,
    SchemaConfigCreate,
    SchemaConfigResponse,
    SchemaConfigUpdate,
)
from app.schemas.task import (
    TaskListResponse,
    TaskResponse,
    TaskSubmitResponse,
)
from app.schemas.term import (
    TermBase,
    TermCreate,
    TermResponse,
    TermUpdate,
)
from app.schemas.user import (
    TokenResponse,
    UserBase,
    UserCreate,
    UserResponse,
)

__all__ = [
    # common
    "PaginationParams",
    "ApiResponse",
    # document
    "DocumentBase",
    "DocumentCreate",
    "DocumentUpdate",
    "DocumentResponse",
    "DocumentListResponse",
    # knowledge_base
    "KnowledgeBaseBase",
    "KnowledgeBaseCreate",
    "KnowledgeBaseUpdate",
    "KnowledgeBaseActiveUpdate",
    "KnowledgeBaseResponse",
    "KnowledgeBaseStatsResponse",
    "KbMemberAdd",
    "KbMemberUpdate",
    "KbMemberResponse",
    # kb_config
    "ApplyTemplateRequest",
    "ApplyTemplateResult",
    "KbCategoryCreate",
    "KbCategoryResponse",
    "KbCategoryUpdate",
    "KbConfigResponse",
    "KbConfigSectionUpdate",
    "KbConfigUpdate",
    "KbConfigValidationResult",
    "KbFieldTemplateResponse",
    "KbHookContent",
    "KbHookInfo",
    "KbHookReloadResult",
    "KbHookUpdate",
    "KbRegexRuleResponse",
    "KbResourceVerifyResult",
    # task
    "TaskResponse",
    "TaskListResponse",
    "TaskSubmitResponse",
    # schema_model
    "SchemaConfigBase",
    "SchemaConfigCreate",
    "SchemaConfigUpdate",
    "SchemaConfigResponse",
    # term
    "TermBase",
    "TermCreate",
    "TermUpdate",
    "TermResponse",
    # user
    "UserBase",
    "UserCreate",
    "UserResponse",
    "TokenResponse",
]
