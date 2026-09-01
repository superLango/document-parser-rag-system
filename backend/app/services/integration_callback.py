"""一站式任务终态回调客户端。"""

from __future__ import annotations

import asyncio
import uuid

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
_ALLOWED_STATUSES = frozenset({STATUS_SUCCESS, STATUS_FAILED})


async def send_status_callback(
    task_id: uuid.UUID | str,
    status: str,
    reason: str = "",
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """发送一站式任务终态；失败只记录日志，不反向改变业务任务状态。"""
    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"不支持的一站式任务回调状态：{status}")

    url = settings.INTEGRATION_STATUS_CALLBACK_URL.strip()
    if not url:
        logger.warning("一站式任务状态回调地址为空，跳过回调", task_id=str(task_id))
        return False

    payload = {
        "task_id": str(task_id),
        "status": status,
        "reason": reason[:500] if status == STATUS_FAILED else "",
    }
    attempts = max(1, settings.INTEGRATION_STATUS_CALLBACK_MAX_ATTEMPTS)
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        timeout=settings.INTEGRATION_STATUS_CALLBACK_TIMEOUT_SECONDS
    )
    try:
        for attempt in range(1, attempts + 1):
            try:
                response = await http_client.post(url, json=payload)
                response.raise_for_status()
                try:
                    response_data = response.json()
                except ValueError:
                    response_data = None
                logger.info(
                    "一站式任务状态回调成功",
                    task_id=str(task_id),
                    status=status,
                    attempt=attempt,
                    result=(response_data or {}).get("result")
                    if isinstance(response_data, dict)
                    else None,
                )
                return True
            except httpx.HTTPError as exc:
                logger.warning(
                    "一站式任务状态回调失败",
                    task_id=str(task_id),
                    status=status,
                    attempt=attempt,
                    error=str(exc)[:500],
                )
                if attempt < attempts:
                    await asyncio.sleep(min(2 ** (attempt - 1), 5))
        return False
    finally:
        if owns_client:
            await http_client.aclose()
