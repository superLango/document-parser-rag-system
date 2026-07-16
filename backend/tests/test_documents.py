"""文档管理端点测试（F1.6）。

覆盖 GET /api/v1/documents/ 列表、GET /documents/{id} 详情、
DELETE /documents/{id} 删除。上传/下载端点依赖 MinIO 对象存储，
通过 mock ``storage_service`` 隔离外部依赖。
"""

from unittest.mock import AsyncMock

import pytest

from app.models.document import Document
from app.services.storage_service import storage_service as storage_service_instance


@pytest.fixture
def mock_storage(monkeypatch):
    """mock storage_service 实例的外部 IO 方法，避免连接 MinIO。"""
    monkeypatch.setattr(
        storage_service_instance, "upload", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        storage_service_instance, "download", AsyncMock(return_value=b"fake-pdf-bytes")
    )
    monkeypatch.setattr(
        storage_service_instance, "delete", AsyncMock(return_value=None)
    )
    return storage_service_instance


class TestListDocuments:
    """GET /api/v1/documents/ 列表测试。"""

    @pytest.mark.asyncio
    async def test_list_empty(self, client, seed_user):
        """空库时应返回空列表与 total=0。"""
        resp = await client.get(
            "/api/v1/documents/", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_returns_documents(
        self, client, seed_user, db_session
    ):
        """库中存在文档时应返回对应条目。"""
        doc = Document(
            filename="test.pdf",
            file_size=1024,
            file_type="pdf",
            status="pending",
            minio_object_name="obj-1.pdf",
        )
        db_session.add(doc)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/documents/", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["filename"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_list_without_auth(self, client):
        """未认证访问应返回 401。"""
        resp = await client.get("/api/v1/documents/")
        assert resp.status_code == 401


class TestGetDocument:
    """GET /api/v1/documents/{document_id} 详情测试。"""

    @pytest.mark.asyncio
    async def test_get_existing_document(
        self, client, seed_user, db_session
    ):
        """存在的文档应返回详情。"""
        doc = Document(
            filename="doc.pdf",
            file_size=2048,
            file_type="pdf",
            status="completed",
            minio_object_name="obj-2.pdf",
        )
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)

        resp = await client.get(
            f"/api/v1/documents/{doc.id}", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["filename"] == "doc.pdf"

    @pytest.mark.asyncio
    async def test_get_nonexistent_document_returns_404(
        self, client, seed_user
    ):
        """不存在的文档 ID 应返回 400（BusinessException）。"""
        import uuid

        resp = await client.get(
            f"/api/v1/documents/{uuid.uuid4()}",
            headers=seed_user["headers"],
        )
        # BusinessException 对应 HTTP 400
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] != 0


class TestDeleteDocument:
    """DELETE /api/v1/documents/{document_id} 删除测试。"""

    @pytest.mark.asyncio
    async def test_delete_existing_document(
        self, client, seed_user, db_session, mock_storage
    ):
        """存在的文档应被删除，并触发存储服务删除。"""
        doc = Document(
            filename="del.pdf",
            file_size=512,
            file_type="pdf",
            status="pending",
            minio_object_name="obj-del.pdf",
        )
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)

        resp = await client.delete(
            f"/api/v1/documents/{doc.id}", headers=seed_user["headers"]
        )
        assert resp.status_code == 200
        # storage_service.delete 应被调用一次
        mock_storage.delete.assert_called_once_with("obj-del.pdf")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_400(self, client, seed_user):
        """删除不存在的文档应返回 400。"""
        import uuid

        resp = await client.delete(
            f"/api/v1/documents/{uuid.uuid4()}",
            headers=seed_user["headers"],
        )
        assert resp.status_code == 400
