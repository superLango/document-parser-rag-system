"""Schema 配置端点测试（F1.7）。

覆盖 GET /api/v1/schemas/ 列表、POST /schemas/ 创建、
PATCH /schemas/{id}/active 启用/停用。
"""

import pytest

from app.models.schema_model import SchemaConfig


class TestListSchemas:
    """GET /api/v1/schemas/ 列表测试。"""

    @pytest.mark.asyncio
    async def test_list_empty(self, client, seed_user):
        """空库时应返回空列表。"""
        resp = await client.get(
            "/api/v1/schemas/", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_returns_schemas(
        self, client, seed_user, db_session
    ):
        """库中存在 Schema 时应返回对应条目。"""
        schema = SchemaConfig(
            name="测试Schema",
            description="用于测试",
            schema_definition=[{"name": "field1", "type": "string"}],
            is_template=False,
        )
        db_session.add(schema)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/schemas/", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["name"] == "测试Schema"

    @pytest.mark.asyncio
    async def test_list_without_auth(self, client):
        """未认证访问应返回 401。"""
        resp = await client.get("/api/v1/schemas/")
        assert resp.status_code == 401


class TestCreateSchema:
    """POST /api/v1/schemas/ 创建测试。"""

    @pytest.mark.asyncio
    async def test_create_success(self, client, seed_user):
        """合法请求应创建 Schema 并返回 200。"""
        payload = {
            "name": "合同抽取",
            "description": "提取合同关键字段",
            "doc_type": "contract",
            "fields": [
                {"name": "甲方", "type": "string"},
                {"name": "乙方", "type": "string"},
                {"name": "金额", "type": "number"},
            ],
        }
        resp = await client.post(
            "/api/v1/schemas/", json=payload, headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["name"] == "合同抽取"
        assert body["data"]["is_active"] is True
        assert len(body["data"]["fields"]) == 3

    @pytest.mark.asyncio
    async def test_create_missing_name_returns_400(self, client, seed_user):
        """缺少 name 字段应返回参数校验错误。"""
        resp = await client.post(
            "/api/v1/schemas/",
            json={"description": "无名"},
            headers=seed_user["headers"],
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_without_auth(self, client):
        """未认证创建应返回 401。"""
        resp = await client.post(
            "/api/v1/schemas/", json={"name": "x"}
        )
        assert resp.status_code == 401


class TestToggleActive:
    """PATCH /api/v1/schemas/{id}/active 启用/停用测试。"""

    @pytest.mark.asyncio
    async def test_deactivate_schema(self, client, seed_user, db_session):
        """停用 Schema 应将 is_active 置为 False。"""
        schema = SchemaConfig(
            name="待停用",
            schema_definition=[],
            is_template=False,
        )
        db_session.add(schema)
        await db_session.commit()
        await db_session.refresh(schema)

        resp = await client.patch(
            f"/api/v1/schemas/{schema.id}/active",
            json={"is_active": False},
            headers=seed_user["headers"],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["is_active"] is False

    @pytest.mark.asyncio
    async def test_activate_schema(self, client, seed_user, db_session):
        """启用 Schema 应将 is_active 置为 True。"""
        schema = SchemaConfig(
            name="待启用",
            schema_definition=[],
            is_template=True,  # 初始为停用态
        )
        db_session.add(schema)
        await db_session.commit()
        await db_session.refresh(schema)

        resp = await client.patch(
            f"/api/v1/schemas/{schema.id}/active",
            json={"is_active": True},
            headers=seed_user["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["is_active"] is True

    @pytest.mark.asyncio
    async def test_toggle_nonexistent_returns_400(self, client, seed_user):
        """不存在的 Schema 应返回 400。"""
        import uuid

        resp = await client.patch(
            f"/api/v1/schemas/{uuid.uuid4()}/active",
            json={"is_active": True},
            headers=seed_user["headers"],
        )
        assert resp.status_code == 400
