"""BaseExtract 抽取器（线路 B）。

移植自 glm-ocr simple_pipeline，增强文本预处理逻辑：
- 短文本（< 8000 字符）：单次 LLM 调用，完整上下文
- 长文本（≥ 8000 字符）：表格边界感知分批，**全批次并行**压入 vLLM 等待队列
- LLM 参数：temperature=0.0, top_p=0.1, max_tokens=32768, enable_thinking=False
- JSON 解析三级容错（复用 llm_client.parse_json）
- 后处理：字段名过滤 + 去重

并发模型（**全并行**）：
- 类别间并发：所有 feature 通过 ``asyncio.gather`` 并发（Pipeline 层控制）
- 类别内并发：长文本的所有批次通过 ``asyncio.gather`` 并发提交
- LLM 调用总并发由 ``_llm_semaphore`` 控制（默认 24）
- 所有请求压入 vLLM 等待队列，vLLM 按 ``max-num-seqs`` 自动批处理
- 牌号传递在并行模式下不可行，改为后处理阶段统一去重

使用示例::

    from app.services.extraction.llm_extract.base_extract_extractor import BaseExtractExtractor

    extractor = BaseExtractExtractor(llm_semaphore=sem)
    records = await extractor.extract(context, schema, target)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.logging import get_logger
from app.core.exceptions import BusinessException
from app.services.extraction.llm_client import llm_client
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    ExtractedRecord,
    RetrievalContext,
)
from app.services.extraction.llm_extract.batch_processor import batch_processor
from app.services.extraction.llm_extract.extractor_base import BaseExtractor
from app.services.extraction.prompts.config_prompt_renderer import config_prompt_renderer

logger = get_logger(__name__)


class BaseExtractExtractor(BaseExtractor):
    """线路 B：BaseExtract 直抽（glm-ocr simple_pipeline 风格）。

    短文本单次调用 / 长文本分批串行（牌号传递）。
    """

    _engine_name = "BaseExtract"

    def __init__(self, llm_semaphore: asyncio.Semaphore | None = None) -> None:
        super().__init__(llm_semaphore)

    async def extract(
        self,
        context: RetrievalContext,
        schema: dict[str, Any],
        target: ExtractionTarget,
        cfg: Any = None,
    ) -> list[ExtractedRecord]:
        """从检索上下文抽取记录（glmocr 线路）。

        Args:
            context: 检索上下文（含拼接文本和白名单）。
            schema: 该 feature 的 schema 定义。
            target: 抽取目标。
            cfg: 抽取领域配置（Prompt 模板 / LLM 参数）。

        Returns:
            list[ExtractedRecord]: 抽取的记录列表。
        """
        if not context.text:
            logger.warning("上下文为空，跳过抽取", extra={"feature": target.feature})
            return []

        # 文本预处理：短文本单次 / 长文本分批（批处理参数走配置，缺失即报错）
        _batch = self._require_batch(cfg)
        batches = batch_processor.split(
            context.text,
            threshold=_batch["single_threshold"],
            batch_chars=_batch["batch_chars"],
            overlap=_batch["overlap"],
        )

        if len(batches) <= 1:
            # 短文本：单次 LLM 调用
            return await self._extract_single(
                batches[0] if batches else "",
                schema,
                target,
                context.whitelist_prompt,
                cfg=cfg,
            )
        else:
            # 长文本：分批串行（牌号传递）
            return await self._extract_batched(batches, schema, target, context.whitelist_prompt, cfg)

    def _require_batch(self, cfg: Any = None) -> dict:
        """校验 BaseExtract 批处理参数齐全并返回（缺失即报错，无硬编码回退）。"""
        _batch = cfg.llm_batch() if cfg is not None else {}
        _missing = [
            k for k in ("single_threshold", "batch_chars", "overlap", "context_truncate")
            if _batch.get(k) is None
        ]
        if _missing:
            raise BusinessException(
                f"未配置 BaseExtract 批处理参数 llm.engines.BaseExtract.batch.{'、'.join(_missing)}"
            )
        return _batch

    async def _extract_single(
        self,
        text: str,
        schema: dict[str, Any],
        target: ExtractionTarget,
        whitelist: str,
        prev_brands: list[str] | None = None,
        cfg: Any = None,
    ) -> list[ExtractedRecord]:
        """单次 LLM 抽取（短文本或单批）。

        Args:
            text: 待抽取文本（截断到 glmocr_context_truncate）。
            schema: schema 定义。
            target: 抽取目标。
            whitelist: 白名单 prompt。
            prev_brands: 前批抽取的牌号（跨批传递）。
            cfg: 抽取领域配置。

        Returns:
            list[ExtractedRecord]: 抽取记录列表。
        """
        # 截断保护（批处理参数走配置，缺失即报错）
        _batch = self._require_batch(cfg)
        _truncate = _batch["context_truncate"]
        truncated_text = text[:_truncate]

        # 构建 prompt
        system_prompt, user_prompt = self._build_prompt(
            target, schema, truncated_text, whitelist, prev_brands, cfg
        )

        # 未配置类别 Prompt 模板时跳过（prompt 全程走配置，不降级到内置 prompt）
        if not user_prompt:
            logger.warning(
                "类别无 Prompt 模板，跳过抽取",
                extra={"feature": target.feature},
            )
            return []

        # 调用 LLM（受 _llm_semaphore 控制，LLM 参数走引擎分组配置）
        _engine_params = cfg.engine_params() if cfg is not None else {}
        # 类别级 max_tokens 覆盖引擎分组（类别参数回退全局，不允许 env 兜底）
        _max_tokens = target.max_tokens or (cfg.max_output_tokens() if cfg is not None else None)
        _temperature = cfg.engine_temperature() if cfg is not None else None
        _endpoint = cfg.endpoint if cfg is not None else {}
        async with self._llm_semaphore:
            try:
                result_data = await llm_client.chat_json(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=_max_tokens,
                    temperature=_temperature,
                    endpoint=_endpoint,
                    engine_params=_engine_params,
                )
            except Exception as err:
                logger.error(
                    "glmocr LLM 调用失败",
                    extra={"feature": target.feature, "error": str(err)},
                )
                return []

        # 调试日志：记录 LLM 返回数据
        logger.info(
            "LLM 返回数据",
            extra={
                "feature": target.feature,
                "data_type": type(result_data).__name__,
                "data_len": len(result_data) if isinstance(result_data, list) else 1,
                "data_preview": str(result_data)[:500],
            },
        )

        # 解析记录
        records = self._parse_records(result_data, schema, target)

        logger.info(
            "glmocr 单次抽取完成",
            extra={
                "feature": target.feature,
                "text_len": len(text),
                "records": len(records),
            },
        )
        return records

    async def _extract_batched(
        self,
        batches: list[str],
        schema: dict[str, Any],
        target: ExtractionTarget,
        whitelist: str,
        cfg: Any = None,
    ) -> list[ExtractedRecord]:
        """分批**并行**抽取（长文本，全批次同时压入 vLLM 等待队列）。

        所有批次通过 ``asyncio.gather`` 并发提交，每个批次独立调用 LLM，
        由全局 ``llm_semaphore`` 控制并发上限，vLLM 自动排队批处理。

        牌号传递在并行模式下不可行，改为后处理阶段统一去重
        （``post_processor`` 的 ``_dedup`` 逻辑）。

        Args:
            batches: 批次列表。
            schema: schema 定义。
            target: 抽取目标。
            whitelist: 白名单 prompt。
            cfg: 抽取领域配置。

        Returns:
            list[ExtractedRecord]: 合并后的抽取记录列表。
        """
        # 所有批次并行提交（prev_brands=None，不传递牌号）
        tasks = [
            self._extract_single(batch_text, schema, target, whitelist, None, cfg)
            for batch_text in batches
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并结果
        all_records: list[ExtractedRecord] = []
        for batch_idx, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.error(
                    "批次抽取异常",
                    extra={
                        "feature": target.feature,
                        "batch_idx": batch_idx + 1,
                        "error": str(result),
                    },
                )
                continue
            all_records.extend(result)
            logger.debug(
                "批次抽取完成",
                extra={
                    "feature": target.feature,
                    "batch_idx": batch_idx + 1,
                    "total_batches": len(batches),
                    "batch_records": len(result),
                },
            )

        logger.info(
            "glmocr 分批抽取完成",
            extra={
                "feature": target.feature,
                "batch_count": len(batches),
                "total_records": len(all_records),
            },
        )
        return all_records

    def _build_prompt(
        self,
        target: ExtractionTarget,
        schema: dict[str, Any],
        context: str,
        whitelist: str,
        prev_brands: list[str] | None,
        cfg: Any = None,
    ) -> tuple[str, str]:
        """构建抽取 prompt（配置驱动，不再读内置 YAML）。

        Args:
            target: 抽取目标。
            schema: schema 定义。
            context: 文档上下文。
            whitelist: 白名单 prompt。
            prev_brands: 前批牌号列表。
            cfg: 抽取领域配置。

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        # 字段定义文本（从 target.fields 构建）
        field_defs = config_prompt_renderer.build_field_defs(target)

        # 输出格式说明由 Schema 模板 return_type 声明，不再写死；
        # Prompt 模板通过 ${format_instruction} 占位符自行引用格式要求
        format_instruction = ""

        # 构建牌号提示段
        prev_brands_section = ""
        if prev_brands:
            brands_str = "、".join(set(prev_brands))
            prev_brands_section = f"[前批已抽取的牌号]\n{brands_str}\n\n请参考上述牌号信息。"

        # 渲染 prompt（未配置模板时由渲染器生成纯指令）
        system, user = config_prompt_renderer.render_category(
            target,
            cfg,
            context,
            field_defs,
            format_instruction,
            whitelist or "",
            prev_brands_section,
        )

        return system, user
