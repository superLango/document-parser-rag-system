"""抽取器工厂（引擎切换 + 降级）。

根据配置选择抽取引擎（glmocr / langextract），支持 LangExtract 失败时
降级到 glmocr。

使用示例::

    from app.services.extraction.llm_extract.extractor_factory import get_extractor

    extractor = get_extractor(llm_semaphore=sem)
    records = await extractor.extract(context, schema, target)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    ExtractedRecord,
    RetrievalContext,
)
from app.services.extraction.llm_extract.extractor_base import BaseExtractor
from app.services.extraction.llm_extract.glmocr_extractor import GlmOcrExtractor
from app.services.extraction.llm_extract.langextract_extractor import LangExtractExtractor

logger = get_logger(__name__)


def get_extractor(
    llm_semaphore: asyncio.Semaphore | None = None,
    engine: str | None = None,
) -> BaseExtractor:
    """获取抽取器实例。

    Args:
        llm_semaphore: LLM 调用总并发信号量。
        engine: 引擎名（glmocr / langextract），None 时使用配置项。

    Returns:
        BaseExtractor: 抽取器实例。
    """
    settings = get_extraction_settings()
    _engine = engine or settings.extraction_engine

    if _engine == "langextract":
        return LangExtractExtractor(llm_semaphore=llm_semaphore)
    return GlmOcrExtractor(llm_semaphore=llm_semaphore)


async def extract_with_fallback(
    context: RetrievalContext,
    schema: dict[str, Any],
    target: ExtractionTarget,
    llm_semaphore: asyncio.Semaphore | None = None,
    engine: str | None = None,
) -> list[ExtractedRecord]:
    """抽取入口（不降级，空结果直接剔除该类别）。

    LangExtract 线路返回空结果或异常时，**不降级到 glmocr**，直接返回空列表。
    空类别由 pipeline 层剔除（records=0 且 rejected=0）。
    这样避免双重 LLM 调用浪费时间和 token。

    Args:
        context: 检索上下文。
        schema: schema 定义。
        target: 抽取目标。
        llm_semaphore: LLM 调用总并发信号量。
        engine: 引擎名，None 时使用配置项。

    Returns:
        list[ExtractedRecord]: 抽取记录列表（可能为空）。
    """
    settings = get_extraction_settings()
    _engine = engine or settings.extraction_engine

    extractor = get_extractor(llm_semaphore=llm_semaphore, engine=_engine)

    try:
        records = await extractor.extract(context, schema, target)
        if not records:
            logger.info(
                "抽取返回空结果，直接剔除该类别",
                extra={"engine": _engine, "feature": target.feature},
            )
        return records

    except Exception as err:
        logger.error(
            "抽取失败，返回空结果",
            extra={
                "engine": _engine,
                "feature": target.feature,
                "error": str(err),
            },
        )
        return []
