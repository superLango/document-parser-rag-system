"""ORM 模型注册入口。"""

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.document import Document, DocumentTask, TaskDeadLetter, TaskOutbox
from app.models.extraction import (
    KbScript,
    PromptContent,
    PromptTemplate,
    RuleGroup,
    RuleGroupItem,
    SchemaCategory,
    SchemaField,
    SchemaTemplate,
)
from app.models.glossary import Term, TermBase
from app.models.indexing import DocumentChunk, KbBm25Stats, TextChunk
from app.models.knowledge_base import KbInvitation, KbMember, KnowledgeBase
from app.models.password import PasswordHistory, PasswordResetToken
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.user import User
from app.models.workspace import (
    Group,
    GroupMember,
    KbGroupAccess,
    Workspace,
    WorkspaceMember,
)

__all__ = [
    "ApiKey",
    "AuditLog",
    "Document",
    "DocumentChunk",
    "DocumentTask",
    "Group",
    "GroupMember",
    "KbBm25Stats",
    "KbGroupAccess",
    "KbInvitation",
    "KbMember",
    "KbScript",
    "KnowledgeBase",
    "PasswordHistory",
    "PasswordResetToken",
    "Permission",
    "PromptContent",
    "PromptTemplate",
    "Role",
    "RolePermission",
    "RuleGroup",
    "RuleGroupItem",
    "SchemaCategory",
    "SchemaField",
    "SchemaTemplate",
    "TaskDeadLetter",
    "TaskOutbox",
    "Term",
    "TermBase",
    "TextChunk",
    "User",
    "UserRole",
    "Workspace",
    "WorkspaceMember",
]
