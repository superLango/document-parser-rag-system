"""一站式任务终态回调单元测试。"""

import json

import httpx
from app.core.config import settings
from app.services import integration_callback


async def test_failed_status_callback_payload(monkeypatch):
    """失败终态传 task_id/status/reason，并读取对端 result。"""
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"result": dict(seen)})

    monkeypatch.setattr(settings, "INTEGRATION_STATUS_CALLBACK_MAX_ATTEMPTS", 1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sent = await integration_callback.send_status_callback(
            "task-1", "failed", "OCR 服务不可用", client=client
        )

    assert sent is True
    assert seen == {
        "task_id": "task-1",
        "status": "failed",
        "reason": "OCR 服务不可用",
    }


async def test_success_status_callback_clears_reason(monkeypatch):
    """成功终态始终发送空 reason。"""
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"result": dict(seen)})

    monkeypatch.setattr(settings, "INTEGRATION_STATUS_CALLBACK_MAX_ATTEMPTS", 1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sent = await integration_callback.send_status_callback(
            "task-2", "success", "该内容不会发送", client=client
        )

    assert sent is True
    assert seen["status"] == "success"
    assert seen["reason"] == ""


async def test_status_callback_failure_retries_without_raising(monkeypatch):
    """回调失败有限重试，最终不影响业务调用方。"""
    attempts: list[int] = []

    async def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(500, text="boom")

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(settings, "INTEGRATION_STATUS_CALLBACK_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(integration_callback.asyncio, "sleep", fake_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sent = await integration_callback.send_status_callback(
            "task-3", "failed", "索引失败", client=client
        )

    assert sent is False
    assert len(attempts) == 2
