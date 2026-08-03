"""glm-ocr 风格抽取器（线路 B）。

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

    from app.services.extraction.llm_extract.glmocr_extractor import GlmOcrExtractor

    extractor = GlmOcrExtractor(llm_semaphore=sem)
    records = await extractor.extract(context, schema, target)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.llm_client import llm_client
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    ExtractedRecord,
    RetrievalContext,
)
from app.services.extraction.llm_extract.batch_processor import batch_processor
from app.services.extraction.llm_extract.extractor_base import BaseExtractor
from app.services.extraction.prompts.prompt_manager import prompt_manager

logger = get_logger(__name__)


class GlmOcrExtractor(BaseExtractor):
    """线路 B：glm-ocr simple_pipeline 风格直抽。

    短文本单次调用 / 长文本分批串行（牌号传递）。
    """

    _engine_name = "glmocr"

    def __init__(self, llm_semaphore: asyncio.Semaphore | None = None) -> None:
        super().__init__(llm_semaphore)
        self._settings = get_extraction_settings()

    async def extract(
        self,
        context: RetrievalContext,
        schema: dict[str, Any],
        target: ExtractionTarget,
    ) -> list[ExtractedRecord]:
        """从检索上下文抽取记录（glmocr 线路）。

        Args:
            context: 检索上下文（含拼接文本和白名单）。
            schema: 该 feature 的 schema 定义。
            target: 抽取目标。

        Returns:
            list[ExtractedRecord]: 抽取的记录列表。
        """
        if not context.text:
            logger.warning("上下文为空，跳过抽取", extra={"feature": target.feature})
            return []

        # 文本预处理：短文本单次 / 长文本分批
        batches = batch_processor.split(context.text)

        if len(batches) <= 1:
            # 短文本：单次 LLM 调用
            return await self._extract_single(
                batches[0] if batches else "",
                schema,
                target,
                context.whitelist_prompt,
            )
        else:
            # 长文本：分批串行（牌号传递）
            return await self._extract_batched(batches, schema, target, context.whitelist_prompt)

    async def _extract_single(
        self,
        text: str,
        schema: dict[str, Any],
        target: ExtractionTarget,
        whitelist: str,
        prev_brands: list[str] | None = None,
    ) -> list[ExtractedRecord]:
        """单次 LLM 抽取（短文本或单批）。

        Args:
            text: 待抽取文本（截断到 glmocr_context_truncate）。
            schema: schema 定义。
            target: 抽取目标。
            whitelist: 白名单 prompt。
            prev_brands: 前批抽取的牌号（跨批传递）。

        Returns:
            list[ExtractedRecord]: 抽取记录列表。
        """
        # 截断保护
        truncated_text = text[:self._settings.glmocr_context_truncate]

        # 构建 prompt
        system_prompt, user_prompt = self._build_prompt(
            target, schema, truncated_text, whitelist, prev_brands
        )

        # 调用 LLM（受 _llm_semaphore 控制）
        async with self._llm_semaphore:
            try:
                result_data = await llm_client.chat_json(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=self._settings.llm_max_output_tokens,
                    temperature=self._settings.llm_temperature,
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
    ) -> list[ExtractedRecord]:
        """分批**并行**抽取（长文本，全批次同时压入 vLLM 等待队列）。

        所有批次通过 ``asyncio.gather`` 并发提交，每个批次独立调用 LLM，
        由全局 ``llm_semaphore`` 控制并发上限，vLLM 自动排队批处理。

        **与串行的区别**：
        - 串行：批次 1 → 等 LLM 返回 → 批次 2 → ...（牌号逐批传递）
        - 并行：批次 1/2/.../N 同时提交 → vLLM 满载并发处理 → 合并去重

        牌号传递在并行模式下不可行，改为后处理阶段统一去重
        （``post_processor`` 的 ``_dedup`` 逻辑）。

        Args:
            batches: 批次列表。
            schema: schema 定义。
            target: 抽取目标。
            whitelist: 白名单 prompt。

        Returns:
            list[ExtractedRecord]: 合并后的抽取记录列表。
        """
        # 所有批次并行提交（prev_brands=None，不传递牌号）
        tasks = [
            self._extract_single(batch_text, schema, target, whitelist, None)
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
    ) -> tuple[str, str]:
        """构建抽取 prompt（复用 prompt_manager）。

        Args:
            target: 抽取目标。
            schema: schema 定义。
            context: 文档上下文。
            whitelist: 白名单 prompt。
            prev_brands: 前批牌号列表。

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        # 构建字段定义文本（从 schema.properties 动态取字段名）
        # 试验方法用标准编号（method_codes），fallback 到方法名称
        properties = schema.get("result", {}).get("properties", {})
        field_names = list(properties.keys())
        field_defs = prompt_manager.build_field_defs_text(
            feature=target.feature,
            field_names=field_names,
            items=target.item_names,
            methods=target.method_codes or target.method_names,
        )

        # 构建输出格式说明
        format_instruction = self._build_format_instruction(schema)

        # 构建牌号提示段
        prev_brands_section = ""
        if prev_brands:
            brands_str = "、".join(set(prev_brands))
            prev_brands_section = f"[前批已抽取的牌号]\n{brands_str}\n\n请参考上述牌号信息。"

        # 构建白名单段
        whitelist_section = whitelist or ""

        # 渲染 prompt
        schema_prompt = schema.get("prompt", "")
        system, user = prompt_manager.render_category_prompt(
            feature=target.feature,
            prompt=schema_prompt,
            field_defs=field_defs,
            format_instruction=format_instruction,
            context=context,
            whitelist_section=whitelist_section,
            prev_brands_section=prev_brands_section,
        )

        return system, user

    @staticmethod
    def _build_format_instruction(schema: dict[str, Any]) -> str:
        """构建输出格式说明。

        Args:
            schema: schema 定义。

        Returns:
            str: 格式说明文本。
        """
        result_def = schema.get("result", {})
        result_type = result_def.get("type", "array")
        properties = result_def.get("properties", {})
        field_names = list(properties.keys())

        if result_type == "array":
            return (
                "请输出 JSON 数组，每个元素为一个检测数据记录，包含以下字段：\n"
                f"{', '.join(field_names)}\n"
                "如果文档中没有该类别的数据，返回空数组 []。"
            )
        else:
            return (
                "请输出 JSON 对象，包含以下字段：\n"
                f"{', '.join(field_names)}"
            )
