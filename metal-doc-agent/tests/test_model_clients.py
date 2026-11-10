"""Tests for the model service clients using an in-process fake server."""

from __future__ import annotations

import io
import json
import unittest

import httpx
from PIL import Image

from metal_doc_agent.clients import GlmOcrClient, LayoutClient, QwenClient


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_1X1 = png_bytes()


class FakeModelService:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.payloads: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            self.payloads.append(payload)
            if payload.get("stream"):
                chunk = json.dumps({"choices": [{"delta": {"content": "ok"}}]})
                usage = json.dumps(
                    {
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "total_tokens": 15,
                        }
                    }
                )
                body = f"data: {chunk}\n\ndata: {usage}\n\ndata: [DONE]\n\n"
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=body.encode(),
                )
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                },
            )
        if path.endswith("/v1/layout"):
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "blocks": [
                        {
                            "type": "table",
                            "bbox": [0.1, 0.2, 0.3, 0.4],
                            "order": 1,
                            "confidence": 0.9,
                            "structural": {"engine": "ppdoclayoutv3"},
                        }
                    ],
                },
            )
        if path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok", "model_loaded": True})
        return httpx.Response(404, json={"error": "not found"})


class ModelClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeModelService()
        self.http = httpx.Client(
            transport=httpx.MockTransport(self.service), trust_env=False
        )

    def tearDown(self) -> None:
        self.http.close()

    def test_qwen_health_and_json_mode(self) -> None:
        client = QwenClient(
            "http://test/v1", "Qwen3.5-9B", client=self.http
        )
        self.assertEqual(client.health(), ["test-model"])
        content = client.chat(
            [{"role": "user", "content": "extract"}], json_mode=True
        )
        self.assertEqual(content, "ok")
        payload = self.service.payloads[-1]
        self.assertEqual(payload["model"], "Qwen3.5-9B")
        self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_usage_accumulates_per_client(self) -> None:
        client = QwenClient("http://test/v1", "Qwen3.5-9B", client=self.http)
        client.chat([{"role": "user", "content": "a"}])
        client.chat([{"role": "user", "content": "b"}])
        self.assertEqual(
            client.usage,
            {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        )
        self.assertEqual(client.calls, 2)
        self.assertEqual(client.last_usage["total_tokens"], 15)

    def test_glm_image_payload(self) -> None:
        client = GlmOcrClient(
            "http://test/v1", "GLM-OCR", max_edge=2048, stream=False, client=self.http
        )
        text = client.ocr_image(PNG_1X1, "table")
        self.assertEqual(text, "ok")
        payload = self.service.payloads[-1]
        content = payload["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image_url")
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertIn("<table>", content[1]["text"])

    def test_glm_streams_chunks_and_usage(self) -> None:
        client = GlmOcrClient(
            "http://test/v1", "GLM-OCR", max_edge=2048, client=self.http
        )
        text = client.ocr_image(PNG_1X1, "table")
        self.assertEqual(text, "ok")
        self.assertTrue(self.service.payloads[-1]["stream"])
        self.assertEqual(
            client.usage,
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    def test_layout_analyze(self) -> None:
        client = LayoutClient("http://test", client=self.http)
        self.assertTrue(client.health()["model_loaded"])
        blocks = client.analyze(PNG_1X1, page_index=5)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].type, "table")
        self.assertEqual(blocks[0].bbox, (0.1, 0.2, 0.3, 0.4))
        self.assertEqual(blocks[0].order, 1)

    def test_layout_falls_back_to_secondary(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "primary":
                return httpx.Response(503, json={"detail": "layout down"})
            if request.url.path.endswith("/v1/layout"):
                return httpx.Response(
                    200,
                    json={
                        "blocks": [
                            {
                                "type": "table",
                                "bbox": [0.1, 0.2, 0.3, 0.4],
                                "order": 1,
                                "confidence": 0.9,
                            }
                        ]
                    },
                )
            return httpx.Response(404, json={"detail": "not found"})

        http = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        try:
            client = LayoutClient(
                "http://primary",
                fallback_url="http://fallback",
                retries=0,
                client=http,
            )
            blocks = client.analyze(PNG_1X1, page_index=2)
        finally:
            http.close()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].type, "table")

    def test_api_base_normalization(self) -> None:
        client = QwenClient("http://test", "Qwen3.5-9B", client=self.http)
        self.assertEqual(client.base_url, "http://test/v1")

    def test_failover_endpoints_switch_and_recover(self) -> None:
        from metal_doc_agent.clients.base import FailoverEndpoints

        endpoints = FailoverEndpoints(
            "http://failover-a/v1",
            "http://failover-b/v1",
            probe_interval=60.0,
        )
        self.assertEqual(
            endpoints.ordered(),
            ["http://failover-a/v1", "http://failover-b/v1"],
        )
        endpoints.record_failure("http://failover-a/v1")
        self.assertEqual(endpoints.active, "http://failover-b/v1")
        self.assertEqual(
            endpoints.ordered(),
            ["http://failover-b/v1", "http://failover-a/v1"],
        )
        endpoints.record_success("http://failover-b/v1")
        self.assertEqual(
            endpoints.ordered(),
            ["http://failover-b/v1", "http://failover-a/v1"],
        )
        endpoints.record_success("http://failover-a/v1")
        self.assertEqual(
            endpoints.ordered(),
            ["http://failover-a/v1", "http://failover-b/v1"],
        )

    def test_qwen_fails_over_and_stays_on_fallback(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.host)
            if request.url.host == "qwen-primary-failover":
                return httpx.Response(503, json={"detail": "down"})
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}
            )

        http = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        try:
            client = QwenClient(
                "http://qwen-primary-failover/v1",
                "test",
                fallback_base_url="http://qwen-fallback-failover/v1",
                failover_probe_seconds=60,
                retries=0,
                stream=False,
                client=http,
            )
            self.assertEqual(client.chat([{"role": "user", "content": "a"}]), "ok")
            self.assertEqual(calls, ["qwen-primary-failover", "qwen-fallback-failover"])
            self.assertEqual(client.base_url, "http://qwen-fallback-failover/v1")

            calls.clear()
            self.assertEqual(client.chat([{"role": "user", "content": "b"}]), "ok")
            self.assertEqual(calls, ["qwen-fallback-failover"])
        finally:
            http.close()

    def test_qwen_recovers_primary_when_probe_interval_passes(self) -> None:
        primary_up = {"value": False}
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.host)
            if request.url.host == "qwen-probe-primary":
                if not primary_up["value"]:
                    return httpx.Response(503, json={"detail": "down"})
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": "primary"}}]}
                )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "fallback"}}]}
            )

        http = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        try:
            client = QwenClient(
                "http://qwen-probe-primary/v1",
                "test",
                fallback_base_url="http://qwen-probe-fallback/v1",
                failover_probe_seconds=0,
                retries=0,
                stream=False,
                client=http,
            )
            self.assertEqual(client.chat([{"role": "user", "content": "a"}]), "fallback")
            primary_up["value"] = True
            self.assertEqual(client.chat([{"role": "user", "content": "b"}]), "primary")
            self.assertEqual(client.base_url, "http://qwen-probe-primary/v1")
        finally:
            http.close()

    def test_streaming_client_fails_over(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "glm-primary-failover":
                return httpx.Response(503, json={"detail": "down"})
            body = (
                "data: "
                + json.dumps({"choices": [{"delta": {"content": "ok"}}]})
                + "\n\ndata: [DONE]\n\n"
            )
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=body.encode(),
            )

        http = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        try:
            client = GlmOcrClient(
                "http://glm-primary-failover/v1",
                "GLM-OCR",
                fallback_base_url="http://glm-fallback-failover/v1",
                failover_probe_seconds=60,
                retries=0,
                client=http,
            )
            self.assertEqual(client.ocr_image(PNG_1X1, "text"), "ok")
            self.assertEqual(client.base_url, "http://glm-fallback-failover/v1")
        finally:
            http.close()

    def test_layout_stays_on_fallback_within_probe_interval(self) -> None:
        primary_calls = {"value": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "layout-primary-failover":
                primary_calls["value"] += 1
                return httpx.Response(503, json={"detail": "down"})
            return httpx.Response(
                200,
                json={
                    "blocks": [
                        {
                            "type": "table",
                            "bbox": [0.1, 0.2, 0.3, 0.4],
                            "order": 1,
                            "confidence": 0.9,
                        }
                    ]
                },
            )

        http = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        try:
            client = LayoutClient(
                "http://layout-primary-failover",
                fallback_url="http://layout-fallback-failover",
                failover_probe_seconds=60,
                retries=0,
                client=http,
            )
            client.analyze(PNG_1X1, page_index=1)
            client.analyze(PNG_1X1, page_index=2)
        finally:
            http.close()
        self.assertEqual(primary_calls["value"], 1)

    def test_non_temporary_http_error_does_not_fail_over(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.host)
            return httpx.Response(404, json={"detail": "model not found"})

        http = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        try:
            from metal_doc_agent.clients import ModelServiceError

            client = QwenClient(
                "http://qwen-404-primary/v1",
                "test",
                fallback_base_url="http://qwen-404-fallback/v1",
                retries=0,
                stream=False,
                client=http,
            )
            with self.assertRaises(ModelServiceError):
                client.chat([{"role": "user", "content": "a"}])
        finally:
            http.close()
        self.assertEqual(calls, ["qwen-404-primary"])


class SettingsFailoverTests(unittest.TestCase):
    def test_settings_parse_failover_endpoints(self) -> None:
        import os
        from unittest.mock import patch

        from metal_doc_agent.settings import Settings

        with patch.dict(
            os.environ,
            {
                "GLM_OCR_BASE_URL": "http://public:35032/v1",
                "GLM_OCR_FALLBACK_BASE_URL": "http://lan:9977/v1",
                "QWEN_FALLBACK_BASE_URL": "http://lan:9991/v1",
                "SFT_FALLBACK_BASE_URL": "http://lan:9991/v1",
                "LAYOUT_SERVICE_FALLBACK_URLS": "http://a:1, http://b:2 ",
                "MODEL_FAILOVER_PROBE_SECONDS": "15",
            },
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.glm_ocr_fallback_base_url, "http://lan:9977/v1")
        self.assertEqual(settings.qwen_fallback_base_url, "http://lan:9991/v1")
        self.assertEqual(settings.sft_fallback_base_url, "http://lan:9991/v1")
        self.assertEqual(
            settings.layout_service_fallback_urls,
            ("http://a:1", "http://b:2"),
        )
        self.assertEqual(settings.model_failover_probe_seconds, 15.0)


if __name__ == "__main__":
    unittest.main()
