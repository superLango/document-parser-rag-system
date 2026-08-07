"""抽取器工厂（引擎切换 + 降级）。

根据配置选择抽取引擎（BaseExtract / LangExtract），支持 LangExtract 失败时
降级到 BaseExtract。

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
from app.core.exceptions import BusinessException
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    ExtractedRecord,
    RetrievalContext,
)
from app.services.extraction.llm_extract.extractor_base import BaseExtractor
from app.services.extraction.llm_extract.base_extract_extractor import BaseExtractExtractor
from app.services.extraction.llm_extract.langextract_extractor import LangExtractExtractor
from app.services.extraction_config.defaults import ENGINE_LANG_EXTRACT

logger = get_logger(__name__)


def get_extractor(
    llm_semaphore: asyncio.Semaphore | None = None,
    engine: str | None = None,
) -> BaseExtractor:
    """获取抽取器实例。

    Args:
        llm_semaphore: LLM 调用总并发信号量。
        engine: 引擎名（BaseExtract / LangExtract），None 时使用配置项。

    Returns:
        BaseExtractor: 抽取器实例。
    """
    if engine is None:
        raise BusinessException("未指定抽取引擎（engine），请配置 llm.engine")
    _engine = engine

    if _engine == ENGINE_LANG_EXTRACT:
        return LangExtractExtractor(llm_semaphore=llm_semaphore)
    return BaseExtractExtractor(llm_semaphore=llm_semaphore)


async def extract_with_fallback(
    context: RetrievalContext,
    schema: dict[str, Any],
    target: ExtractionTarget,
    llm_semaphore: asyncio.Semaphore | None = None,
    engine: str | None = None,
    cfg: Any = None,
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
        cfg: 抽取领域配置（Prompt 模板 / LLM 参数）。

    Returns:
        list[ExtractedRecord]: 抽取记录列表（可能为空）。
    """
    # 引擎优先级：显式参数 > 配置驱动（cfg.llm.engine），缺失即报错（无 settings 兜底）
    _engine = engine
    if _engine is None:
        if cfg is None:
            raise BusinessException("未指定抽取引擎且缺少抽取配置（cfg）")
        _engine = cfg.llm_engine()

    extractor = get_extractor(llm_semaphore=llm_semaphore, engine=_engine)

    try:
        records = await extractor.extract(context, schema, target, cfg)
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
