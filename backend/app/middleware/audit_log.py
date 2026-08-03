"""审计日志中间件（阶段 1.1）。

采用 **装饰器标记 + 异步落库** 模式，仅对标记了 ``@audit_action`` 的端点
记录审计日志，避免对全量请求产生噪音。

设计要点：
1. **装饰器标记**：``@audit_action(action="user.create", resource_type="user")``
   将审计元数据挂载到端点函数的 ``__audit__`` 属性，运行时由包装函数读取。
2. **自动提取上下文**：从端点的依赖注入参数中识别 ``current_user`` / ``kb_ctx``，
   提取操作者、KB、资源 ID（路径参数）。
3. **脱敏**：请求体中的 password / old_password / new_password / token 字段
   在落库前替换为 ``"***"``。
4. **异步落库**：通过 ``asyncio.create_task`` 在独立任务中写入 ``audit_logs`` 表，
   不阻塞主请求；失败仅记录 WARNING，不影响业务响应。
5. **状态码捕获**：包装函数捕获业务异常的 ``http_status`` 与 ``code``，
   即使操作失败也记录审计日志（便于追溯越权/失败尝试）。

使用方式：
    from app.middleware.audit_log import audit_action

    @router.post("/users")
    @audit_action(action="user.create", resource_type="user")
    async def create_user(body: UserCreateRequest, current_user=Depends(...)): ...
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import uuid
from typing import Any, Callable

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.response import get_current_trace_id

logger = get_logger(__name__)

#: 请求体中需要脱敏的字段名（小写匹配）
_SENSITIVE_FIELDS = frozenset({
    "password", "new_password", "old_password", "token",
    "access_token", "secret", "secret_key", "hashed_password",
})


def _sanitize_payload(payload: Any) -> Any:
    """递归脱敏请求体中的敏感字段。

    Args:
        payload: 请求体（dict / list / 其他）。

    Returns:
        脱敏后的深拷贝（不修改原对象）。
    """
    if isinstance(payload, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_FIELDS else _sanitize_payload(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    return payload


def _extract_context(
    kwargs: dict[str, Any],
    path_params: dict[str, Any],
) -> tuple[uuid.UUID | None, str | None, uuid.UUID | None, str | None]:
    """从端点参数中提取审计上下文。

    识别规则：
    - 操作者：名为 ``current_user`` 的参数（User 对象），或 ``kb_ctx`` 上的 ``.user``
    - 知识库：名为 ``kb_ctx`` 的参数（KBContext），取 ``.kb_id``
    - 资源 ID：路径参数中的 ``user_id`` / ``kb_id`` / ``doc_id`` / ``document_id``
      / ``schema_id`` / ``term_id`` / ``task_id``

    Returns:
        (user_id, username, kb_id, resource_id)
    """
    user_id: uuid.UUID | None = None
    username: str | None = None
    kb_id: uuid.UUID | None = None

    kb_ctx = kwargs.get("kb_ctx")
    if kb_ctx is not None:
        kb_id = getattr(kb_ctx, "kb_id", None)
        user = getattr(kb_ctx, "user", None)
        if user is not None:
            user_id = getattr(user, "id", None)
            username = getattr(user, "username", None)

    current_user = kwargs.get("current_user")
    if current_user is not None and user_id is None:
        user_id = getattr(current_user, "id", None)
        username = getattr(current_user, "username", None)

    # 资源 ID：优先级从高到低匹配路径参数
    resource_id: str | None = None
    for key in (
        "user_id", "kb_id", "document_id", "doc_id",
        "schema_id", "term_id", "task_id", "category_id",
    ):
        val = path_params.get(key) or kwargs.get(key)
        if val is not None:
            resource_id = str(val)
            break

    return user_id, username, kb_id, resource_id


async def _write_audit_log(
    *,
    user_id: uuid.UUID | None,
    username: str | None,
    kb_id: uuid.UUID | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    method: str | None,
    path: str | None,
    status_code: int | None,
    ip: str | None,
    user_agent: str | None,
    details: dict | None,
    trace_id: str | None,
) -> None:
    """异步写入审计日志，失败仅记录 WARNING。

    使用独立数据库会话，避免与请求事务耦合（即使请求回滚，审计仍留存）。
    写入后检测是否为异常操作，若异常则向所有超管发送通知（C4 异常告警）。
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.audit_log import AuditLog

        async with AsyncSessionLocal() as db:
            log = AuditLog(
                user_id=user_id,
                username=username,
                kb_id=kb_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                method=method,
                path=path,
                status_code=status_code,
                ip=ip,
                user_agent=user_agent,
                details=details,
                trace_id=trace_id,
            )
            db.add(log)
            await db.commit()

        # C4 异常操作告警：检测异常并通知超管
        alert = _detect_anomaly(action, status_code, details, username, ip)
        if alert is not None:
            await _alert_superadmins(db_session_factory=AsyncSessionLocal, **alert)
    except Exception as exc:  # noqa: BLE001
        logger.warning("审计日志写入失败", action=action, error=str(exc))


def _detect_anomaly(
    action: str,
    status_code: int | None,
    details: dict | None,
    username: str | None,
    ip: str | None,
) -> dict | None:
    """检测异常操作，返回告警信息字典（无需告警则返回 None）。

    告警规则（C4 异常操作告警）：
    1. 账户锁定：auth.login 且 status_code==400 且 details 含"锁定" → audit_alert（高优先级）
    2. 权限拒绝：status_code==403 → audit_alert（中优先级）
    3. 服务器错误：status_code>=500 → audit_alert（高优先级）
    4. 批量删除：action 含 "batch.delete" 且成功 → audit_alert（信息级）

    Args:
        action: 业务动作标识。
        status_code: HTTP 状态码。
        details: 审计详情（可能含 error 字段）。
        username: 操作者用户名。
        ip: 客户端 IP。

    Returns:
        dict | None: 告警信息（title/content/level），无需告警返回 None。
    """
    if status_code is None:
        return None

    error_msg = (details or {}).get("error", "") if details else ""

    # 规则 1：账户锁定（连续登录失败触发）
    if action == "auth.login" and status_code == 400 and "锁定" in error_msg:
        return {
            "title": f"账户安全告警：{username or '未知用户'} 账户被锁定",
            "content": f"连续登录失败触发账户锁定。IP: {ip or '未知'}，详情: {error_msg[:200]}",
        }

    # 规则 2：权限拒绝
    if status_code == 403:
        return {
            "title": f"权限拒绝告警：{username or '匿名'} 访问被拒（{action}）",
            "content": f"操作 {action} 被权限策略拒绝。IP: {ip or '未知'}",
        }

    # 规则 3：服务器错误
    if status_code >= 500:
        return {
            "title": f"服务器错误告警：{action} 返回 {status_code}",
            "content": f"操作者: {username or '匿名'}，IP: {ip or '未知'}，错误: {error_msg[:200]}",
        }

    # 规则 4：批量删除（成功的批量删除操作记录告警）
    if "batch.delete" in action and status_code == 200:
        return {
            "title": f"批量删除操作：{username or '匿名'} 执行了 {action}",
            "content": f"批量删除操作已完成。IP: {ip or '未知'}",
        }

    return None


async def _alert_superadmins(
    *,
    db_session_factory,
    title: str,
    content: str,
) -> None:
    """向所有超级管理员发送异常告警通知。

    查询所有 is_superuser=True 且未软删除的用户，为每人创建一条
    type=audit_alert 的通知。失败仅记录 WARNING，不影响主流程。

    Args:
        db_session_factory: AsyncSessionLocal 工厂。
        title: 告警标题。
        content: 告警内容。
    """
    try:
        from app.models.user import User
        from app.services.notification_service import create_notification

        async with db_session_factory() as db:
            result = await db.execute(
                select(User.id).where(
                    User.is_superuser.is_(True),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                )
            )
            superadmin_ids = [row[0] for row in result.all()]

            for admin_id in superadmin_ids:
                await create_notification(
                    db,
                    user_id=admin_id,
                    type="audit_alert",
                    title=title[:255],
                    content=content,
                    resource_type="audit",
                )
            await db.commit()

        logger.info("异常告警已发送", title=title, superadmin_count=len(superadmin_ids))
    except Exception as exc:  # noqa: BLE001
        logger.warning("异常告警发送失败", title=title, error=str(exc))


def audit_action(
    action: str,
    resource_type: str | None = None,
    *,
    capture_body: bool = True,
) -> Callable[[Callable], Callable]:
    """装饰器：标记端点需要审计，并包装以记录审计日志。

    Args:
        action: 业务动作标识（如 ``user.create`` / ``kb.delete``）。
        resource_type: 资源类型（user/kb/document/config/term/schema/...）。
        capture_body: 是否捕获请求体（已脱敏），默认 True。对大体积或敏感
            端点可设为 False。

    Returns:
        包装后的端点函数。
    """

    def decorator(func: Callable) -> Callable:
        # 挂载审计元数据，便于静态分析与路由扫描
        setattr(func, "__audit__", {"action": action, "resource_type": resource_type})

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 提取 Request 对象（FastAPI 注入名为 request 或通过签名查找）
            request: Any = kwargs.get("request")
            path_params: dict[str, Any] = {}
            if request is not None:
                path_params = dict(getattr(request, "path_params", {}) or {})

            user_id, username, kb_id, resource_id = _extract_context(kwargs, path_params)

            # 捕获请求体（脱敏）
            details: dict | None = None
            if capture_body:
                body_candidates = [
                    kwargs.get("body"), kwargs.get("payload"),
                    kwargs.get("data"), kwargs.get("schema"),
                ]
                for cand in body_candidates:
                    if cand is not None and hasattr(cand, "model_dump"):
                        details = {"body": _sanitize_payload(cand.model_dump())}
                        break
                    if isinstance(cand, dict):
                        details = {"body": _sanitize_payload(cand)}
                        break

            method = getattr(request, "method", None) if request else None
            path = str(getattr(request, "url", None)) if request else None
            ip = (
                getattr(request, "client", None).host
                if request and getattr(request, "client", None)
                else None
            )
            user_agent = request.headers.get("user-agent") if request else None
            trace_id = get_current_trace_id()

            status_code = 200
            try:
                result = await func(*args, **kwargs)
                # 从返回的统一响应体中无法直接拿到 HTTP 状态码，默认 200；
                # 异常路径由 except 分支捕获真实状态码。
                return result
            except Exception as exc:
                # 捕获业务异常的状态码
                http_status = getattr(exc, "http_status", 500)
                status_code = http_status
                details = details or {}
                details["error"] = str(exc)[:500]
                raise
            finally:
                asyncio.create_task(
                    _write_audit_log(
                        user_id=user_id,
                        username=username,
                        kb_id=kb_id,
                        action=action,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        method=method,
                        path=path,
                        status_code=status_code,
                        ip=ip,
                        user_agent=user_agent,
                        details=details,
                        trace_id=trace_id,
                    )
                )

        # 保留审计元数据到包装函数（functools.wraps 已复制 __dict__，此处显式确保）
        setattr(wrapper, "__audit__", {"action": action, "resource_type": resource_type})
        return wrapper

    return decorator
