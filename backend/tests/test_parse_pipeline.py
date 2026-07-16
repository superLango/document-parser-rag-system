"""文档解析管道集成测试（Phase F Task F2）。

通过 mock OCR / 版面分析 / 结构化抽取 / 术语标准化 / 对象存储 / Popo 后处理
等外部服务，验证 ``parse_document_impl`` 端到端流程的正确性：

- 文档状态从 pending 推进到 completed
- 解析文本、版面数据、结构化数据正确回写
- 任务进度更新通过数据库 Task 记录上报（mock 后不影响主流程）

由于 ``parse_document_impl`` 直接使用 ``app.tasks.document_tasks.AsyncSessionLocal``
而非 FastAPI 依赖注入，本测试通过 ``monkeypatch`` 将其替换为绑定到
SQLite 内存测试引擎的会话工厂，实现无外部 PostgreSQL 环境下的真实数据库验证。
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import BusinessException
from app.models.document import Document
from app.models.schema_model import SchemaConfig
from app.models.task import Task
from app.tasks import document_tasks


@pytest.fixture
def mock_all_services(monkeypatch):
    """mock 解析管道依赖的全部外部服务，隔离 OCR / 存储 / 模型调用。

    返回一个字典，便于各测试在需要时断言调用次数或调整返回值。
    """
    mocks = {}

    # 对象存储：下载返回伪造的图片字节
    mocks["storage_download"] = AsyncMock(
        return_value=b"fake-image-bytes"
    )
    monkeypatch.setattr(
        document_tasks.storage_service,
        "download",
        mocks["storage_download"],
    )

    # OCR 识别：返回文本与版面块
    mocks["ocr_recognize"] = AsyncMock(
        return_value={
            "text": "这是 OCR 识别出的文本内容",
            "layout": [
                {"type": "text", "bbox": [10, 10, 100, 50], "text": "OCR 文本块"},
                {"type": "title", "bbox": [10, 60, 100, 80], "text": "标题"},
            ],
            "page_size": {"width": 1240, "height": 1754},
        }
    )
    monkeypatch.setattr(
        document_tasks.ocr_service,
        "recognize_with_layout",
        mocks["ocr_recognize"],
    )

    # 版面分析：返回文本块
    mocks["layout_extract"] = AsyncMock(
        return_value=[
            {
                "type": "text",
                "bbox": [10, 10, 100, 50],
                "text": "版面文本块",
                "confidence": 0.95,
            }
        ]
    )
    monkeypatch.setattr(
        document_tasks.layout_service,
        "extract_text_blocks",
        mocks["layout_extract"],
    )

    # Popo 后处理：返回 None 表示跳过增强（保持简单）
    mocks["popo_post_process"] = AsyncMock(return_value=None)
    monkeypatch.setattr(
        document_tasks.popo_service,
        "post_process",
        mocks["popo_post_process"],
    )

    # 结构化抽取：返回伪造的字段字典
    mocks["extraction_extract"] = AsyncMock(
        return_value={"甲方": "某公司", "乙方": "另一公司", "金额": "10000"}
    )
    monkeypatch.setattr(
        document_tasks.extraction_service,
        "extract",
        mocks["extraction_extract"],
    )

    # 术语标准化：原样返回文本，无替换
    mocks["term_standardize"] = AsyncMock(
        return_value={
            "standardized_text": "这是 OCR 识别出的文本内容",
            "replacements": [],
        }
    )
    monkeypatch.setattr(
        document_tasks.term_service,
        "standardize_text",
        mocks["term_standardize"],
    )

    return mocks


@pytest.fixture
def patch_session_local(test_engine, monkeypatch):
    """将 document_tasks 中的 AsyncSessionLocal 替换为绑定测试引擎的会话工厂。

    ``parse_document_impl`` 与 ``_update_progress`` 通过
    ``async with AsyncSessionLocal() as db`` 直接获取会话，
    因此必须替换该模块级引用才能接入 SQLite 测试库。
    """
    test_session_factory = async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr(
        document_tasks, "AsyncSessionLocal", test_session_factory
    )
    return test_session_factory


class TestParseDocumentPipeline:
    """parse_document_impl 集成测试。"""

    @pytest.mark.asyncio
    async def test_full_pipeline_without_schema(
        self, db_session, patch_session_local, mock_all_services
    ):
        """无 schema_id 时应完成全流程，回写 parsed_text 与 layout_data。

        覆盖阶段：下载 -> OCR -> 版面分析 -> Popo -> 跳过抽取 -> 术语标准化 -> 保存。
        """
        # 准备：在测试库中创建一条 pending 文档
        doc = Document(
            filename="sample.pdf",
            file_size=2048,
            file_type="pdf",
            status="pending",
            minio_object_name="obj-sample.pdf",
        )
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        doc_id = str(doc.id)

        # 执行解析管道（无 schema_id、无 term_base_id）
        ctx = {"job_id": None}
        result = await document_tasks.parse_document_impl(
            document_id=doc_id,
            schema_id=None,
            term_base_id=None,
            ctx=ctx,
        )

        # 断言返回结果
        assert result["status"] == "completed"
        assert result["document_id"] == doc_id
        assert result["parsed_text_length"] > 0
        assert result["structured_fields"] == 0

        # 断言外部服务被调用
        mock_all_services["storage_download"].assert_awaited_once_with(
            "obj-sample.pdf"
        )
        mock_all_services["ocr_recognize"].assert_awaited_once()
        mock_all_services["layout_extract"].assert_awaited_once()
        # 无 schema_id 时不应调用结构化抽取
        mock_all_services["extraction_extract"].assert_not_awaited()
        # 术语标准化应被调用
        mock_all_services["term_standardize"].assert_awaited_once()

        # 断言数据库中文档状态与字段已更新
        await db_session.refresh(doc)
        assert doc.status == "completed"
        assert doc.parsed_text is not None
        assert len(doc.parsed_text) > 0
        assert doc.structured_data is None
        assert doc.layout_data is not None
        assert "ocr_layout" in doc.layout_data
        assert "text_blocks" in doc.layout_data
        assert "merged" in doc.layout_data
        # 合并后的版面块数应 >= 1
        assert len(doc.layout_data["merged"]) >= 1

    @pytest.mark.asyncio
    async def test_full_pipeline_with_schema(
        self, db_session, patch_session_local, mock_all_services
    ):
        """带 schema_id 时应执行结构化抽取并回写 structured_data。"""
        # 准备：创建 SchemaConfig 与 pending 文档
        schema = SchemaConfig(
            name="合同Schema",
            schema_definition=[
                {"name": "甲方", "type": "string"},
                {"name": "金额", "type": "number"},
            ],
            is_template=False,
        )
        db_session.add(schema)
        doc = Document(
            filename="contract.pdf",
            file_size=4096,
            file_type="pdf",
            status="pending",
            minio_object_name="obj-contract.pdf",
        )
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(schema)
        await db_session.refresh(doc)

        # 执行解析管道（带 schema_id）
        result = await document_tasks.parse_document_impl(
            document_id=str(doc.id),
            schema_id=str(schema.id),
            term_base_id=None,
            ctx={"job_id": None},
        )

        # 断言返回结果
        assert result["status"] == "completed"
        assert result["structured_fields"] == 3  # 甲方/乙方/金额

        # 结构化抽取应被调用一次
        mock_all_services["extraction_extract"].assert_awaited_once()

        # 断言数据库中文档结构化数据已回写
        await db_session.refresh(doc)
        assert doc.status == "completed"
        assert doc.structured_data is not None
        assert doc.structured_data["甲方"] == "某公司"
        assert doc.structured_data["金额"] == "10000"

    @pytest.mark.asyncio
    async def test_pipeline_document_not_found_raises(
        self, patch_session_local, mock_all_services
    ):
        """不存在的文档 ID 应抛出 BusinessException。"""
        fake_id = str(uuid.uuid4())
        with pytest.raises(BusinessException):
            await document_tasks.parse_document_impl(
                document_id=fake_id,
                schema_id=None,
                term_base_id=None,
                ctx={"job_id": None},
            )
        # 文档不存在时应在调用存储下载前即失败
        mock_all_services["storage_download"].assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pipeline_progress_updates_with_task_id(
        self, db_session, patch_session_local, mock_all_services
    ):
        """提供 job_id 时应更新数据库中的 Task 记录进度。"""
        # 准备：创建文档与对应的 Task 记录（document_id 为非空外键）
        doc = Document(
            filename="progress.pdf",
            file_size=1024,
            file_type="pdf",
            status="pending",
            minio_object_name="obj-progress.pdf",
        )
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        task = Task(
            id="task-progress-001",
            document_id=doc.id,
            status="pending",
            progress=0,
        )
        db_session.add(task)
        await db_session.commit()

        # 执行解析管道，传入 job_id
        result = await document_tasks.parse_document_impl(
            document_id=str(doc.id),
            schema_id=None,
            term_base_id=None,
            ctx={"job_id": "task-progress-001"},
        )
        assert result["status"] == "completed"

        # 断言 Task 记录进度已更新为 100
        await db_session.refresh(task)
        assert task.progress == 100
        assert task.status == "progress"
