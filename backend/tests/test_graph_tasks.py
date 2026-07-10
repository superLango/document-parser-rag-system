"""知识图谱任务测试模块。

测试 graph_tasks Celery 任务的完整执行流程：
- build_document_graph：单文档图谱构建（分块 → 抽取 → 去重 → Neo4j 入库）
- rebuild_all_graphs：重建所有文档知识图谱
- remove_document_graph：删除文档图谱数据

所有外部依赖（数据库 / 分块器 / 抽取服务 / 图存储）均通过 mock 隔离，
确保无 GPU / 无模型 / 无外部服务环境下可运行。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.document import Document
from app.services.graph_extract_service import Entity, ExtractionResult, Relation
from app.tasks import graph_tasks


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
        "text": "2 材料\n钢材应采用Q235高强度结构钢，执行GB/T700标准。",
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

# 模拟抽取结果：两段文本分别抽取出的实体与关系
_EXTRACTION_RESULTS: list[ExtractionResult] = [
    ExtractionResult(
        entities=[
            Entity(text="工业采购", type="组织"),
        ],
        relations=[],
    ),
    ExtractionResult(
        entities=[
            Entity(text="Q235高强度结构钢", type="材料"),
            Entity(text="GB/T700", type="标准"),
        ],
        relations=[
            Relation(
                head="Q235高强度结构钢",
                relation="执行标准",
                tail="GB/T700",
            ),
        ],
    ),
]

# 模拟 batch_create 返回的入库统计
_FAKE_STORE_RESULT: dict = {
    "nodes_created": 3,
    "relations_created": 1,
}


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
    parsed_text: str = "1 总则\n本规范适用于工业采购。\n2 材料\n钢材应采用Q235高强度结构钢。",
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

    Args:
        document: 单文档查询时返回的文档对象。
        documents_list: 列表查询时返回的文档列表（用于 rebuild_all_graphs）。

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
    return patch.object(graph_tasks, "AsyncSessionLocal", mock_session_local)


# ---------------------------------------------------------------
# 1. build_document_graph 任务测试
# ---------------------------------------------------------------
class TestBuildDocumentGraph:
    """build_document_graph 任务测试。"""

    def test_build_document_graph_success(self):
        """测试任务成功完成全流程。

        验证调用序列：chunker.chunk_document → graph_extract_service.extract_batch
        → graph_store.batch_create，并返回正确的统计信息。
        """
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        call_order = []

        async def _track_chunk(*args, **kwargs):
            call_order.append("chunk_document")
            return _FAKE_CHUNKS

        async def _track_extract(*args, **kwargs):
            call_order.append("extract_batch")
            return _EXTRACTION_RESULTS

        async def _track_store(*args, **kwargs):
            call_order.append("batch_create")
            return _FAKE_STORE_RESULT

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(side_effect=_track_chunk),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(side_effect=_track_extract),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create",
                new=AsyncMock(side_effect=_track_store),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            result = graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证服务调用顺序正确
        assert call_order == [
            "chunk_document",
            "extract_batch",
            "batch_create",
        ]

        # 验证返回结果
        assert isinstance(result, dict)
        assert result["doc_id"] == _DOCUMENT_ID
        assert result["status"] == "graph_built"
        # 3 个不重复实体（工业采购、Q235高强度结构钢、GB/T700）
        assert result["entity_count"] == 3
        # 1 个不重复关系
        assert result["relation_count"] == 1

    def test_build_document_graph_sets_status_graph_built(self):
        """测试任务完成后 Document 状态为 graph_built。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create",
                new=AsyncMock(return_value=_FAKE_STORE_RESULT),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证文档状态最终为 graph_built
        assert doc.status == "graph_built"

    def test_build_document_graph_progress_updates(self):
        """测试任务进度按序列上报。

        验证 update_state 被调用时的 progress 值序列为：
        10 → 30 → 60 → 90 → 100。
        """
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        update_state_mock = MagicMock()

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create",
                new=AsyncMock(return_value=_FAKE_STORE_RESULT),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
                new=update_state_mock,
            ),
        ):
            graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 提取所有 PROGRESS 状态的 progress 值
        progress_values = []
        for call in update_state_mock.call_args_list:
            args, kwargs = call
            if kwargs.get("state") == "PROGRESS":
                meta = kwargs.get("meta", {})
                if "progress" in meta:
                    progress_values.append(meta["progress"])

        # 验证进度序列包含所有预期值
        assert 10 in progress_values   # 初始
        assert 30 in progress_values   # 分块中
        assert 60 in progress_values   # 抽取中
        assert 90 in progress_values   # 入库中
        assert 100 in progress_values  # 完成

    def test_build_document_graph_calls_db_commit(self):
        """测试任务完成后调用了 db.commit。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create",
                new=AsyncMock(return_value=_FAKE_STORE_RESULT),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证 commit 被调用（至少一次用于标记 graph_built）
        assert db.commit.await_count >= 1

    def test_build_document_graph_passes_correct_text_to_chunker(self):
        """测试将 Document.parsed_text 传给分块器。"""
        doc = _make_mock_document(parsed_text="自定义解析文本")
        db = _make_mock_db(document=doc)

        chunk_mock = AsyncMock(return_value=_FAKE_CHUNKS)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document", new=chunk_mock,
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create",
                new=AsyncMock(return_value=_FAKE_STORE_RESULT),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证分块器接收到的文本为 Document.parsed_text
        call_args = chunk_mock.call_args
        assert call_args.args[0] == "自定义解析文本"

    def test_build_document_graph_passes_chunks_text_to_extractor(self):
        """测试将分块文本列表传给抽取服务。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        extract_mock = AsyncMock(return_value=_EXTRACTION_RESULTS)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=extract_mock,
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create",
                new=AsyncMock(return_value=_FAKE_STORE_RESULT),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证抽取服务接收到的是分块文本列表
        call_args = extract_mock.call_args
        texts = call_args.args[0]
        assert texts == [c["text"] for c in _FAKE_CHUNKS]

    def test_build_document_graph_document_not_found_raises(self):
        """测试文档不存在时抛出异常。"""
        db = _make_mock_db(document=None)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            with pytest.raises(Exception) as exc_info:
                graph_tasks.build_document_graph(_DOCUMENT_ID)

            # 应抛出包含"文档不存在"的异常
            assert "不存在" in str(exc_info.value)

    def test_build_document_graph_empty_text_raises(self):
        """测试文档无解析文本时抛出异常。"""
        doc = _make_mock_document(parsed_text=None)
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            with pytest.raises(Exception) as exc_info:
                graph_tasks.build_document_graph(_DOCUMENT_ID)

            assert "解析" in str(exc_info.value) or "图谱" in str(exc_info.value)

    def test_build_document_graph_empty_chunks_raises(self):
        """测试分块结果为空时抛出异常。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            with pytest.raises(Exception) as exc_info:
                graph_tasks.build_document_graph(_DOCUMENT_ID)

            assert "分块" in str(exc_info.value)

    def test_build_document_graph_extract_failure_sets_failed(self):
        """测试抽取失败时 Document 状态被置为 failed。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(side_effect=RuntimeError("抽取失败")),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            with pytest.raises(RuntimeError, match="抽取失败"):
                graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证文档状态被置为 failed
        assert doc.status == "failed"

    def test_build_document_graph_store_failure_sets_failed(self):
        """测试图入库失败时 Document 状态被置为 failed。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create",
                new=AsyncMock(side_effect=RuntimeError("Neo4j 入库失败")),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            with pytest.raises(RuntimeError, match="Neo4j 入库失败"):
                graph_tasks.build_document_graph(_DOCUMENT_ID)

        assert doc.status == "failed"

    def test_build_document_graph_failure_calls_rollback(self):
        """测试任务失败时调用了 db.rollback。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(side_effect=RuntimeError("抽取失败")),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            with pytest.raises(RuntimeError):
                graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证 rollback 被调用
        db.rollback.assert_awaited()

    def test_build_document_graph_deduplicates_entities(self):
        """测试相同名称的实体被去重合并。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        # 两段抽取结果包含相同实体，应被去重
        dedup_results = [
            ExtractionResult(
                entities=[Entity(text="Q235钢材", type="材料")],
                relations=[],
            ),
            ExtractionResult(
                entities=[
                    Entity(text="Q235钢材", type="材料"),  # 重复实体
                    Entity(text="GB/T700", type="标准"),
                ],
                relations=[],
            ),
        ]

        store_mock = AsyncMock(return_value=_FAKE_STORE_RESULT)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=dedup_results),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create", new=store_mock,
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            result = graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证传入 batch_create 的节点数为 2（去重后）
        nodes_arg = store_mock.call_args.args[0]
        assert len(nodes_arg) == 2
        # 验证返回结果中的 entity_count 反映去重后的数量
        assert result["entity_count"] == 2

    def test_build_document_graph_deduplicates_relations(self):
        """测试相同关系被去重合并。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        # 两段抽取结果包含相同关系，应被去重
        dedup_results = [
            ExtractionResult(
                entities=[
                    Entity(text="Q235钢材", type="材料"),
                    Entity(text="GB/T700", type="标准"),
                ],
                relations=[
                    Relation(head="Q235钢材", relation="执行标准", tail="GB/T700"),
                ],
            ),
            ExtractionResult(
                entities=[],
                relations=[
                    Relation(
                        head="Q235钢材", relation="执行标准", tail="GB/T700",  # 重复关系
                    ),
                ],
            ),
        ]

        store_mock = AsyncMock(return_value=_FAKE_STORE_RESULT)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=dedup_results),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create", new=store_mock,
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            result = graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证传入 batch_create 的关系数为 1（去重后）
        relations_arg = store_mock.call_args.args[1]
        assert len(relations_arg) == 1
        assert result["relation_count"] == 1

    def test_build_document_graph_attaches_doc_id_to_nodes(self):
        """测试所有节点都附带 doc_id 属性以支持文档级追溯。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc)

        store_mock = AsyncMock(return_value=_FAKE_STORE_RESULT)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create", new=store_mock,
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
        ):
            graph_tasks.build_document_graph(_DOCUMENT_ID)

        # 验证所有节点均包含 doc_id
        nodes_arg = store_mock.call_args.args[0]
        for node in nodes_arg:
            assert node["properties"]["doc_id"] == _DOCUMENT_ID


# ---------------------------------------------------------------
# 2. rebuild_all_graphs 任务测试
# ---------------------------------------------------------------
class TestRebuildAllGraphs:
    """rebuild_all_graphs 任务测试。"""

    def test_rebuild_all_graphs_success(self):
        """测试重建任务对所有文档重新构建图谱。"""
        doc1 = _make_mock_document(document_id=_DOCUMENT_ID)
        doc2 = _make_mock_document(
            document_id="660e8400-e29b-41d4-a716-446655440000"
        )
        db = _make_mock_db(documents_list=[doc1, doc2])

        store_mock = AsyncMock(return_value=_FAKE_STORE_RESULT)

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create", new=store_mock,
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
            patch.object(
                graph_tasks.rebuild_all_graphs, "update_state",
            ),
        ):
            result = graph_tasks.rebuild_all_graphs()

        # 验证 batch_create 被调用两次（每文档一次）
        assert store_mock.await_count == 2
        # 验证结果包含成功计数
        assert result["total_docs"] == 2
        assert result["success_count"] == 2
        assert result["failed_count"] == 0
        assert result["failed_docs"] == []

    def test_rebuild_all_graphs_partial_failure(self):
        """测试部分文档构建失败时仍继续处理其他文档。"""
        doc1 = _make_mock_document(document_id=_DOCUMENT_ID)
        doc2 = _make_mock_document(
            document_id="660e8400-e29b-41d4-a716-446655440000"
        )
        db = _make_mock_db(documents_list=[doc1, doc2])

        # 第一文档成功，第二文档入库失败
        store_mock = AsyncMock(
            side_effect=[_FAKE_STORE_RESULT, RuntimeError("Neo4j 入库失败")]
        )

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create", new=store_mock,
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
            patch.object(
                graph_tasks.rebuild_all_graphs, "update_state",
            ),
        ):
            result = graph_tasks.rebuild_all_graphs()

        # 验证一成功一失败
        assert result["total_docs"] == 2
        assert result["success_count"] == 1
        assert result["failed_count"] == 1
        assert len(result["failed_docs"]) == 1

    def test_rebuild_all_graphs_no_documents(self):
        """测试无已解析文档时返回空结果。"""
        db = _make_mock_db(documents_list=[])

        with _setup_session_local_patch(db):
            result = graph_tasks.rebuild_all_graphs()

        assert result["total_docs"] == 0
        assert result["success_count"] == 0
        assert result["failed_count"] == 0
        assert result["failed_docs"] == []

    def test_rebuild_all_graphs_returns_summary(self):
        """测试重建结果包含完整的统计摘要字段。"""
        doc1 = _make_mock_document(document_id=_DOCUMENT_ID)
        db = _make_mock_db(documents_list=[doc1])

        with (
            _setup_session_local_patch(db),
            patch.object(
                graph_tasks.chunker, "chunk_document",
                new=AsyncMock(return_value=_FAKE_CHUNKS),
            ),
            patch.object(
                graph_tasks.graph_extract_service, "extract_batch",
                new=AsyncMock(return_value=_EXTRACTION_RESULTS),
            ),
            patch.object(
                graph_tasks.graph_store, "batch_create",
                new=AsyncMock(return_value=_FAKE_STORE_RESULT),
            ),
            patch.object(
                graph_tasks.build_document_graph, "update_state",
            ),
            patch.object(
                graph_tasks.rebuild_all_graphs, "update_state",
            ),
        ):
            result = graph_tasks.rebuild_all_graphs()

        # 验证结果包含所有摘要字段
        assert "total_docs" in result
        assert "success_count" in result
        assert "failed_count" in result
        assert "failed_docs" in result
        assert result["total_docs"] == 1
        assert result["success_count"] == 1


# ---------------------------------------------------------------
# 3. remove_document_graph 任务测试
# ---------------------------------------------------------------
class TestRemoveDocumentGraph:
    """remove_document_graph 任务测试。"""

    def test_remove_document_graph_calls_graph_store_delete(self):
        """测试删除图谱调用 graph_store.delete_by_doc。"""
        delete_mock = AsyncMock(return_value=2)

        with patch.object(
            graph_tasks.graph_store, "delete_by_doc", new=delete_mock
        ):
            result = graph_tasks.remove_document_graph(_DOCUMENT_ID)

        # 验证 delete_by_doc 被调用
        delete_mock.assert_awaited_once_with(_DOCUMENT_ID)
        # 验证返回结果
        assert result["doc_id"] == _DOCUMENT_ID
        assert result["status"] == "removed"
        assert result["deleted"] == 2

    def test_remove_document_graph_passes_correct_doc_id(self):
        """测试删除图谱时传递正确的 doc_id。"""
        delete_mock = AsyncMock(return_value=1)
        custom_doc_id = "770e8400-e29b-41d4-a716-446655440000"

        with patch.object(
            graph_tasks.graph_store, "delete_by_doc", new=delete_mock
        ):
            graph_tasks.remove_document_graph(custom_doc_id)

        # 验证 doc_id 正确传递
        call_args = delete_mock.call_args
        assert call_args.args[0] == custom_doc_id

    def test_remove_document_graph_zero_deleted(self):
        """测试文档无图谱数据时返回 deleted=0。"""
        delete_mock = AsyncMock(return_value=0)

        with patch.object(
            graph_tasks.graph_store, "delete_by_doc", new=delete_mock
        ):
            result = graph_tasks.remove_document_graph(_DOCUMENT_ID)

        assert result["deleted"] == 0
        assert result["status"] == "removed"

    def test_remove_document_graph_failure_raises(self):
        """测试删除图谱失败时抛出异常。"""
        with patch.object(
            graph_tasks.graph_store, "delete_by_doc",
            new=AsyncMock(side_effect=RuntimeError("Neo4j 删除失败")),
        ):
            with pytest.raises(RuntimeError, match="Neo4j 删除失败"):
                graph_tasks.remove_document_graph(_DOCUMENT_ID)


# ---------------------------------------------------------------
# 4. 类型映射辅助函数测试
# ---------------------------------------------------------------
class TestTypeMapping:
    """实体/关系类型中英文映射测试。"""

    def test_map_entity_type_known(self):
        """测试已知中文实体类型映射为英文标签。"""
        assert graph_tasks._map_entity_type("材料") == "Material"
        assert graph_tasks._map_entity_type("标准") == "Standard"
        assert graph_tasks._map_entity_type("工艺") == "Process"
        assert graph_tasks._map_entity_type("参数") == "Parameter"
        assert graph_tasks._map_entity_type("组织") == "Organization"
        assert graph_tasks._map_entity_type("设备") == "Equipment"
        assert graph_tasks._map_entity_type("属性值") == "Attribute"

    def test_map_entity_type_unknown_falls_back_to_entity(self):
        """测试未知实体类型回退为 Entity。"""
        assert graph_tasks._map_entity_type("未知类型") == "Entity"
        assert graph_tasks._map_entity_type("") == "Entity"

    def test_map_entity_type_already_english(self):
        """测试已是英文标签时直接使用。"""
        assert graph_tasks._map_entity_type("Material") == "Material"
        assert graph_tasks._map_entity_type("CustomEntity") == "CustomEntity"

    def test_map_relation_type_known(self):
        """测试已知中文关系类型映射为英文关系类型。"""
        assert graph_tasks._map_relation_type("执行标准") == "EXECUTES_STANDARD"
        assert graph_tasks._map_relation_type("材质") == "MATERIAL_OF"
        assert graph_tasks._map_relation_type("用于") == "USED_FOR"
        assert graph_tasks._map_relation_type("包含") == "CONTAINS"
        assert graph_tasks._map_relation_type("参数值") == "PARAM_VALUE"
        assert graph_tasks._map_relation_type("属于") == "BELONGS_TO"
        assert graph_tasks._map_relation_type("生产于") == "PRODUCED_IN"

    def test_map_relation_type_unknown_falls_back_to_related_to(self):
        """测试未知关系类型回退为 RELATED_TO。"""
        assert graph_tasks._map_relation_type("未知关系") == "RELATED_TO"
        assert graph_tasks._map_relation_type("") == "RELATED_TO"

    def test_map_relation_type_already_english(self):
        """测试已是英文关系类型时直接使用。"""
        assert graph_tasks._map_relation_type("RELATED_TO") == "RELATED_TO"
        assert graph_tasks._map_relation_type("CUSTOM_REL") == "CUSTOM_REL"


# ---------------------------------------------------------------
# 5. _merge_and_build 辅助函数测试
# ---------------------------------------------------------------
class TestMergeAndBuild:
    """_merge_and_build 去重合并函数测试。"""

    def test_merge_deduplicates_entities_by_name_and_type(self):
        """测试按 (name, type) 去重实体。"""
        results = [
            ExtractionResult(
                entities=[
                    Entity(text="Q235", type="材料"),
                    Entity(text="GB/T700", type="标准"),
                ],
                relations=[],
            ),
            ExtractionResult(
                entities=[
                    Entity(text="Q235", type="材料"),  # 重复
                    Entity(text="Q345", type="材料"),
                ],
                relations=[],
            ),
        ]

        nodes, relations = graph_tasks._merge_and_build(results, _DOCUMENT_ID)

        # 3 个不重复实体
        assert len(nodes) == 3
        # 验证所有节点包含 doc_id
        for node in nodes:
            assert node["properties"]["doc_id"] == _DOCUMENT_ID

    def test_merge_deduplicates_relations_by_head_rel_tail(self):
        """测试按 (head, relation, tail) 去重关系。"""
        results = [
            ExtractionResult(
                entities=[
                    Entity(text="Q235", type="材料"),
                    Entity(text="GB/T700", type="标准"),
                ],
                relations=[
                    Relation(head="Q235", relation="执行标准", tail="GB/T700"),
                ],
            ),
            ExtractionResult(
                entities=[],
                relations=[
                    Relation(
                        head="Q235", relation="执行标准", tail="GB/T700",  # 重复
                    ),
                ],
            ),
        ]

        nodes, relations = graph_tasks._merge_and_build(results, _DOCUMENT_ID)

        # 1 个不重复关系
        assert len(relations) == 1
        assert relations[0]["head_name"] == "Q235"
        assert relations[0]["tail_name"] == "GB/T700"
        assert relations[0]["relation"] == "EXECUTES_STANDARD"

    def test_merge_skips_empty_entity_text(self):
        """测试空文本实体被跳过。"""
        results = [
            ExtractionResult(
                entities=[
                    Entity(text="", type="材料"),
                    Entity(text="  ", type="标准"),
                    Entity(text="Q235", type="材料"),
                ],
                relations=[],
            ),
        ]

        nodes, relations = graph_tasks._merge_and_build(results, _DOCUMENT_ID)

        # 仅 1 个有效实体
        assert len(nodes) == 1
        assert nodes[0]["properties"]["name"] == "Q235"

    def test_merge_skips_relation_with_empty_endpoints(self):
        """测试空 head 或 tail 的关系被跳过。"""
        results = [
            ExtractionResult(
                entities=[Entity(text="Q235", type="材料")],
                relations=[
                    Relation(head="", relation="执行标准", tail="GB/T700"),
                    Relation(head="Q235", relation="执行标准", tail=""),
                ],
            ),
        ]

        nodes, relations = graph_tasks._merge_and_build(results, _DOCUMENT_ID)

        # 无有效关系
        assert len(relations) == 0

    def test_merge_attaches_doc_id_to_relations(self):
        """测试关系附带 doc_id 属性。"""
        results = [
            ExtractionResult(
                entities=[
                    Entity(text="Q235", type="材料"),
                    Entity(text="GB/T700", type="标准"),
                ],
                relations=[
                    Relation(head="Q235", relation="执行标准", tail="GB/T700"),
                ],
            ),
        ]

        nodes, relations = graph_tasks._merge_and_build(results, _DOCUMENT_ID)

        assert len(relations) == 1
        assert relations[0]["properties"]["doc_id"] == _DOCUMENT_ID

    def test_merge_empty_results_returns_empty_lists(self):
        """测试空抽取结果返回空列表。"""
        nodes, relations = graph_tasks._merge_and_build([], _DOCUMENT_ID)

        assert nodes == []
        assert relations == []

    def test_merge_resolves_relation_endpoint_labels(self):
        """测试关系端点标签从已抽取实体中查找。"""
        results = [
            ExtractionResult(
                entities=[
                    Entity(text="Q235", type="材料"),
                    Entity(text="GB/T700", type="标准"),
                ],
                relations=[
                    Relation(head="Q235", relation="执行标准", tail="GB/T700"),
                ],
            ),
        ]

        nodes, relations = graph_tasks._merge_and_build(results, _DOCUMENT_ID)

        assert len(relations) == 1
        # 头实体标签应为 Material
        assert relations[0]["head_label"] == "Material"
        # 尾实体标签应为 Standard
        assert relations[0]["tail_label"] == "Standard"

    def test_merge_unknown_endpoint_label_falls_back_to_entity(self):
        """测试关系端点未在实体中出现时回退为 Entity 标签。"""
        results = [
            ExtractionResult(
                entities=[],
                relations=[
                    Relation(head="UnknownHead", relation="包含", tail="UnknownTail"),
                ],
            ),
        ]

        nodes, relations = graph_tasks._merge_and_build(results, _DOCUMENT_ID)

        assert len(relations) == 1
        # 端点未在实体中出现，回退为 Entity
        assert relations[0]["head_label"] == "Entity"
        assert relations[0]["tail_label"] == "Entity"
