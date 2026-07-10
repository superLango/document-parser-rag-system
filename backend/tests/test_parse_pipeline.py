"""文档解析流水线测试模块。

测试 parse_document Celery 任务的完整执行流程：
- 成功路径：下载 -> OCR -> 版面分析 -> 结构化抽取 -> 术语标准化 -> 入库
- 错误路径：OCR 失败时 Document 状态置为 failed

所有外部依赖（MinIO / OCR 模型 / LLM / 数据库 / 术语库）均通过 mock 隔离，
确保无 GPU / 无模型 / 无数据库环境下可运行。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.document import Document
from app.models.schema_model import SchemaConfig
from app.tasks import document_tasks


# ---------------------------------------------------------------
# 测试常量
# ---------------------------------------------------------------
_DOCUMENT_ID = "550e8400-e29b-41d4-a716-446655440000"
_SCHEMA_ID = "660e8400-e29b-41d4-a716-446655440000"

_FAKE_PDF_BYTES = b"%PDF-1.4 fake pdf content for testing"

_OCR_RESULT = {
    "text": "测试文本内容",
    "layout": [
        {
            "type": "text",
            "bbox": [0, 0, 100, 100],
            "text": "测试文本内容",
        }
    ],
    "pages": 1,
}

_TEXT_BLOCKS = [
    {
        "type": "text",
        "text": "测试文本内容",
        "bbox": [0, 0, 100, 100],
        "confidence": 0.95,
    }
]

_EXTRACTED_DATA = {"材料名称": "不锈钢"}

_STANDARDIZE_RESULT = {
    "original_text": "测试文本内容",
    "standardized_text": "测试文本内容",
    "replacements": [],
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
    status: str = "pending",
    minio_object_name: str = "documents/test.pdf",
):
    """创建模拟 Document 对象。

    使用 MagicMock 以支持属性赋值与状态追踪。
    """
    doc = MagicMock(spec=Document)
    doc.id = uuid.UUID(document_id)
    doc.status = status
    doc.minio_object_name = minio_object_name
    doc.filename = "test.pdf"
    doc.file_size = 1024
    doc.file_type = "pdf"
    doc.parsed_text = None
    doc.structured_data = None
    doc.layout_data = None
    return doc


def _make_mock_schema_config(schema_id: str = _SCHEMA_ID):
    """创建模拟 SchemaConfig 对象。"""
    config = MagicMock(spec=SchemaConfig)
    config.id = uuid.UUID(schema_id)
    config.schema_definition = {
        "fields": [
            {
                "name": "材料名称",
                "type": "string",
                "required": True,
                "description": "材料的标准名称",
            }
        ]
    }
    return config


def _make_mock_db(document=None, schema_config=None):
    """创建 mock AsyncSession。

    配置 db.get 按 (Model, uuid) 参数返回不同的 mock 对象，
    支持 Document 与 SchemaConfig 两种查询。

    Args:
        document: 首次 get(Document, ...) 时返回的文档对象。
        schema_config: get(SchemaConfig, ...) 时返回的配置对象。

    Returns:
        MagicMock: 模拟的异步会话。
    """
    db = MagicMock()

    async def _mock_get(model, obj_id, **kwargs):
        if model is Document:
            return document
        if model is SchemaConfig:
            return schema_config
        return None

    db.get = AsyncMock(side_effect=_mock_get)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())

    return db


def _setup_session_local_patch(db_mock):
    """构造 AsyncSessionLocal 的 patcher。

    使得 ``async with AsyncSessionLocal() as db:`` 返回 db_mock。
    """
    mock_session_local = MagicMock(return_value=_MockAsyncSessionContext(db_mock))
    return patch.object(document_tasks, "AsyncSessionLocal", mock_session_local)


# ---------------------------------------------------------------
# 成功路径测试
# ---------------------------------------------------------------
class TestParseDocumentSuccess:
    """parse_document 任务成功路径测试。"""

    def test_parse_document_calls_all_services_in_order(self):
        """测试任务按正确顺序调用所有服务。

        验证调用序列：storage.download -> ocr.recognize_with_layout
        -> layout.extract_text_blocks -> extraction.extract
        -> term.standardize_text。
        """
        doc = _make_mock_document()
        schema = _make_mock_schema_config()
        db = _make_mock_db(document=doc, schema_config=schema)

        call_order = []

        async def _track_download(*args, **kwargs):
            call_order.append("storage_download")
            return _FAKE_PDF_BYTES

        async def _track_ocr(*args, **kwargs):
            call_order.append("ocr_recognize")
            return _OCR_RESULT

        async def _track_layout(*args, **kwargs):
            call_order.append("layout_extract")
            return _TEXT_BLOCKS

        async def _track_extract(*args, **kwargs):
            call_order.append("extraction_extract")
            return _EXTRACTED_DATA

        async def _track_standardize(*args, **kwargs):
            call_order.append("term_standardize")
            return _STANDARDIZE_RESULT

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(side_effect=_track_download),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(side_effect=_track_ocr),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(side_effect=_track_layout),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(side_effect=_track_extract),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(side_effect=_track_standardize),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            result = document_tasks.parse_document(
                _DOCUMENT_ID, schema_id=_SCHEMA_ID
            )

        # 验证服务调用顺序正确
        assert call_order == [
            "storage_download",
            "ocr_recognize",
            "layout_extract",
            "extraction_extract",
            "term_standardize",
        ]

        # 验证返回结果包含文档 ID
        assert isinstance(result, dict)
        assert result["document_id"] == _DOCUMENT_ID
        assert result["status"] == "completed"

    def test_parse_document_sets_status_completed(self):
        """测试任务完成后 Document 状态为 completed。"""
        doc = _make_mock_document()
        schema = _make_mock_schema_config()
        db = _make_mock_db(document=doc, schema_config=schema)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(return_value=_OCR_RESULT),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(return_value=_EXTRACTED_DATA),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            document_tasks.parse_document(_DOCUMENT_ID, schema_id=_SCHEMA_ID)

        # 验证文档状态最终为 completed
        assert doc.status == "completed"

    def test_parse_document_progress_updates(self):
        """测试任务进度按序列上报。

        验证 update_state 被调用时的 progress 值序列为：
        10 -> 20 -> 40 -> 60 -> 80 -> 90 -> 100。
        """
        doc = _make_mock_document()
        schema = _make_mock_schema_config()
        db = _make_mock_db(document=doc, schema_config=schema)

        update_state_mock = MagicMock()

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(return_value=_OCR_RESULT),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(return_value=_EXTRACTED_DATA),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
                new=update_state_mock,
            ),
        ):
            document_tasks.parse_document(_DOCUMENT_ID, schema_id=_SCHEMA_ID)

        # 提取所有 PROGRESS 状态的 progress 值
        progress_values = []
        for call in update_state_mock.call_args_list:
            args, kwargs = call
            if kwargs.get("state") == "PROGRESS":
                meta = kwargs.get("meta", {})
                if "progress" in meta:
                    progress_values.append(meta["progress"])

        # 验证进度序列包含所有预期值
        assert 10 in progress_values  # 初始
        assert 20 in progress_values  # OCR
        assert 40 in progress_values  # 版面分析
        assert 60 in progress_values  # 结构化抽取
        assert 80 in progress_values  # 术语标准化
        assert 90 in progress_values  # 保存
        assert 100 in progress_values  # 完成

    def test_parse_document_without_schema_id(self):
        """测试不提供 schema_id 时跳过结构化抽取。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc, schema_config=None)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(return_value=_OCR_RESULT),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(return_value=_EXTRACTED_DATA),
            ) as extract_mock,
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            result = document_tasks.parse_document(
                _DOCUMENT_ID, schema_id=None
            )

        # 未提供 schema_id 时不应调用结构化抽取
        extract_mock.assert_not_awaited()
        # 但任务仍应成功完成
        assert result["status"] == "completed"
        assert doc.status == "completed"

    def test_parse_document_writes_parsed_text(self):
        """测试解析文本被写入 Document.parsed_text。"""
        doc = _make_mock_document()
        schema = _make_mock_schema_config()
        db = _make_mock_db(document=doc, schema_config=schema)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(return_value=_OCR_RESULT),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(return_value=_EXTRACTED_DATA),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            document_tasks.parse_document(_DOCUMENT_ID, schema_id=_SCHEMA_ID)

        # 验证解析文本被写入
        assert doc.parsed_text == "测试文本内容"

    def test_parse_document_writes_structured_data(self):
        """测试结构化数据被写入 Document.structured_data。"""
        doc = _make_mock_document()
        schema = _make_mock_schema_config()
        db = _make_mock_db(document=doc, schema_config=schema)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(return_value=_OCR_RESULT),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(return_value=_EXTRACTED_DATA),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            document_tasks.parse_document(_DOCUMENT_ID, schema_id=_SCHEMA_ID)

        assert doc.structured_data == _EXTRACTED_DATA

    def test_parse_document_writes_layout_data(self):
        """测试版面数据被写入 Document.layout_data。"""
        doc = _make_mock_document()
        schema = _make_mock_schema_config()
        db = _make_mock_db(document=doc, schema_config=schema)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(return_value=_OCR_RESULT),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(return_value=_EXTRACTED_DATA),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            document_tasks.parse_document(_DOCUMENT_ID, schema_id=_SCHEMA_ID)

        # 验证版面数据被写入
        assert doc.layout_data is not None
        assert "ocr_layout" in doc.layout_data
        assert "text_blocks" in doc.layout_data

    def test_parse_document_calls_db_commit(self):
        """测试任务完成后调用了 db.commit。"""
        doc = _make_mock_document()
        schema = _make_mock_schema_config()
        db = _make_mock_db(document=doc, schema_config=schema)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(return_value=_OCR_RESULT),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(return_value=_EXTRACTED_DATA),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            document_tasks.parse_document(_DOCUMENT_ID, schema_id=_SCHEMA_ID)

        # 验证 commit 被调用至少两次：processing 标记 + 最终保存
        assert db.commit.await_count >= 2


# ---------------------------------------------------------------
# 错误路径测试
# ---------------------------------------------------------------
class TestParseDocumentFailure:
    """parse_document 任务错误路径测试。"""

    def test_ocr_failure_sets_document_failed(self):
        """测试 OCR 失败时 Document 状态被置为 failed。

        Mock ocr_service.recognize_with_layout 抛出异常，
        验证文档状态被回写为 failed 且任务抛出异常。
        """
        doc = _make_mock_document()
        db = _make_mock_db(document=doc, schema_config=None)

        ocr_error = RuntimeError("OCR 模型推理失败")

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(side_effect=ocr_error),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(return_value=_EXTRACTED_DATA),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            # 任务应抛出异常
            with pytest.raises(RuntimeError, match="OCR 模型推理失败"):
                document_tasks.parse_document(_DOCUMENT_ID, schema_id=None)

        # 验证文档状态被置为 failed
        assert doc.status == "failed"

    def test_ocr_failure_calls_rollback(self):
        """测试 OCR 失败时调用了 db.rollback。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc, schema_config=None)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(side_effect=RuntimeError("OCR 失败")),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            with pytest.raises(RuntimeError):
                document_tasks.parse_document(_DOCUMENT_ID, schema_id=None)

        # 验证 rollback 被调用
        db.rollback.assert_awaited()

    def test_ocr_failure_sets_failure_state(self):
        """测试 OCR 失败时任务状态被置为 FAILURE。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc, schema_config=None)

        update_state_mock = MagicMock()

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(side_effect=RuntimeError("OCR 失败")),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
                new=update_state_mock,
            ),
        ):
            with pytest.raises(RuntimeError):
                document_tasks.parse_document(_DOCUMENT_ID, schema_id=None)

        # 验证 update_state 被调用且至少一次 state 为 FAILURE
        failure_calls = [
            call for call in update_state_mock.call_args_list
            if call.kwargs.get("state") == "FAILURE"
        ]
        assert len(failure_calls) >= 1

    def test_storage_download_failure_sets_document_failed(self):
        """测试下载失败时 Document 状态被置为 failed。"""
        doc = _make_mock_document()
        db = _make_mock_db(document=doc, schema_config=None)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(side_effect=RuntimeError("MinIO 下载失败")),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            with pytest.raises(RuntimeError, match="MinIO 下载失败"):
                document_tasks.parse_document(_DOCUMENT_ID, schema_id=None)

        assert doc.status == "failed"

    def test_extraction_failure_sets_document_failed(self):
        """测试结构化抽取失败时 Document 状态被置为 failed。"""
        doc = _make_mock_document()
        schema = _make_mock_schema_config()
        db = _make_mock_db(document=doc, schema_config=schema)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.storage_service, "download",
                new=AsyncMock(return_value=_FAKE_PDF_BYTES),
            ),
            patch.object(
                document_tasks.ocr_service, "recognize_with_layout",
                new=AsyncMock(return_value=_OCR_RESULT),
            ),
            patch.object(
                document_tasks.layout_service, "extract_text_blocks",
                new=AsyncMock(return_value=_TEXT_BLOCKS),
            ),
            patch.object(
                document_tasks.extraction_service, "extract",
                new=AsyncMock(side_effect=RuntimeError("抽取失败")),
            ),
            patch.object(
                document_tasks.term_service, "standardize_text",
                new=AsyncMock(return_value=_STANDARDIZE_RESULT),
            ),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            with pytest.raises(RuntimeError, match="抽取失败"):
                document_tasks.parse_document(_DOCUMENT_ID, schema_id=_SCHEMA_ID)

        assert doc.status == "failed"

    def test_document_not_found_raises(self):
        """测试文档不存在时抛出异常。"""
        # mock db.get 返回 None（文档不存在）
        db = _make_mock_db(document=None, schema_config=None)

        with (
            _setup_session_local_patch(db),
            patch.object(
                document_tasks.parse_document, "update_state",
            ),
        ):
            with pytest.raises(Exception) as exc_info:
                document_tasks.parse_document(_DOCUMENT_ID, schema_id=None)

            # 应抛出包含"文档不存在"的异常
            assert "不存在" in str(exc_info.value) or "文档" in str(exc_info.value)
