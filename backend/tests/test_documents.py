"""文档管理端点测试模块。

测试 POST /api/v1/documents/ 上传、GET /api/v1/documents/ 列表、
GET /api/v1/documents/{id} 详情、DELETE /api/v1/documents/{id} 删除。
使用 mock 隔离 MinIO 存储服务与数据库查询，不依赖外部服务。
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.models.document import Document


def _create_sample_doc(**kwargs):
    """创建模拟文档对象。

    提供合理的默认值，可通过 kwargs 覆盖任意字段。
    """
    defaults = {
        "id": uuid.uuid4(),
        "filename": "test.pdf",
        "file_size": 1024,
        "file_type": ".pdf",
        "status": "completed",
        "minio_object_name": "documents/sample.pdf",
        "created_at": datetime.now(),
        "updated_at": None,
    }
    defaults.update(kwargs)
    return Document(**defaults)


def test_upload_document(client: TestClient, db_session, auth_headers):
    """测试上传文档。

    Mock storage_service.upload 和数据库操作（add/commit/refresh），
    验证上传成功后返回文档信息。
    """
    # Mock 存储服务上传方法
    with patch(
        "app.api.v1.endpoints.documents.storage_service.upload",
        new_callable=AsyncMock,
        return_value="documents/test.pdf",
    ):
        # Mock 数据库操作
        db_session.add = MagicMock()
        db_session.commit = AsyncMock()

        # refresh 需要设置数据库生成的字段
        async def mock_refresh(obj, *args, **kwargs):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now()
            obj.updated_at = None

        db_session.refresh = AsyncMock(side_effect=mock_refresh)

        response = client.post(
            "/api/v1/documents/",
            files={"file": ("test.pdf", b"test content", "application/pdf")},
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert data["data"]["filename"] == "test.pdf"
    assert data["data"]["file_size"] == len(b"test content")
    assert data["data"]["status"] == "pending"
    # 当前实现 file_type 不含点号
    assert data["data"]["file_type"] == "pdf"


def test_list_documents(client: TestClient, db_session, auth_headers):
    """测试查询文档列表。

    Mock db.execute 按调用顺序返回计数结果和列表结果，
    验证响应中包含分页数据。
    """
    sample_doc = _create_sample_doc()

    # 构造计数查询结果（第一次 execute 调用）
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    # 构造列表查询结果（第二次 execute 调用）
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = [sample_doc]

    # Mock execute 按调用顺序返回不同结果
    db_session.execute = AsyncMock(side_effect=[count_result, list_result])

    response = client.get(
        "/api/v1/documents/",
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert data["data"]["total"] == 1
    assert len(data["data"]["items"]) == 1
    assert data["data"]["page"] == 1
    assert data["data"]["page_size"] == 20
    assert data["data"]["items"][0]["filename"] == "test.pdf"


def test_get_document_detail(client: TestClient, db_session, auth_headers):
    """测试查询单个文档详情。

    Mock db.execute 返回模拟文档，验证响应中包含文档信息。
    """
    doc_id = uuid.uuid4()
    sample_doc = _create_sample_doc(id=doc_id)

    result = MagicMock()
    result.scalar_one_or_none.return_value = sample_doc
    db_session.execute = AsyncMock(return_value=result)

    response = client.get(
        f"/api/v1/documents/{doc_id}",
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert data["data"]["filename"] == "test.pdf"
    assert data["data"]["file_type"] == ".pdf"
    assert data["data"]["status"] == "completed"


def test_delete_document(client: TestClient, db_session, auth_headers):
    """测试删除文档。

    Mock db.execute 返回模拟文档，Mock storage_service.delete 和数据库删除操作，
    验证删除成功后返回成功消息。
    """
    doc_id = uuid.uuid4()
    sample_doc = _create_sample_doc(id=doc_id)

    # 第一次 execute 返回查询结果，第二次 execute 执行删除语句（返回值不使用）
    result = MagicMock()
    result.scalar_one_or_none.return_value = sample_doc
    db_session.execute = AsyncMock(return_value=result)
    db_session.commit = AsyncMock()

    with patch(
        "app.api.v1.endpoints.documents.storage_service.delete",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = client.delete(
            f"/api/v1/documents/{doc_id}",
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert "删除成功" in data["message"]
