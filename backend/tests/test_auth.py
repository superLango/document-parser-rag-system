"""认证端点测试模块。

测试 POST /api/v1/auth/login 和 GET /api/v1/auth/me 接口。
使用 mock 隔离数据库查询，不依赖实际数据库连接。
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def test_login_valid_credentials(client: TestClient):
    """测试使用有效凭据登录成功。

    Mock authenticate_user 返回模拟用户，验证响应中包含有效的 access_token。
    """
    # 构造模拟用户对象
    mock_user = MagicMock()
    mock_user.username = "testuser"
    mock_user.id = uuid.uuid4()
    mock_user.email = "test@example.com"
    mock_user.is_active = True
    mock_user.created_at = datetime.now()

    # Mock authenticate_user 返回模拟用户
    with patch(
        "app.api.v1.endpoints.auth.authenticate_user",
        new_callable=AsyncMock,
        return_value=mock_user,
    ):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "testpass"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert "access_token" in data["data"]
    assert data["data"]["token_type"] == "bearer"
    assert data["data"]["expires_in"] > 0


def test_login_invalid_credentials(client: TestClient):
    """测试使用无效凭据登录返回 401。

    Mock authenticate_user 返回 None，验证响应状态码为 401。
    """
    with patch(
        "app.api.v1.endpoints.auth.authenticate_user",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "wrong", "password": "wrongpass"},
        )

    assert response.status_code == 401
    data = response.json()
    assert data["code"] != 0
    assert "用户名或密码错误" in data["message"]


def test_me_without_token(client: TestClient):
    """测试未携带令牌访问 /auth/me 返回 401。"""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    data = response.json()
    assert data["code"] != 0
