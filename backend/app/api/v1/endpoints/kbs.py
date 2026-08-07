"""知识库管理端点模块（方案 §10.1）。

提供知识库 CRUD 与成员管理接口，所有 KB 内操作通过 ``get_kb_context`` /
``require_role`` 守卫，强制知识库隔离与 RBAC 权限校验。

端点清单：
- GET    /kbs/                      我参与的知识库列表
- POST   /kbs/                      新建知识库（初始化物理资源 + 成为 owner）
- GET    /kbs/{kb_id}               知识库详情
- PUT    /kbs/{kb_id}               更新基础信息（owner/admin）
- DELETE /kbs/{kb_id}               删除知识库（owner，彻底销毁物理资源）
- PATCH  /kbs/{kb_id}/active        启用/停用（owner/admin）
- GET    /kbs/{kb_id}/stats         知识库统计
- GET    /kbs/{kb_id}/members       成员列表（owner/admin）
- POST   /kbs/{kb_id}/members       添加成员（owner/admin）
- PUT    /kbs/{kb_id}/members/{user_id}  修改成员角色（owner/admin）
- DELETE /kbs/{kb_id}/members/{user_id}  移除成员（owner/admin）

注意：本模块与现有 ``knowledge_base.py``（旧索引管理端点）共存，
后者在阶段 3 改造为 ``/kbs/{kb_id}/kb/...``。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import KBContext, get_current_active_user, get_kb_context, require_role
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode, PermissionException
from app.core.logging import get_logger
from app.core.response import paginated, success
from app.models.document import Document
from app.models.knowledge_base import (
    EDIT_ROLES,
    MANAGE_ROLES,
    KnowledgeBase,
    KbMember,
    ROLE_OWNER,
)
from app.models.task import Task
from app.models.user import User
from app.schemas.knowledge_base import (
    KbMemberAdd,
    KbMemberResponse,
    KbMemberUpdate,
    KnowledgeBaseActiveUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseStatsResponse,
    KnowledgeBaseUpdate,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/kbs", tags=["知识库管理"])


# ============================================================
# 知识库列表与新建（全局，无 kb 上下文）
# ============================================================
@router.get("", response_model_exclude_none=True)
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> dict:
    """获取当前用户参与的知识库列表。

    超管可查看全部知识库。普通用户仅可见已加入成员的知识库。
    返回每条 KB 的 ``my_role`` 便于前端判断可用操作。

    Args:
        db: 异步数据库会话。
        current_user: 当前已认证用户。
        page: 页码。
        page_size: 每页条数。

    Returns:
        dict: 分页响应，items 为 KnowledgeBaseResponse 列表。
    """
    # 基础查询：超管看全部，普通用户按成员关系过滤
    if current_user.is_superuser:
        base_stmt = select(KnowledgeBase)
        count_stmt = select(func.count()).select_from(KnowledgeBase)
    else:
        base_stmt = (
            select(KnowledgeBase)
            .join(KbMember, KbMember.kb_id == KnowledgeBase.id)
            .where(KbMember.user_id == current_user.id)
        )
        count_stmt = (
            select(func.count())
            .select_from(KnowledgeBase)
            .join(KbMember, KbMember.kb_id == KnowledgeBase.id)
            .where(KbMember.user_id == current_user.id)
        )

    # 仅查询启用中的 KB（停用的也列出，便于管理；前端可标记）
    total_result = await db.execute(count_stmt)
    total: int = total_result.scalar_one()

    # 分页 + 排序
    rows_result = await db.execute(
        base_stmt.order_by(KnowledgeBase.sort_order, KnowledgeBase.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    kbs = rows_result.scalars().all()

    # 批量查询当前用户在各 KB 的角色
    kb_ids = [kb.id for kb in kbs]
    role_map: dict[uuid.UUID, str] = {}
    if kb_ids:
        role_stmt = select(KbMember.kb_id, KbMember.role).where(
            KbMember.user_id == current_user.id, KbMember.kb_id.in_(kb_ids)
        )
        role_result = await db.execute(role_stmt)
        for kb_id, role in role_result.all():
            role_map[kb_id] = role

    items: list[dict] = []
    for kb in kbs:
        item = KnowledgeBaseResponse.model_validate(kb).model_dump()
        # 超管对未加入的 KB 也按 owner 处理
        item["my_role"] = role_map.get(kb.id, ROLE_OWNER if current_user.is_superuser else None)
        items.append(item)

    return paginated(items=items, total=total, page=page, page_size=page_size)


@router.post("", status_code=201, response_model_exclude_none=True)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """新建知识库。

    处理流程：
        1. 创建 KnowledgeBase 记录（owner_id = 当前用户）。
        2. 创建 KbMember（owner 角色）。
        3. 提交事务。
        4. 调用 ``kb_lifecycle.create_kb_resources`` 初始化物理资源
           （Milvus/MinIO/NebulaGraph/Redis/文件系统）。
        5. 若指定 ``template_code``，调用领域模板初始化（阶段 4）。
        6. 返回 KB 详情 + 资源创建结果。

    资源创建失败不回滚 DB 记录（KB 已建立，可在配置中心重试资源初始化），
    仅在响应中标记失败步骤。

    Args:
        payload: 新建知识库请求体。
        db: 异步数据库会话。
        current_user: 当前已认证用户（自动成为 owner）。

    Returns:
        dict: 包含知识库详情与资源初始化结果的响应。
    """
    # 1. 创建知识库记录
    kb = KnowledgeBase(
        name=payload.name,
        description=payload.description,
        domain_code=payload.domain_code,
        template_code=payload.template_code,
        owner_id=current_user.id,
        config=payload.config if isinstance(payload.config, dict) else {},
    )
    db.add(kb)
    await db.flush()  # 取 kb.id

    # 2. 创建 owner 成员关系
    member = KbMember(kb_id=kb.id, user_id=current_user.id, role=ROLE_OWNER)
    db.add(member)
    await db.commit()
    await db.refresh(kb)

    logger.info(
        "知识库已创建",
        kb_id=str(kb.id),
        kb_name=kb.name,
        owner_id=str(current_user.id),
        template_code=payload.template_code,
    )

    # 3. 初始化物理资源（失败不回滚 DB）
    from app.services.kb.kb_lifecycle import kb_lifecycle

    resource_result = await kb_lifecycle.create_kb_resources(kb.id)

    # 4. 领域模板初始化（domain_template_service 已实现）
    template_result: dict = {"applied": False}
    if payload.template_code:
        try:
            from app.services.kb.domain_template_service import init_kb_from_template

            await init_kb_from_template(kb.id, payload.template_code, db)
            template_result = {"applied": True, "template_code": payload.template_code}
        except Exception as e:  # noqa: BLE001
            logger.error(
                "领域模板初始化失败",
                kb_id=str(kb.id), template_code=payload.template_code, error=str(e),
            )
            template_result = {"applied": False, "error": str(e)}

    # 5. 构造响应
    # 显式刷新 kb 对象，确保所有字段（含 updated_at 等 onupdate 字段）已加载，
    # 避免 kb_lifecycle / template_init 之后属性 expired 触发同步 lazy load
    await db.refresh(kb)
    kb_resp = KnowledgeBaseResponse.model_validate(kb).model_dump()
    kb_resp["my_role"] = ROLE_OWNER
    return success(
        data={
            "knowledge_base": kb_resp,
            "resources": resource_result,
            "template": template_result,
        },
        message="知识库创建成功",
    )


# ============================================================
# 知识库详情 / 更新 / 删除 / 启停
# ============================================================
@router.get("/{kb_id}", response_model_exclude_none=True)
async def get_knowledge_base(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取知识库详情（含成员数量）。"""
    # 成员数量
    count_stmt = select(func.count()).select_from(KbMember).where(KbMember.kb_id == kb_ctx.kb_id)
    member_count: int = (await db.execute(count_stmt)).scalar_one()

    resp = KnowledgeBaseResponse.model_validate(kb_ctx.kb).model_dump()
    resp["my_role"] = kb_ctx.role
    resp["member_count"] = member_count
    return success(data=resp)


@router.put("/{kb_id}", response_model_exclude_none=True)
async def update_knowledge_base(
    payload: KnowledgeBaseUpdate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新知识库基础信息（owner/admin）。

    config 不在此处更新，配置中心有独立端点。
    """
    kb = kb_ctx.kb
    if payload.name is not None:
        kb.name = payload.name
    if payload.description is not None:
        kb.description = payload.description
    if payload.sort_order is not None:
        kb.sort_order = payload.sort_order
    await db.commit()
    await db.refresh(kb)

    logger.info("知识库基础信息已更新", kb_id=str(kb.id), user_id=str(kb_ctx.user.id))
    resp = KnowledgeBaseResponse.model_validate(kb).model_dump()
    resp["my_role"] = kb_ctx.role
    return success(data=resp, message="更新成功")


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_ctx: KBContext = Depends(require_role(ROLE_OWNER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除知识库（仅 owner）。

    彻底销毁全部物理资源（合规销毁，不可恢复），然后删除 DB 记录。
    资源销毁失败不阻断 DB 记录删除（避免残留孤立 KB），但记录失败步骤。
    """
    kb_id = kb_ctx.kb_id
    kb_name = kb_ctx.kb.name

    # 1. 销毁物理资源
    from app.services.kb.kb_lifecycle import kb_lifecycle

    resource_result = await kb_lifecycle.destroy_kb_resources(kb_id)

    # 2. 显式清理引用 kb_id 但外键为 NO ACTION（不级联）的子表，
    #    否则 db.delete(kb) 会触发 ForeignKeyViolationError。
    #    物理资源（MinIO/Milvus 等）已在步骤 1 销毁，此处仅清 DB 记录。
    #    删除顺序遵循依赖关系：先删子表（引用 documents/terms 的表），再删父表。
    #    已知 NO ACTION 外键（7 表）：
    #      documents / tasks / kb_backups / qa_sessions / schema_configs /
    #      terms / term_mappings
    #    其中 tasks.document_id → documents、term_mappings.term_id → terms 亦为 NO ACTION。
    from sqlalchemy import text as _text

    # 按依赖顺序清理（子表优先）
    # 注意：qa_messages 无 kb_id 列，通过 qa_sessions 的 CASCADE 自动清理，不在此列出。
    _cleanup_order = [
        "tasks",            # 引用 documents(document_id) + knowledge_bases(kb_id)
        "term_mappings",    # 引用 terms(term_id) + knowledge_bases(kb_id)
        "terms",            # 引用 knowledge_bases(kb_id)
        "documents",        # 引用 knowledge_bases(kb_id)
        "kb_backups",       # 引用 knowledge_bases(kb_id)
        "qa_sessions",      # 引用 knowledge_bases(kb_id)，CASCADE 清理 qa_messages
        "schema_configs",   # 引用 knowledge_bases(kb_id)
    ]
    for tbl in _cleanup_order:
        # 用 savepoint 隔离每个表删除：某表不存在 kb_id 列或删除失败时，
        # 仅回滚该 savepoint，不影响外层事务及其他表清理。
        try:
            async with db.begin_nested():
                await db.execute(
                    _text(f"DELETE FROM {tbl} WHERE kb_id = :kb_id"),
                    {"kb_id": kb_id},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "清理 KB 关联表失败（继续）",
                table=tbl, kb_id=str(kb_id), error=str(exc),
            )
    await db.flush()

    # 3. 删除 KB 记录（kb_members / kb_categories 等已配置 CASCADE 的表自动级联）
    await db.delete(kb_ctx.kb)
    await db.commit()

    logger.warning(
        "知识库已删除（含物理资源销毁）",
        kb_id=str(kb_id), kb_name=kb_name, user_id=str(kb_ctx.user.id),
    )
    return success(
        data={"kb_id": str(kb_id), "resources": resource_result},
        message="知识库已删除，物理资源已销毁",
    )


@router.patch("/{kb_id}/active", response_model_exclude_none=True)
async def update_knowledge_base_active(
    payload: KnowledgeBaseActiveUpdate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """启用/停用知识库（owner/admin）。"""
    kb = kb_ctx.kb
    kb.is_active = payload.is_active
    await db.commit()
    await db.refresh(kb)

    logger.info(
        "知识库启停状态已变更",
        kb_id=str(kb.id), is_active=kb.is_active, user_id=str(kb_ctx.user.id),
    )
    resp = KnowledgeBaseResponse.model_validate(kb).model_dump()
    resp["my_role"] = kb_ctx.role
    return success(data=resp, message="状态已更新")


# ============================================================
# 知识库统计
# ============================================================
@router.get("/{kb_id}/stats")
async def get_knowledge_base_stats(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """知识库统计信息（文档数、chunks数、任务数、成员数）。"""
    from app.services.dashboard_service import get_kb_stats
    stats = await get_kb_stats(db, kb_ctx.kb_id)
    data = {
        "kb_id": str(kb_ctx.kb_id),
        "kb_name": kb_ctx.kb.name,
        **stats,
    }
    return success(data=data)


# ============================================================
# 成员管理（owner/admin）
# ============================================================
@router.get("/{kb_id}/members")
async def list_members(
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """成员列表（owner/admin）。"""
    stmt = (
        select(KbMember, User)
        .join(User, User.id == KbMember.user_id)
        .where(KbMember.kb_id == kb_ctx.kb_id)
        .order_by(KbMember.created_at)
    )
    result = await db.execute(stmt)
    items: list[dict] = []
    for member, user in result.all():
        item = KbMemberResponse.model_validate(member).model_dump()
        item["username"] = user.username
        item["email"] = user.email
        item["avatar"] = user.avatar
        items.append(item)
    return success(data={"items": items, "total": len(items)})


@router.post("/{kb_id}/members", status_code=201)
async def add_member(
    payload: KbMemberAdd,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """添加成员（owner/admin）。

    校验目标用户存在且未已是成员。
    """
    # 校验用户存在
    user_stmt = select(User).where(User.id == payload.user_id)
    user = (await db.execute(user_stmt)).scalar_one_or_none()
    if user is None:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"用户 {payload.user_id} 不存在",
        )

    # 校验未已是成员
    exist_stmt = select(KbMember.id).where(
        KbMember.kb_id == kb_ctx.kb_id, KbMember.user_id == payload.user_id
    )
    if (await db.execute(exist_stmt)).scalar_one_or_none() is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_KB_MEMBER_EXISTS,
            message=f"用户「{user.username}」已是该知识库成员",
        )

    member = KbMember(
        kb_id=kb_ctx.kb_id, user_id=payload.user_id, role=payload.role
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    logger.info(
        "成员已添加",
        kb_id=str(kb_ctx.kb_id), user_id=str(payload.user_id),
        role=payload.role, operator=str(kb_ctx.user.id),
    )
    item = KbMemberResponse.model_validate(member).model_dump()
    item["username"] = user.username
    item["email"] = user.email
    item["avatar"] = user.avatar
    return success(data=item, message="成员添加成功")


@router.put("/{kb_id}/members/{user_id}")
async def update_member_role(
    user_id: uuid.UUID,
    payload: KbMemberUpdate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """修改成员角色（owner/admin）。

    不可修改 owner 角色（owner 仅可通过转让变更，本端点不提供转让）。
    """
    stmt = select(KbMember).where(
        KbMember.kb_id == kb_ctx.kb_id, KbMember.user_id == user_id
    )
    member = (await db.execute(stmt)).scalar_one_or_none()
    if member is None:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message="该成员不存在"
        )
    if member.role == ROLE_OWNER:
        raise PermissionException(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            message="不可修改 owner 角色",
        )

    member.role = payload.role
    await db.commit()
    await db.refresh(member)

    logger.info(
        "成员角色已变更",
        kb_id=str(kb_ctx.kb_id), user_id=str(user_id),
        role=payload.role, operator=str(kb_ctx.user.id),
    )
    return success(data={"role": member.role}, message="角色已更新")


@router.delete("/{kb_id}/members/{user_id}")
async def remove_member(
    user_id: uuid.UUID,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """移除成员（owner/admin）。

    不可移除 owner。不可移除自己（避免 owner 误操作失去权限）。
    """
    if user_id == kb_ctx.user.id:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="不可移除自己，如需退出请转让 owner 后操作",
        )

    stmt = select(KbMember).where(
        KbMember.kb_id == kb_ctx.kb_id, KbMember.user_id == user_id
    )
    member = (await db.execute(stmt)).scalar_one_or_none()
    if member is None:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message="该成员不存在"
        )
    if member.role == ROLE_OWNER:
        raise PermissionException(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            message="不可移除 owner",
        )

    await db.delete(member)
    await db.commit()

    logger.info(
        "成员已移除",
        kb_id=str(kb_ctx.kb_id), user_id=str(user_id),
        operator=str(kb_ctx.user.id),
    )
    return success(message="成员已移除")
