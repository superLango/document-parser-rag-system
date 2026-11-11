from __future__ import annotations

import asyncio

import httpx
import pytest
from hanson_contracts import ModelMessage

from services.agent.model_gateway import (
    ModelEndpoint,
    ModelGateway,
    ModelGatewayConfig,
    ModelUnavailable,
    parse_json_value,
)


def _response(content: str, tokens: int = 10) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": tokens,
            "completion_tokens": 2,
            "total_tokens": tokens + 2,
        },
    }


def _config(failover_seconds: float = 0.0, cooldown: float = 30.0) -> ModelGatewayConfig:
    return ModelGatewayConfig(
        model="Qwen-35B",
        endpoints=(
            ModelEndpoint(name="primary", base_url="http://primary"),
            ModelEndpoint(name="secondary", base_url="http://secondary"),
            ModelEndpoint(name="tertiary", base_url="http://tertiary"),
        ),
        failover_seconds=failover_seconds,
        cooldown_seconds=cooldown,
    )


def test_parse_json_value_accepts_fences_and_prose() -> None:
    assert parse_json_value('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_value('result: {"a": 2} done') == {"a": 2}


def test_failover_to_secondary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary":
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json=_response('{"ok": true}'))

    async def scenario() -> None:
        gateway = ModelGateway(
            _config(failover_seconds=0),
            transport=httpx.MockTransport(handler),
        )
        try:
            response = await gateway.chat([ModelMessage(role="user", content="hi")])
            assert response.endpoint == "secondary"
            assert response.prompt_tokens == 10
            statuses = {item.name: item for item in gateway.status()}
            assert statuses["primary"].available is False
            assert statuses["secondary"].active is True
        finally:
            await gateway.close()

    asyncio.run(scenario())


def test_short_blip_does_not_switch_active() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary":
            raise httpx.ConnectError("blip", request=request)
        return httpx.Response(200, json=_response('{"ok": true}'))

    async def scenario() -> None:
        now = [0.0]
        gateway = ModelGateway(
            _config(failover_seconds=10),
            transport=httpx.MockTransport(handler),
            clock=lambda: now[0],
        )
        try:
            response = await gateway.chat([ModelMessage(role="user", content="hi")])
            assert response.endpoint == "secondary"
            assert gateway.active_endpoint.name == "primary"
        finally:
            await gateway.close()

    asyncio.run(scenario())


def test_ten_second_outage_commits_switch_and_recovers() -> None:
    primary_ok = [False]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary":
            if not primary_ok[0]:
                raise httpx.ConnectError("down", request=request)
            return httpx.Response(200, json=_response('{"from": "primary"}'))
        return httpx.Response(200, json=_response('{"from": "secondary"}'))

    async def scenario() -> None:
        now = [0.0]
        gateway = ModelGateway(
            _config(failover_seconds=10, cooldown=30),
            transport=httpx.MockTransport(handler),
            clock=lambda: now[0],
        )
        try:
            first = await gateway.chat([ModelMessage(role="user", content="hi")])
            assert first.endpoint == "secondary"
            assert gateway.active_endpoint.name == "primary"

            now[0] = 11.0
            second = await gateway.chat([ModelMessage(role="user", content="hi")])
            assert second.endpoint == "secondary"
            assert gateway.active_endpoint.name == "secondary"

            primary_ok[0] = True
            now[0] = 45.0
            third = await gateway.chat([ModelMessage(role="user", content="hi")])
            assert third.endpoint == "primary"
            assert gateway.active_endpoint.name == "primary"
        finally:
            await gateway.close()

    asyncio.run(scenario())


def test_json_repair_calls_model_twice() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(200, json=_response("not json"))
        return httpx.Response(200, json=_response('{"fixed": true}'))

    async def scenario() -> None:
        gateway = ModelGateway(_config(), transport=httpx.MockTransport(handler))
        try:
            value, response = await gateway.chat_json(
                [ModelMessage(role="user", content="return JSON")]
            )
            assert value == {"fixed": True}
            assert len(calls) == 2
            assert response.total_tokens == 24
        finally:
            await gateway.close()

    asyncio.run(scenario())


def test_probe_marks_model_mismatch_and_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "primary":
            return httpx.Response(200, json={"data": [{"id": "Qwen3.5-9B"}]})
        if host == "secondary":
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json={"data": [{"id": "Qwen-35B"}]})

    async def scenario() -> None:
        gateway = ModelGateway(
            _config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: 100.0,
        )
        try:
            entries = await gateway.probe()
            assert entries[0]["ok"] is False
            assert "not in" in entries[0]["error"]
            assert entries[1]["ok"] is False
            assert entries[2]["ok"] is True
            assert gateway.active_endpoint.name == "tertiary"
            statuses = {item.name: item for item in gateway.status()}
            assert statuses["primary"].available is False
            assert statuses["secondary"].available is False
            assert statuses["tertiary"].active is True
        finally:
            await gateway.close()

    asyncio.run(scenario())


def test_all_endpoints_down_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async def scenario() -> None:
        gateway = ModelGateway(_config(), transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ModelUnavailable):
                await gateway.chat([ModelMessage(role="user", content="hi")])
        finally:
            await gateway.close()

    asyncio.run(scenario())
