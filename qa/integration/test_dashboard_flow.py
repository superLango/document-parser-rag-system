"""L2 集成链路：工作台模块（M5）。"""


async def test_overview_for_super_admin(client, super_token):
    resp = await client.get(
        "/api/v1/dashboard/overview",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["project"]["app_name"] == "HansonDOC RAG"
    assert data["project"]["database"] == "hanson_doc_rag_test"
    assert data["user"]["username"] == "admin"
    assert data["stats"]["users_total"] >= 1
    assert "login_trend" in data
    assert "recent_audit" in data


async def test_overview_for_member(client, member_user):
    token, _, _ = member_user
    resp = await client.get(
        "/api/v1/dashboard/overview", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["is_superuser"] is False


async def test_stats_denied_for_member(client, member_user):
    token, _, _ = member_user
    resp = await client.get(
        "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    resp2 = await client.get(
        "/api/v1/dashboard/trends", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp2.status_code == 403


async def test_stats_allowed_for_super(client, super_token):
    resp = await client.get(
        "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {super_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "users_total" in data and "audit_total" in data
    trends = await client.get(
        "/api/v1/dashboard/trends?days=7",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert trends.status_code == 200
    assert len(trends.json()["data"]) <= 7


async def test_system_info_available(client, member_user):
    token, _, _ = member_user
    resp = await client.get(
        "/api/v1/system/info", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    features = resp.json()["data"]["features"]
    assert features["rbac"] is True
    assert features["audit_log"] is True
