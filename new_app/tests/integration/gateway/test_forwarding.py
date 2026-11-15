from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient


def _client_with_capture(seen: list[tuple[str, str, dict, bytes]]):
    import services.api_gateway.main as gateway

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.method,
                request.url.path,
                dict(request.url.params),
                request.content,
            )
        )
        if request.url.path == "/internal/documents" and request.method == "POST":
            return httpx.Response(201, json={"id": "doc-1", "filename": "a.txt"})
        if request.url.path.endswith("/reparse"):
            return httpx.Response(202, json={"id": "run-2", "status": "RECEIVED"})
        return httpx.Response(200, json={"items": []})

    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    gateway.httpx.AsyncClient = factory  # type: ignore[assignment]
    return TestClient(gateway.app), original


def test_upload_and_list_are_forwarded() -> None:
    import services.api_gateway.main as gateway

    seen: list[tuple[str, str, dict, bytes]] = []
    client, original = _client_with_capture(seen)
    try:
        upload = client.post(
            "/v1/documents",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        assert upload.status_code == 201
        assert upload.json()["id"] == "doc-1"

        listing = client.get("/v1/documents")
        assert listing.status_code == 200
        assert listing.json() == {"items": []}
    finally:
        gateway.httpx.AsyncClient = original  # type: ignore[assignment]

    assert seen[0][:2] == ("POST", "/internal/documents")
    assert seen[1][:2] == ("GET", "/internal/documents")


def test_reparse_body_is_passed_through() -> None:
    import services.api_gateway.main as gateway

    seen: list[tuple[str, str, dict, bytes]] = []
    client, original = _client_with_capture(seen)
    try:
        response = client.post(
            "/v1/runs/run-1/reparse", json={"parser_version": "1.0.14"}
        )
        assert response.status_code == 202
    finally:
        gateway.httpx.AsyncClient = original  # type: ignore[assignment]

    method, path, _, body = seen[-1]
    assert (method, path) == ("POST", "/internal/runs/run-1/reparse")
    assert json.loads(body) == {"parser_version": "1.0.14", "reuse_ocr": False}


def test_orchestration_outage_returns_502() -> None:
    import services.api_gateway.main as gateway

    original = httpx.AsyncClient

    def failing(*args, **kwargs):
        raise httpx.ConnectError("boom")

    gateway.httpx.AsyncClient = failing  # type: ignore[assignment]
    try:
        client = TestClient(gateway.app)
        response = client.get("/v1/documents")
        assert response.status_code == 502
    finally:
        gateway.httpx.AsyncClient = original  # type: ignore[assignment]
