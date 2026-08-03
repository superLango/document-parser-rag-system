"""用户管理端点模块（阶段 1.1）。

提供超管维度的用户管理接口（前缀 ``/users``）：

- GET    /users                分页查询用户列表（超管）
- POST   /users                创建用户（超管）
- GET    /users/{user_id}      用户详情（超管）
- PUT    /users/{user_id}      更新用户（超管）
- PATCH  /users/{user_id}/active 启用/禁用用户（超管）
- PATCH  /users/{user_id}/superuser 设置/取消超管（超管）
- POST   /users/{user_id}/reset-password 重置密码（超管生成令牌）
- DELETE /users/{user_id}      软删除用户（超管）

所有端点要求超管权限（``is_superuser=True``），由 ``require_superuser`` 守卫。
关键操作通过 ``@audit_action`` 记录审计日志。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_pagination_params, require_superuser
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.password_policy import validate_password
from app.core.response import paginated, success
from app.core.security import hash_password
from app.middleware.audit_log import audit_action
from app.models.password_reset import PasswordHistory, PasswordResetToken
from app.models.user import User
from app.schemas.user import (
    PasswordResetRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["用户管理"])


# ============================================================
# 超管守卫（require_superuser 已移至 app.api.deps 共享，避免循环导入）
# ============================================================


def _serialize_user(u: User) -> dict:
    """序列化 User ORM 对象为响应字典。"""
    return UserResponse.model_validate(u).model_dump()


# ============================================================
# 用户 CRUD
# ============================================================
@router.get("")
async def list_users(
    keyword: str | None = Query(None, description="按用户名/邮箱/姓名模糊搜索"),
    is_active: bool | None = Query(None, description="按启用状态过滤"),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """分页查询用户列表（超管）。

    支持按用户名/邮箱/姓名模糊搜索与启用状态过滤。软删除用户不返回。
    """
    page = pagination["page"]
    page_size = pagination["page_size"]

    base = select(User).where(User.deleted_at.is_(None))
    count_base = select(User).where(User.deleted_at.is_(None))

    if keyword:
        like = f"%{keyword}%"
        cond = or_(
            User.username.ilike(like),
            User.email.ilike(like),
            User.full_name.ilike(like),
        )
        base = base.where(cond)
        count_base = count_base.where(cond)
    if is_active is not None:
        base = base.where(User.is_active == is_active)
        count_base = count_base.where(User.is_active == is_active)

    from sqlalchemy import func

    total = (await db.execute(select(func.count()).select_from(count_base.subquery()))).scalar_one()
    users = (
        await db.execute(
            base.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return paginated([_serialize_user(u) for u in users], total, page, page_size)


@router.post("")
@audit_action(action="user.create", resource_type="user")
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """创建用户（超管）。

    校验用户名/邮箱唯一性、密码强度，记录密码历史。
    """
    # 唯一性校验
    exists = await db.execute(
        select(User).where(
            or_(User.username == body.username, User.email == body.email),
            User.deleted_at.is_(None),
        )
    )
    if exists.scalar_one_or_none() is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_EXISTS,
            message=f"用户名或邮箱已存在：{body.username}",
        )

    # 密码强度校验（新用户无历史）
    validate_password(body.password, hashed_history=[])

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        is_active=True,
        is_superuser=body.is_superuser,
        full_name=body.full_name,
        phone=body.phone,
        department=body.department,
        password_changed_at=None,
    )
    db.add(user)
    await db.flush()

    # 记录密码历史
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))
    await db.commit()
    await db.refresh(user)

    logger.info("用户已创建", user_id=str(user.id), operator=str(current_user.id))
    return success(data=_serialize_user(user))


@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """获取用户详情（超管）。"""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND,
            message=f"用户 {user_id} 不存在",
        )
    return success(data=_serialize_user(user))


@router.put("/{user_id}")
@audit_action(action="user.update", resource_type="user")
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """更新用户信息（超管）。所有字段可选。"""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND,
            message=f"用户 {user_id} 不存在",
        )

    if body.email is not None:
        user.email = body.email
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.phone is not None:
        user.phone = body.phone
    if body.department is not None:
        user.department = body.department
    if body.notes is not None:
        user.notes = body.notes
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_superuser is not None:
        # 防止超管取消自身超管权限导致无超管
        if user.id == current_user.id and not body.is_superuser:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="不能取消自身的超级管理员权限",
            )
        user.is_superuser = body.is_superuser

    await db.commit()
    await db.refresh(user)
    return success(data=_serialize_user(user))


@router.patch("/{user_id}/active")
@audit_action(action="user.toggle_active", resource_type="user")
async def toggle_active(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """启用/禁用用户（超管）。请求体 ``{"is_active": bool}``。"""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND,
            message=f"用户 {user_id} 不存在",
        )
    if user.id == current_user.id:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="不能禁用当前登录账户",
        )

    import json

    body = await request.json()
    user.is_active = bool(body.get("is_active", True))
    await db.commit()
    await db.refresh(user)
    return success(data={"id": str(user.id), "is_active": user.is_active})


@router.patch("/{user_id}/superuser")
@audit_action(action="user.toggle_superuser", resource_type="user")
async def toggle_superuser(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """设置/取消超管（超管）。请求体 ``{"is_superuser": bool}``。"""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND,
            message=f"用户 {user_id} 不存在",
        )
    if user.id == current_user.id:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="不能修改自身的超级管理员权限",
        )

    import json

    body = await request.json()
    user.is_superuser = bool(body.get("is_superuser", False))
    await db.commit()
    await db.refresh(user)
    return success(data={"id": str(user.id), "is_superuser": user.is_superuser})


@router.post("/{user_id}/reset-password")
@audit_action(action="user.reset_password", resource_type="user")
async def admin_reset_password(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """超管重置用户密码。

    请求体可选 ``{"new_password": "..."}``，未提供时由超管线下告知。
    重置后记录密码历史并清除失败计数与锁定。
    """
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND,
            message=f"用户 {user_id} 不存在",
        )

    import json

    body = await request.json()
    new_password = body.get("new_password")
    if not new_password:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="必须提供 new_password",
        )

    # 密码强度 + 历史校验
    from sqlalchemy import select as _select

    hist_rows = await db.execute(
        _select(PasswordHistory.hashed_password)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(5)
    )
    history = [r[0] for r in hist_rows.all()]
    validate_password(new_password, hashed_history=history, current_hashed=user.hashed_password)

    user.hashed_password = hash_password(new_password)
    from datetime import datetime, timezone

    user.password_changed_at = datetime.now(timezone.utc)
    user.failed_login_count = 0
    user.locked_until = None

    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))
    # 清理旧历史，仅保留最近 N 条
    from app.core.config import settings

    keep = settings.PASSWORD_HISTORY_SIZE
    all_hist = await db.execute(
        _select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
    )
    all_rows = all_hist.scalars().all()
    for old in all_rows[keep:]:
        await db.delete(old)

    await db.commit()
    return success(message="密码已重置")


@router.delete("/{user_id}")
@audit_action(action="user.delete", resource_type="user")
async def delete_user(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """软删除用户（超管）。

    设置 ``deleted_at``，不物理删除以保留审计可追溯性。
    禁止删除自身账户。
    """
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND,
            message=f"用户 {user_id} 不存在",
        )
    if user.id == current_user.id:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="不能删除当前登录账户",
        )

    from datetime import datetime, timezone

    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False
    await db.commit()
    return success(message="用户已删除")
