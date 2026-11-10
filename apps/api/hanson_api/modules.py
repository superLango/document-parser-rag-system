"""功能模块层：四个业务功能与内置模块工作区。

产品不再向用户暴露“知识库”，但底层仍复用 ``knowledge_bases`` 记录作为模块
工作区（每个模块在当前工作空间内固定一条）。模块对工作空间全员可见，写权限
由平台角色或工作空间角色决定，不再依赖知识库成员表。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .access import KB_ROLE_RANK, Principal, default_workspace, workspace_role
from .models import (
    Document,
    DocumentTask,
    KnowledgeBase,
    Workspace,
    WorkspaceMember,
)


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    name: str
    summary: str
    description: str
    status: str  # active / planned
    input_types: tuple[str, ...]
    highlights: tuple[str, ...]
    schema_template: str | None = None


MODULES: dict[str, ModuleSpec] = {
    "standard_split": ModuleSpec(
        key="standard_split",
        name="标准拆分",
        summary="上传标准原文，自动拆分为结构化条目并完成复核",
        description=(
            "面向金属材料标准文档，完成版面与表格识别、条款拆分、"
            "业务词典对齐与字段级复核，产出可直接下游消费的结构化数据。"
        ),
        status="active",
        input_types=("PDF", "Markdown"),
        highlights=(
            "版面与表格自动识别",
            "业务词典自动对齐",
            "字段级人工复核",
            "结构化结果导出",
        ),
        schema_template="product_standard.json",
    ),
    "order_parse": ModuleSpec(
        key="order_parse",
        name="委托单解析",
        summary="从委托单中提取委托方、样品与检测项目信息",
        description=(
            "解析检测委托单，抽取委托单位、样品编号、检测项目与时限要求，"
            "生成可导入业务系统的结构化记录。"
        ),
        status="planned",
        input_types=("PDF", "扫描件"),
        highlights=("委托信息提取", "样品明细识别", "检测项目匹配"),
    ),
    "certificate_parse": ModuleSpec(
        key="certificate_parse",
        name="质保书解析",
        summary="提取质保书中的牌号、批次与力学性能数据",
        description=(
            "解析产品质量证明书，抽取牌号、炉批号、化学成分与力学性能，"
            "并校验证书内部数据的一致性。"
        ),
        status="planned",
        input_types=("PDF", "扫描件"),
        highlights=("牌号与批次识别", "性能指标提取", "证书一致性校验"),
    ),
    "outsource_report": ModuleSpec(
        key="outsource_report",
        name="委外报告解析",
        summary="汇总委外检测报告的关键结论与数据",
        description=(
            "解析委外检测报告，提取检测机构、报告编号、检测项目与结论，"
            "支持多份报告的汇总与比对。"
        ),
        status="planned",
        input_types=("PDF", "Excel"),
        highlights=("报告要素提取", "检测结论归集", "多报告汇总"),
    ),
}

MODULE_KEYS = tuple(MODULES.keys())


def module_spec(module_key: str) -> ModuleSpec:
    spec = MODULES.get(module_key)
    if spec is None:
        raise HTTPException(status_code=404, detail="module not found")
    return spec


def module_key_of(kb: KnowledgeBase | None) -> str | None:
    if kb is None:
        return None
    config = kb.config or {}
    value = config.get("module")
    return value if isinstance(value, str) and value in MODULES else None


def module_workspace_id(db: Session, principal: Principal) -> str:
    """模块工作区：用户取首个已加入的工作空间，API Key 取其绑定的工作空间。"""

    if principal.anonymous:
        # 免登录模式：使用首个工作空间，避免访客自建空工作区而看不到已有文档。
        workspace = db.scalar(
            select(Workspace)
            .where(Workspace.deleted_at.is_(None))
            .order_by(Workspace.created_at.asc())
            .limit(1)
        )
        if workspace is not None:
            return workspace.id
        if principal.user is None:
            raise HTTPException(status_code=500, detail="anonymous user missing")
        return default_workspace(db, principal.user).id
    if principal.actor_type == "api_key":
        if not principal.workspace_id:
            raise HTTPException(status_code=403, detail="API key has no workspace")
        return principal.workspace_id
    if principal.user is None:
        raise HTTPException(status_code=403, detail="user token required")
    workspace = db.scalar(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == principal.user.id,
            Workspace.deleted_at.is_(None),
        )
        .order_by(
            case(
                (WorkspaceMember.role.in_(["owner", "admin"]), 0),
                else_=1,
            ),
            Workspace.created_at.asc(),
        )
        .limit(1)
    )
    if workspace is not None:
        return workspace.id
    return default_workspace(db, principal.user).id


def find_module_kb(
    db: Session, workspace_id: str, module_key: str
) -> KnowledgeBase | None:
    rows = (
        db.execute(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.workspace_id == workspace_id,
                KnowledgeBase.deleted_at.is_(None),
            )
            .order_by(KnowledgeBase.created_at.asc())
        )
        .scalars()
        .all()
    )
    for kb in rows:
        if module_key_of(kb) == module_key:
            return kb
    return None


def ensure_module_kb(
    db: Session, workspace_id: str, module_key: str, owner_id: str
) -> tuple[KnowledgeBase, bool]:
    """返回模块内置知识库，缺失则创建（不提交事务）。"""

    spec = module_spec(module_key)
    existing = find_module_kb(db, workspace_id, module_key)
    if existing is not None:
        return existing, False
    kb = KnowledgeBase(
        workspace_id=workspace_id,
        name=spec.name,
        description=spec.summary,
        owner_id=owner_id,
        config={"module": module_key, "builtin": True},
    )
    db.add(kb)
    db.flush()
    return kb, True


def module_role(
    db: Session, principal: Principal, kb: KnowledgeBase
) -> str | None:
    """模块角色：工作空间成员可见，管理员/编辑可写，不再看知识库成员。"""

    if principal.anonymous:
        return "owner"
    if principal.actor_type == "api_key":
        if principal.workspace_id != kb.workspace_id:
            return None
        if workspace_role(db, principal.actor_id, kb.workspace_id) is None:
            return None
        allowed = principal.kb_ids or set()
        module_key = module_key_of(kb)
        if allowed and kb.id not in allowed and module_key not in allowed:
            return None
        cap = "editor" if "documents:write" in principal.scopes else "viewer"
        return cap

    ws_role = workspace_role(db, principal.actor_id, kb.workspace_id)
    if ws_role is None:
        return None
    if principal.user is not None and principal.user.role in {"admin", "editor"}:
        return "owner"
    if ws_role in {"owner", "admin"}:
        return "owner"
    return "viewer"


def resolve_module(
    db: Session,
    principal: Principal,
    module_key: str,
    minimum: str = "viewer",
) -> KnowledgeBase:
    """解析并校验模块；仅已开放模块可访问。"""

    spec = module_spec(module_key)
    if spec.status != "active":
        raise HTTPException(
            status_code=409, detail=f"module {module_key} is not available yet"
        )
    workspace_id = module_workspace_id(db, principal)
    kb, created = ensure_module_kb(
        db, workspace_id, module_key, principal.actor_id
    )
    if created:
        db.commit()
        db.refresh(kb)
    role = module_role(db, principal, kb)
    if role is None or KB_ROLE_RANK[role] < KB_ROLE_RANK[minimum]:
        raise HTTPException(status_code=403, detail="not allowed for this module")
    return kb


def module_stats(db: Session, kb: KnowledgeBase | None) -> dict[str, int]:
    if kb is None:
        return {
            "document_count": 0,
            "task_count": 0,
            "pending_review_count": 0,
            "confirmed_count": 0,
        }
    document_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.kb_id == kb.id, Document.deleted_at.is_(None)
        )
    )
    pending_review_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.kb_id == kb.id,
            Document.deleted_at.is_(None),
            Document.review_status == "review",
        )
    )
    confirmed_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.kb_id == kb.id,
            Document.deleted_at.is_(None),
            Document.review_status == "confirmed",
        )
    )
    task_count = db.scalar(
        select(func.count(DocumentTask.id))
        .join(Document, DocumentTask.document_id == Document.id)
        .where(Document.kb_id == kb.id, Document.deleted_at.is_(None))
    )
    return {
        "document_count": int(document_count or 0),
        "task_count": int(task_count or 0),
        "pending_review_count": int(pending_review_count or 0),
        "confirmed_count": int(confirmed_count or 0),
    }
