"""Phase 4 抽取器抽象基类。

定义双线路 LLM 抽取器的统一接口：
- ``extract``：从 RetrievalContext 抽取记录
- ``_engine_name``：引擎名（glmocr / langextract）

子类需实现 ``extract`` 方法，返回 ``list[ExtractedRecord]``。

并发控制：
- ``_llm_semaphore``：LLM 调用总并发信号量（由 Pipeline 注入，全局共享）
- 子类在调用 LLM 前需 ``async with self._llm_semaphore``
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    ExtractedRecord,
    RetrievalContext,
)

logger = get_logger(__name__)


class BaseExtractor(abc.ABC):
    """抽取器抽象基类。

    Attributes:
        _engine_name: 引擎名（glmocr / langextract）。
        _llm_semaphore: LLM 调用总并发信号量（由 Pipeline 注入）。
    """

    _engine_name: str = "base"

    def __init__(self, llm_semaphore: asyncio.Semaphore | None = None) -> None:
        """初始化抽取器。

        Args:
            llm_semaphore: LLM 调用总并发信号量（由 Pipeline 注入）。
        """
        self._llm_semaphore = llm_semaphore or asyncio.Semaphore(24)

    @abc.abstractmethod
    async def extract(
        self,
        context: RetrievalContext,
        schema: dict[str, Any],
        target: ExtractionTarget,
    ) -> list[ExtractedRecord]:
        """从检索上下文抽取记录（子类实现）。

        Args:
            context: 检索上下文（含拼接文本和白名单）。
            schema: 该 feature 的 schema 定义。
            target: 抽取目标（含 items/methods）。

        Returns:
            list[ExtractedRecord]: 抽取的记录列表。
        """
        ...

    @property
    def engine_name(self) -> str:
        """引擎名。"""
        return self._engine_name

    # ------------------------------------------------------------------
    # 通用辅助方法
    # ------------------------------------------------------------------

    def _parse_records(
        self,
        data: Any,
        schema: dict[str, Any],
        target: ExtractionTarget,
    ) -> list[ExtractedRecord]:
        """将 LLM 输出的 JSON 数据转为 ExtractedRecord 列表。

        处理两种输出格式：
        - dict（schema.result.type="object"）：包装为单条记录
        - list[dict]（schema.result.type="array"）：每项为一条记录

        Args:
            data: LLM 输出的 JSON 数据（dict 或 list）。
            schema: schema 定义。
            target: 抽取目标。

        Returns:
            list[ExtractedRecord]: 抽取记录列表。
        """
        records: list[ExtractedRecord] = []

        if isinstance(data, dict):
            # 单条记录（object 类型）
            records.append(self._to_record(data, target))
        elif isinstance(data, list):
            # 多条记录（array 类型）
            for item in data:
                if isinstance(item, dict):
                    records.append(self._to_record(item, target))

        logger.info(
            "记录解析完成",
            extra={
                "engine": self._engine_name,
                "feature": target.feature,
                "record_count": len(records),
            },
        )
        return records

    @staticmethod
    def _to_record(
        data: dict[str, Any],
        target: ExtractionTarget,
    ) -> ExtractedRecord:
        """将单个 dict 转为 ExtractedRecord。

        过滤掉 schema 未定义的字段（防止 LLM 输出多余字段）。

        Args:
            data: 单条记录字典。
            target: 抽取目标。

        Returns:
            ExtractedRecord: 抽取记录。
        """
        # 保留所有字段（后处理阶段统一过滤）
        return ExtractedRecord(
            feature=target.feature,
            data=dict(data),
        )
