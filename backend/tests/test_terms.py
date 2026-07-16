"""术语库端点测试（F1.8）。

覆盖 GET /api/v1/terms/ 列表、GET /terms/?status=pending 状态过滤、
PUT /terms/{id}/review 审核操作。
"""

import pytest

from app.models.term import Term


class TestListTerms:
    """GET /api/v1/terms/ 列表测试。"""

    @pytest.mark.asyncio
    async def test_list_empty(self, client, seed_user):
        """空库时应返回空列表。"""
        resp = await client.get(
            "/api/v1/terms/", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_returns_terms(self, client, seed_user, db_session):
        """库中存在术语时应返回对应条目。"""
        term = Term(
            term_name="人工智能",
            standard_name="AI",
            definition="Artificial Intelligence",
            synonyms=["AI", "机器智能"],
            status="active",
        )
        db_session.add(term)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/terms/", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["term"] == "人工智能"

    @pytest.mark.asyncio
    async def test_list_without_auth(self, client):
        """未认证访问应返回 401。"""
        resp = await client.get("/api/v1/terms/")
        assert resp.status_code == 401


class TestListTermsByStatus:
    """GET /api/v1/terms/?status=pending 状态过滤测试。"""

    @pytest.mark.asyncio
    async def test_filter_pending_status(self, client, seed_user, db_session):
        """status=pending 应仅返回 pending 状态的术语。"""
        db_session.add_all(
            [
                Term(term_name="待审1", status="pending"),
                Term(term_name="待审2", status="pending"),
                Term(term_name="已激活", status="active"),
                Term(term_name="已废弃", status="deprecated"),
            ]
        )
        await db_session.commit()

        resp = await client.get(
            "/api/v1/terms/?status=pending", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 2
        names = [item["term"] for item in body["data"]["items"]]
        assert "待审1" in names
        assert "待审2" in names

    @pytest.mark.asyncio
    async def test_filter_active_status(self, client, seed_user, db_session):
        """status=active 应仅返回 active 状态的术语。"""
        db_session.add_all(
            [
                Term(term_name="激活1", status="active"),
                Term(term_name="废弃1", status="deprecated"),
            ]
        )
        await db_session.commit()

        resp = await client.get(
            "/api/v1/terms/?status=active", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["term"] == "激活1"

    @pytest.mark.asyncio
    async def test_filter_no_match_returns_empty(
        self, client, seed_user, db_session
    ):
        """无匹配状态时应返回空列表。"""
        db_session.add(Term(term_name="激活项", status="active"))
        await db_session.commit()

        resp = await client.get(
            "/api/v1/terms/?status=pending", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0


class TestReviewTerm:
    """PUT /api/v1/terms/{id}/review 审核测试。"""

    @pytest.mark.asyncio
    async def test_approve_term(self, client, seed_user, db_session):
        """approve 应将术语状态置为 active。"""
        term = Term(term_name="待审核", status="pending")
        db_session.add(term)
        await db_session.commit()
        await db_session.refresh(term)

        resp = await client.put(
            f"/api/v1/terms/{term.id}/review",
            json={"action": "approve"},
            headers=seed_user["headers"],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # 验证数据库中状态已更新
        await db_session.refresh(term)
        assert term.status == "active"

    @pytest.mark.asyncio
    async def test_reject_term(self, client, seed_user, db_session):
        """reject 应将术语状态置为 deprecated。"""
        term = Term(term_name="待拒绝", status="pending")
        db_session.add(term)
        await db_session.commit()
        await db_session.refresh(term)

        resp = await client.put(
            f"/api/v1/terms/{term.id}/review",
            json={"action": "reject"},
            headers=seed_user["headers"],
        )
        assert resp.status_code == 200
        await db_session.refresh(term)
        assert term.status == "deprecated"

    @pytest.mark.asyncio
    async def test_review_nonexistent_returns_400(self, client, seed_user):
        """审核不存在的术语应返回 400。"""
        import uuid

        resp = await client.put(
            f"/api/v1/terms/{uuid.uuid4()}/review",
            json={"action": "approve"},
            headers=seed_user["headers"],
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_review_invalid_action_returns_400(
        self, client, seed_user, db_session
    ):
        """非法 action 值应返回参数校验错误。"""
        term = Term(term_name="非法操作", status="pending")
        db_session.add(term)
        await db_session.commit()
        await db_session.refresh(term)

        resp = await client.put(
            f"/api/v1/terms/{term.id}/review",
            json={"action": "invalid"},
            headers=seed_user["headers"],
        )
        assert resp.status_code == 400
