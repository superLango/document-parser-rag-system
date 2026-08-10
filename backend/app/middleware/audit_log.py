"""审计日志装饰器：标记端点并异步落库。"""

import asyncio
import functools
import uuid
from typing import Any, Callable

from app.core.logging import get_logger
from app.core.response import get_current_trace_id
from app.services.audit_service import write_audit_log

logger = get_logger(__name__)

_SENSITIVE_FIELDS = frozenset({
    "password", "new_password", "old_password", "token",
    "access_token", "secret", "secret_key", "hashed_password",
})


def _sanitize_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_FIELDS else _sanitize_payload(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    return payload


def _extract_context(
    kwargs: dict[str, Any], path_params: dict[str, Any]
) -> tuple[uuid.UUID | None, str | None, uuid.UUID | None, str | None]:
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


def audit_action(
    action: str,
    resource_type: str | None = None,
    *,
    capture_body: bool = True,
) -> Callable[[Callable], Callable]:
    def decorator(func: Callable) -> Callable:
        setattr(func, "__audit__", {"action": action, "resource_type": resource_type})

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Any = kwargs.get("request")
            path_params: dict[str, Any] = {}
            if request is not None:
                path_params = dict(getattr(request, "path_params", {}) or {})

            user_id, username, kb_id, resource_id = _extract_context(kwargs, path_params)

            details: dict | None = None
            if capture_body:
                for cand in (
                    kwargs.get("body"),
                    kwargs.get("payload"),
                    kwargs.get("data"),
                    kwargs.get("schema"),
                ):
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
                return await func(*args, **kwargs)
            except Exception as exc:
                status_code = getattr(exc, "http_status", 500)
                details = details or {}
                details["error"] = str(exc)[:500]
                raise
            finally:
                asyncio.create_task(
                    write_audit_log(
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

        setattr(wrapper, "__audit__", {"action": action, "resource_type": resource_type})
        return wrapper

    return decorator
