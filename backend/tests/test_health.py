"""健康检查与根端点测试模块。

验证 /health 和 / 端点的基本可用性，不依赖外部服务。
"""

from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """测试 GET /health 返回 200 和 {"status": "ok"}。"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint(client: TestClient):
    """测试 GET / 返回 API 基本信息。"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Document Parser API"
    assert data["version"] == "1.0.0"
    assert data["docs"] == "/docs"
