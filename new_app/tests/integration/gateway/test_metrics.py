"""P2-05/P2-06: /metrics exposition, security headers and optional bearer auth."""

from fastapi.testclient import TestClient
from hanson_obs import reset

import services.common as common


def test_metrics_endpoint_exposes_request_counters() -> None:
    reset()
    client = TestClient(common.create_app("test-service"))
    assert client.get("/healthz").status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.text
    assert "hanson_http_requests_total" in body
    assert 'path="/healthz"' in body
    assert "hanson_http_request_duration_seconds_count" in body


def test_security_headers_are_added() -> None:
    client = TestClient(common.create_app("test-service"))
    response = client.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_optional_bearer_auth(monkeypatch) -> None:
    monkeypatch.setattr(common, "API_AUTH_TOKEN", "secret-token")
    client = TestClient(common.create_app("test-service"))
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/some/protected").status_code == 401
    allowed = client.get(
        "/some/protected", headers={"Authorization": "Bearer secret-token"}
    )
    # 路由不存在时鉴权通过后为 404，而不是 401。
    assert allowed.status_code == 404
