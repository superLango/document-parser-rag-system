"""RAG 知识库任务测试模块。

测试 rag_tasks arq 任务的完整执行流程：
- index_document_impl：文档入库（分块 → 嵌入 → Milvus 入库）
- rebuild_index_impl：重建整个知识库索引
- remove_document_impl：从知识库移除文档

所有外部依赖（数据库 / 分块器 / 嵌入模型 / Milvus）均通过 mock 隔离，
确保无 GPU / 无模型 / 无外部服务环境下可运行。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.models.document import Document
from app.tasks import rag_tasks


# ---------------------------------------------------------------
# 测试常量
# ---------------------------------------------------------------
_DOCUMENT_ID = "550e8400-e29b-41d4-a716-446655440000"

_FAKE_CHUNKS: list[dict] = [
    {
        "chunk_id": f"{_DOCUMENT_ID}_1_0",
        "text": "1 总则\n本规范适用于工业采购。",
        "metadata": {
            "doc_id": _DOCUMENT_ID,
            "doc_title": "采购技术规范.pdf",
            "file_name": "采购技术规范.pdf",
            "title_chain": "采购技术规范.pdf > 1 总则",
            "section_level": "1",
            "section_title": "总则",
            "chunk_index": 0,
        },
    },
    {
        "chunk_id": f"{_DOCUMENT_ID}_2_0",
        "text": "2 材料\n钢材应采用高强度结构钢。",
        "metadata": {
            "doc_id": _DOCUMENT_ID,
            "doc_title": "采购技术规范.pdf",
            "file_name": "采购技术规范.pdf",
            "title_chain": "采购技术规范.pdf > 2 材料",
            "section_level": "2",
            "section_title": "材料",
            "chunk_index": 0,
        },
    },
]

_EMBED_RESULT = {
    "dense_vectors": np.zeros((2, 1024), dtype=np.float32),
    "sparse_vectors": [{"1": 0.5}, {"2": 0.3}],
    "sparse_indices": [
        {"indices": [1], "values": [0.5]},
        {"indices": [2], "values": [0.3]},
    ],
}

# 模拟 vector_store.insert 返回的主键列表
_FAKE_PRIMARY_KEYS: list[int] = [1, 2]


# ---------------------------------------------------------------
# 辅助：构造 mock 数据库会话
# ---------------------------------------------------------------
class _MockAsyncSessionContext:
    """模拟 AsyncSessionLocal 的异步上下文管理器。

    支持多次 ``async with`` 调用（成功路径与错误恢复路径各一次），
    每次进入时返回同一个 mock 会话对象。
    """

    def __init__(self, db_mock):
        self._db_mock = db_mock

    async def __aenter__(self):
        return self._db_mock

    async def __aexit__(self, *args):
        return False


def _make_mock_document(
    document_id: str = _DOCUMENT_ID,
    status: str = "completed",
    parsed_text: str = "1 总则\n本规范适用于工业采购。\n2 材料\n钢材应采用高强度结构钢。",
    filename: str = "采购技术规范.pdf",
):
    """创建模拟 Document 对象。

    使用 MagicMock 以支持属性赋值与状态追踪。
    """
    doc = MagicMock(spec=Document)
    doc.id = uuid.UUID(document_id)
    doc.status = status
    doc.filename = filename
    doc.parsed_text = parsed_text
    doc.file_size = 1024
    doc.file_type = "pdf"
    return doc


def _make_mock_db(document=None, documents_list=None):
    """创建 mock AsyncSession。

    配置 db.get 按 (Model, uuid) 参数返回 mock 文档对象，
    db.execute 返回模拟的查询结果。

    rebuild_index 场景下，_index_document_async 会再次通过 db.get 加载文档，
    因此当 document 未显式指定时，从 documents_list 中按 UUID 查找。

    Args:
        document: 单文档查询时返回的文档对象。
        documents_list: 列表查询时返回的文档列表（用于 rebuild_index）。

    Returns:
        MagicMock: 模拟的异步会话。
    """
    db = MagicMock()

    async def _mock_get(model, obj_id, **kwargs):
        if model is Document:
            # 优先使用显式指定的 document
            if document is not None:
                return document
            # rebuild 场景：从 documents_list 中按 UUID 查找
            if documents_list is not None:
                for doc in documents_list:
                    if doc.id == obj_id:
                        return doc
            return None
        return None

    db.get = AsyncMock(side_effect=_mock_get)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    # 模拟 execute 返回（用于 select 查询）
    execute_result = MagicMock()
    if documents_list is not None:
        execute_result.scalars.return_value.all.return_value = documents_list
    db.execute = AsyncMock(return_value=execute_result)

    return db


def _setup_session_local_patch(db_mock):
    """构造 AsyncSessionLocal 的 patcher。

    使得 ``async with AsyncSessionLocal() as db:`` 返回 db_mock。
    """
    mock_session_local = MagicMock(return_value=_MockAsyncSessionContext(db_mock))
    return patch.object(rag_tasks, "AsyncSessionLocal", mock_session_local)


# ---------------------------------------------------------------
# 1. index_document_impl 任务测试
# ---------------------------------------------------------------
class TestIndexDocument:
    """index_document_impl 任务测试。"""

    @pytest.mark.asyncio
    async def test_index_document_calls_all_services_in_order(self):
        """测试任务按正确顺序调用所有服务。

        验证调用序列：chunker.chunk_document → embedding_service.embed_documents
        → vector_store.insert。
        """
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        call_order = []

        async def _track_chunk(*args, **kwargs):
            call_order.append("chunk_document")
            return _FAKE_CHUNKS

        async def _track_embed(*args, **kwargs):
            call_order.append("embed_documents")
            return _EMBED_RESULT

        async def _track_insert(*args, **kwargs):
            call_order.append("insert")
            return _FAKE_PRIMARY_KEYS

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(side_effect=_track_chunk),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(side_effect=_track_embed),
            ),
            patch.object(
                rag_tasks.vector_store, "insert",
                new=AsyncMock(side_effect=_track_insert),
            ),
        ):
            result = await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        # 验证服务调用顺序正确
        assert call_order == [
            "chunk_document",
            "embed_documents",
            "insert",
        ]

        # 验证返回结果
        assert isinstance(result, dict)
        assert result["doc_id"] == _DOCUMENT_ID
        assert result["status"] == "indexed"
        assert result["chunk_count"] == len(_FAKE_CHUNKS)

    @pytest.mark.asyncio
    async def test_index_document_sets_status_indexed(self):
        """测试任务完成后 Document 状态为 indexed。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(return_value=_EMBED_RESULT),
            ),
            patch.object(
                rag_tasks.vector_store, "insert",
                new=AsyncMock(return_value=_FAKE_PRIMARY_KEYS),
            ),
        ):
            await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        # 验证文档状态最终为 indexed
        assert doc.status == "indexed"

    @pytest.mark.asyncio
    async def test_index_document_progress_updates(self):
        """测试任务进度按序列上报。

        验证 _update_progress 被调用时的 progress 值序列为：
        10 → 20 → 40 → 70 → 90 → 100。
        """
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        mock_update = AsyncMock()

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(return_value=_EMBED_RESULT),
            ),
            patch.object(
                rag_tasks.vector_store, "insert",
                new=AsyncMock(return_value=_FAKE_PRIMARY_KEYS),
            ),
            patch("app.tasks.rag_tasks._update_progress", new=mock_update),
        ):
            await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        # 提取所有进度上报值（_update_progress 第二个位置参数为 progress）
        progress_values = [call.args[1] for call in mock_update.call_args_list]

        # 验证进度序列包含所有预期值
        assert 10 in progress_values   # 初始
        assert 20 in progress_values   # 准备分块
        assert 40 in progress_values   # 分块中
        assert 70 in progress_values   # 嵌入中
        assert 90 in progress_values   # 入库中
        assert 100 in progress_values  # 完成

    @pytest.mark.asyncio
    async def test_index_document_calls_db_commit(self):
        """测试任务完成后调用了 db.commit。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(return_value=_EMBED_RESULT),
            ),
            patch.object(
                rag_tasks.vector_store, "insert",
                new=AsyncMock(return_value=_FAKE_PRIMARY_KEYS),
            ),
        ):
            await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        # 验证 commit 被调用（至少一次用于标记 indexed）
        assert db.commit.await_count >= 1

    @pytest.mark.asyncio
    async def test_index_document_passes_correct_text_to_chunker(self):
        """测试将 Document.parsed_text 传给分块器。"""
        doc = _make_mock_document(parsed_text="自定义解析文本")
        db = _make_mock_db(document=doc)

        chunk_mock = AsyncMock(return_value=_FAKE_CHUNKS)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document", new=chunk_mock,
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(return_value=_EMBED_RESULT),
            ),
            patch.object(
                rag_tasks.vector_store, "insert",
                new=AsyncMock(return_value=_FAKE_PRIMARY_KEYS),
            ),
        ):
            await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        # 验证分块器接收到的文本为 Document.parsed_text
        call_args = chunk_mock.call_args
        assert call_args.args[0] == "自定义解析文本"

    @pytest.mark.asyncio
    async def test_index_document_passes_chunks_text_to_embedder(self):
        """测试将分块文本列表传给嵌入服务。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        embed_mock = AsyncMock(return_value=_EMBED_RESULT)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents", new=embed_mock,
            ),
            patch.object(
                rag_tasks.vector_store, "insert",
                new=AsyncMock(return_value=_FAKE_PRIMARY_KEYS),
            ),
        ):
            await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        # 验证嵌入服务接收到的是分块文本列表
        call_args = embed_mock.call_args
        texts = call_args.args[0]
        assert texts == [c["text"] for c in _FAKE_CHUNKS]

    @pytest.mark.asyncio
    async def test_index_document_document_not_found_raises(self):
        """测试文档不存在时抛出异常。"""
        db = _make_mock_db(document=None)

        with _setup_session_local_patch(db):
            with pytest.raises(Exception) as exc_info:
                await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

            # 应抛出包含"文档不存在"的异常
            assert "不存在" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_index_document_no_parsed_text_raises(self):
        """测试文档无解析文本时抛出异常。"""
        doc = _make_mock_document(parsed_text=None)
        db = _make_mock_db(document=doc)

        with _setup_session_local_patch(db):
            with pytest.raises(Exception) as exc_info:
                await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

            assert "解析" in str(exc_info.value) or "索引" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_index_document_empty_chunks_raises(self):
        """测试分块结果为空时抛出异常。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=[]),
            ),
        ):
            with pytest.raises(Exception) as exc_info:
                await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

            assert "分块" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_index_document_embedding_failure_sets_failed(self):
        """测试嵌入失败时 Document 状态被置为 failed。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(side_effect=RuntimeError("嵌入失败")),
            ),
        ):
            with pytest.raises(RuntimeError, match="嵌入失败"):
                await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        # 验证文档状态被置为 failed
        assert doc.status == "failed"

    @pytest.mark.asyncio
    async def test_index_document_vector_store_failure_sets_failed(self):
        """测试向量入库失败时 Document 状态被置为 failed。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(return_value=_EMBED_RESULT),
            ),
            patch.object(
                rag_tasks.vector_store, "insert",
                new=AsyncMock(side_effect=RuntimeError("Milvus 入库失败")),
            ),
        ):
            with pytest.raises(RuntimeError, match="Milvus 入库失败"):
                await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        assert doc.status == "failed"

    @pytest.mark.asyncio
    async def test_index_document_failure_calls_rollback(self):
        """测试任务失败时调用了 db.rollback。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(side_effect=RuntimeError("嵌入失败")),
            ),
        ):
            with pytest.raises(RuntimeError):
                await rag_tasks.index_document_impl(_DOCUMENT_ID, {})

        # 验证 rollback 被调用
        db.rollback.assert_awaited()


# ---------------------------------------------------------------
# 2. rebuild_index_impl 任务测试
# ---------------------------------------------------------------
class TestRebuildIndex:
    """rebuild_index_impl 任务测试。"""

    @pytest.mark.asyncio
    async def test_rebuild_index_clears_vector_store(self):
        """测试重建任务先清空 Milvus 集合。"""
        doc1 = _make_mock_document(document_id=_DOCUMENT_ID)
        doc2 = _make_mock_document(
            document_id="660e8400-e29b-41d4-a716-446655440000"
        )
        db = _make_mock_db(documents_list=[doc1, doc2])

        delete_all_mock = AsyncMock()

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.vector_store, "delete_all", new=delete_all_mock,
            ),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(return_value=_EMBED_RESULT),
            ),
            patch.object(
                rag_tasks.vector_store, "insert",
                new=AsyncMock(return_value=_FAKE_PRIMARY_KEYS),
            ),
        ):
            result = await rag_tasks.rebuild_index_impl({})

        # 验证 delete_all 被调用
        delete_all_mock.assert_awaited()
        # 验证结果包含成功计数
        assert result["total_docs"] == 2
        assert result["success_count"] == 2
        assert result["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_rebuild_index_indexes_all_documents(self):
        """测试重建任务对所有文档重新索引。"""
        doc1 = _make_mock_document(document_id=_DOCUMENT_ID)
        doc2 = _make_mock_document(
            document_id="660e8400-e29b-41d4-a716-446655440000"
        )
        db = _make_mock_db(documents_list=[doc1, doc2])

        insert_mock = AsyncMock(return_value=_FAKE_PRIMARY_KEYS)

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.vector_store, "delete_all",
                new=AsyncMock(),
            ),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(return_value=_EMBED_RESULT),
            ),
            patch.object(
                rag_tasks.vector_store, "insert", new=insert_mock,
            ),
        ):
            result = await rag_tasks.rebuild_index_impl({})

        # 验证 insert 被调用两次（每文档一次）
        assert insert_mock.await_count == 2
        assert result["success_count"] == 2

    @pytest.mark.asyncio
    async def test_rebuild_index_partial_failure(self):
        """测试部分文档索引失败时仍继续处理其他文档。"""
        doc1 = _make_mock_document(document_id=_DOCUMENT_ID)
        doc2 = _make_mock_document(
            document_id="660e8400-e29b-41d4-a716-446655440000"
        )
        db = _make_mock_db(documents_list=[doc1, doc2])

        # 第一文档成功，第二文档失败
        insert_mock = AsyncMock(
            side_effect=[_FAKE_PRIMARY_KEYS, RuntimeError("入库失败")]
        )

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.vector_store, "delete_all",
                new=AsyncMock(),
            ),
            patch.object(
                rag_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                rag_tasks.embedding_service, "embed_documents",
                new=AsyncMock(return_value=_EMBED_RESULT),
            ),
            patch.object(
                rag_tasks.vector_store, "insert", new=insert_mock,
            ),
        ):
            result = await rag_tasks.rebuild_index_impl({})

        # 验证一成功一失败
        assert result["total_docs"] == 2
        assert result["success_count"] == 1
        assert result["failed_count"] == 1
        assert len(result["failed_docs"]) == 1

    @pytest.mark.asyncio
    async def test_rebuild_index_no_documents(self):
        """测试无已解析文档时返回空结果。"""
        db = _make_mock_db(documents_list=[])

        with (
            _setup_session_local_patch(db),
            patch.object(
                rag_tasks.vector_store, "delete_all",
                new=AsyncMock(),
            ),
        ):
            result = await rag_tasks.rebuild_index_impl({})

        assert result["total_docs"] == 0
        assert result["success_count"] == 0
        assert result["failed_count"] == 0


# ---------------------------------------------------------------
# 3. remove_document_impl 任务测试
# ---------------------------------------------------------------
class TestRemoveDocument:
    """remove_document_impl 任务测试。"""

    @pytest.mark.asyncio
    async def test_remove_document_calls_vector_store_delete(self):
        """测试移除文档调用 vector_store.delete_by_doc_id。"""
        delete_mock = AsyncMock(return_value=2)

        with patch.object(
            rag_tasks.vector_store, "delete_by_doc_id", new=delete_mock
        ):
            result = await rag_tasks.remove_document_impl(_DOCUMENT_ID, {})

        # 验证 delete_by_doc_id 被调用
        delete_mock.assert_awaited_once_with(_DOCUMENT_ID)
        # 验证返回结果
        assert result["doc_id"] == _DOCUMENT_ID
        assert result["status"] == "removed"

    @pytest.mark.asyncio
    async def test_remove_document_passes_correct_doc_id(self):
        """测试移除文档时传递正确的 doc_id。"""
        delete_mock = AsyncMock(return_value=1)
        custom_doc_id = "770e8400-e29b-41d4-a716-446655440000"

        with patch.object(
            rag_tasks.vector_store, "delete_by_doc_id", new=delete_mock
        ):
            await rag_tasks.remove_document_impl(custom_doc_id, {})

        # 验证 doc_id 正确传递
        call_args = delete_mock.call_args
        assert call_args.args[0] == custom_doc_id

    @pytest.mark.asyncio
    async def test_remove_document_failure_raises(self):
        """测试移除文档失败时抛出异常。"""
        with patch.object(
            rag_tasks.vector_store, "delete_by_doc_id",
            new=AsyncMock(side_effect=RuntimeError("Milvus 删除失败")),
        ):
            with pytest.raises(RuntimeError, match="Milvus 删除失败"):
                await rag_tasks.remove_document_impl(_DOCUMENT_ID, {})
