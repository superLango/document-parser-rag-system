"""ORM 模型注册入口。"""

from app.models.user import User
from app.models.password import PasswordHistory, PasswordResetToken
from app.models.audit_log import AuditLog
from app.models.knowledge_base import KbInvitation, KnowledgeBase, KbMember
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.workspace import (
    Group,
    GroupMember,
    KbGroupAccess,
    Workspace,
    WorkspaceMember,
)
from app.models.api_key import ApiKey
from app.models.document import Document, DocumentTask, TaskDeadLetter, TaskOutbox
from app.models.indexing import DocumentChunk, KbBm25Stats, TextChunk

__all__ = [
    "User",
    "PasswordHistory",
    "PasswordResetToken",
    "AuditLog",
    "KnowledgeBase",
    "KbMember",
    "KbInvitation",
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "Workspace",
    "WorkspaceMember",
    "Group",
    "GroupMember",
    "KbGroupAccess",
    "ApiKey",
    "Document",
    "DocumentTask",
    "TaskOutbox",
    "TaskDeadLetter",
    "DocumentChunk",
    "TextChunk",
    "KbBm25Stats",
]
