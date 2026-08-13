"""L1 单元：E1 数据与任务底座（模型注册/常量/流水线占位）。"""

import pytest
from app.core.exceptions import BusinessException
from app.models.document import Document
from app.models.extraction import ExtractionHistory, ExtractionResult
from app.services.extraction import pipeline
from app.services.extraction.result_store import HISTORY_LIMIT


async def test_models_registered():
    """L1E1-01：抽取结果/历史模型与文档抽取状态列已注册。"""
    assert ExtractionResult.__tablename__ == "extraction_results"
    assert ExtractionHistory.__tablename__ == "extraction_history"
    assert hasattr(Document, "extraction_status")


async def test_history_limit_constant():
    """L1E1-02：历史保留上限为 50。"""
    assert HISTORY_LIMIT == 50


async def test_pipeline_stub_raises():
    """L1E1-03：E1 流水线占位明确报错（防止伪成功）。"""
    with pytest.raises(BusinessException, match="E3"):
        await pipeline.run(kb_id="kb", document_id="doc")
