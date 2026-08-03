"""LangExtract 抽取器（线路 A）。

使用 LangExtract 框架 + output_schema 强约束 + 类别内并发。

设计要点：
1. 通过 FewShotGenerator 从基础表自动生成 examples
2. 通过 OutputSchemaBuilder 构造 XGrammar 强约束 schema
3. asyncio.to_thread 包装同步 langextract.extract 调用
4. 类别内并发：max_workers=3，langextract 内部分块并行处理
5. 通过 _llm_semaphore 控制总并发（24，低于 max-num-seqs=32）

LangExtract 需要配置 LLM provider，通过 ``language_model_params`` 传入
vLLM OpenAI 兼容端点配置。

并发模型：
- 类别间并发：_category_semaphore=8
- 类别内并发：max_workers=3（langextract 内部分块并行）
- 总并发 = 8 × 3 = 24，匹配 vLLM max-num-seqs=32

使用示例::

    from app.services.extraction.llm_extract.langextract_extractor import LangExtractExtractor

    extractor = LangExtractExtractor(llm_semaphore=sem)
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
from app.services.extraction.llm_extract.few_shot_generator import few_shot_generator
from app.services.extraction.llm_extract.output_schema_builder import output_schema_builder
from app.services.extraction.prompts.prompt_manager import prompt_manager

logger = get_logger(__name__)


class LangExtractExtractor(BaseExtractor):
    """线路 A：LangExtract + output_schema 强约束。

    通过 langextract.extract 框架执行抽取，支持 few-shot 示例和
    XGrammar 结构化输出约束。类别内分块并行（max_workers=3）。
    """

    _engine_name = "langextract"

    def __init__(self, llm_semaphore: asyncio.Semaphore | None = None) -> None:
        super().__init__(llm_semaphore)
        self._settings = get_extraction_settings()

    async def extract(
        self,
        context: RetrievalContext,
        schema: dict[str, Any],
        target: ExtractionTarget,
    ) -> list[ExtractedRecord]:
        """从检索上下文抽取记录（LangExtract 线路）。

        Args:
            context: 检索上下文。
            schema: schema 定义。
            target: 抽取目标。

        Returns:
            list[ExtractedRecord]: 抽取记录列表。
        """
        if not context.text:
            logger.warning("上下文为空，跳过抽取", extra={"feature": target.feature})
            return []

        # 生成 few-shot 示例
        examples = few_shot_generator.generate(target)

        # 构建 output_schema
        output_schema = output_schema_builder.build(target)

        # 构建 prompt description
        prompt_description = self._build_prompt_description(target, schema)

        # 构建 LangExtract config
        config = self._build_config()

        # 调用 LangExtract（受 _llm_semaphore 控制）
        async with self._llm_semaphore:
            try:
                result = await asyncio.to_thread(
                    self._extract_sync,
                    context.text,
                    prompt_description,
                    examples,
                    output_schema,
                    context.whitelist_prompt,
                    config,
                )
            except Exception as err:
                logger.error(
                    "LangExtract 抽取失败",
                    extra={"feature": target.feature, "error": str(err)},
                )
                return []

        # 解析结果
        records = self._parse_extractions(result, target)

        logger.info(
            "LangExtract 抽取完成",
            extra={
                "feature": target.feature,
                "text_len": len(context.text),
                "records": len(records),
                "examples": len(examples),
                "has_schema": output_schema is not None,
            },
        )
        return records

    def _extract_sync(
        self,
        text: str,
        prompt_description: str,
        examples: list[Any],
        output_schema: dict[str, Any] | None,
        whitelist: str,
        config: dict[str, Any],
    ) -> Any:
        """同步调用 langextract.extract（在线程池中执行）。

        Args:
            text: 待抽取文本。
            prompt_description: prompt 描述。
            examples: few-shot 示例。
            output_schema: output_schema 定义。
            whitelist: 白名单 prompt（作为 additional_context）。
            config: LangExtract 配置。

        Returns:
            langextract 抽取结果。
        """
        from langextract.extraction import extract as lx_extract
        from langextract.core.data import FormatType
        from langextract.providers.openai import OpenAILanguageModel
        from langextract.prompt_validation import PromptValidationLevel

        # 显式构造 OpenAI provider（vLLM 兼容 OpenAI 接口）
        # LangExtract 默认按 model_id 正则匹配 provider，但自定义 model_id
        # （如 Qwen3.6-35B-A3B-FP8）不匹配内置 pattern，需显式指定 OpenAI provider，
        # 否则会报 "No provider registered for model_id=..." 并降级到 glmocr。
        # 同时通过 extra_body 关闭 thinking mode：Qwen3.6 的 thinking 与 XGrammar
        # 结构化输出约束冲突，会导致生成卡死（单请求 >120s 无法完成），
        # 关闭后单请求 ~10s 正常完成（已实测验证）。
        model = OpenAILanguageModel(
            model_id=self._settings.llm_model,
            api_key=self._settings.llm_api_key or "EMPTY",
            base_url=self._settings.llm_api_base,
            format_type=FormatType.JSON,
            temperature=0.1,
            max_workers=self._settings.langextract_max_workers,
            max_tokens=self._settings.llm_max_output_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

        result = lx_extract(
            text,
            prompt_description=prompt_description,
            examples=examples,
            model=model,
            format_type=FormatType.JSON,
            fence_output=False,
            output_schema=output_schema,
            additional_context=whitelist,
            extraction_passes=self._settings.langextract_passes,
            context_window_chars=self._settings.langextract_context_window_chars,
            max_char_buffer=self._settings.langextract_max_char_buffer,
            max_workers=self._settings.langextract_max_workers,
            prompt_validation_level=PromptValidationLevel.WARNING,
            show_progress=False,
        )
        return result

    def _build_prompt_description(
        self,
        target: ExtractionTarget,
        schema: dict[str, Any],
    ) -> str:
        """构建 LangExtract prompt description（与 glmocr 线路注入对齐）。

        将原先简单拼接的 prompt description 增强为与 glmocr user_template
        一致的结构化注入，确保两线路获得同等的语义引导：

        - [任务类别]：feature 名
        - [抽取要求]：schema 定义的 prompt
        - [项目与方法白名单]：**显式注入** target 的 item_names 和 method_codes，
          强约束模型只抽取白名单内的项目和方法，避免生成后剔除浪费 token。
          此段直接写入 prompt 主体（而非 additional_context），确保模型优先遵守。
        - [温度区分规则]：与 glmocr 共享的温度规则（prompt_manager.get_temperature_rules）
        - [字段定义]：从 field_descriptions.yaml 构建（build_field_defs_text），
          试验方法用 method_codes（标准编号），与 glmocr 一致
        - [输出要求]：紧凑 JSON 输出要求

        Args:
            target: 抽取目标。
            schema: schema 定义。

        Returns:
            str: 结构化 prompt description。
        """
        schema_prompt = schema.get("prompt", f"请抽取{target.feature}相关的检测数据记录。")

        # 项目与方法白名单（显式注入 prompt 主体，强约束模型生成范围）
        whitelist_section = self._build_whitelist_section(target)

        # 字段定义（从 field_descriptions.yaml 构建，与 glmocr 一致，用 method_codes）
        properties = schema.get("result", {}).get("properties", {})
        field_names = list(properties.keys())
        field_defs = prompt_manager.build_field_defs_text(
            feature=target.feature,
            field_names=field_names,
            items=target.item_names,
            methods=target.method_codes or target.method_names,
        )

        # 温度区分规则（与 glmocr 共享）
        temp_rules = prompt_manager.get_temperature_rules()

        # 紧凑 JSON 输出要求（与 glmocr prompt 对齐）
        compact_rule = (
            "请输出紧凑 JSON 结果（不要包含多余空格、换行或缩进），不要包含任何解释文字。"
            "确保所有字符串都正确闭合，不要在字符串值中包含换行符。"
        )

        parts = [
            f"[任务类别]\n{target.feature}",
            f"[抽取要求]\n{schema_prompt}",
            f"[项目与方法白名单]\n{whitelist_section}",
            f"[温度区分规则]\n{temp_rules}",
            f"[字段定义]\n{field_defs}",
            f"[输出要求]\n{compact_rule}",
        ]
        return "\n\n".join(parts)

    @staticmethod
    def _build_whitelist_section(target: ExtractionTarget) -> str:
        """构建项目与方法白名单约束段（注入 prompt 主体）。

        与 retrieval_service._build_whitelist_prompt 逻辑一致，但措辞更强硬，
        明确告知模型"只抽取以下项目，其他项目一律不要抽取"，
        避免模型生成非白名单项目后再通过后处理剔除，浪费 token。

        Args:
            target: 抽取目标。

        Returns:
            str: 白名单约束文本。
        """
        lines: list[str] = []

        if target.item_names:
            items_str = "、".join(target.item_names)
            lines.append(
                f"项目名称只能从以下列表中选取，不得生成列表以外的项目：\n{items_str}"
            )
            lines.append(
                "如果文档中没有上述项目的数据，返回空数组，不要抽取其他类别的项目。"
            )
            lines.append("")

        # 试验方法白名单用标准编号（method_codes），fallback 到方法名称
        method_enum = target.method_codes or target.method_names
        if method_enum:
            methods_str = "、".join(method_enum)
            lines.append(
                f"试验方法只能从以下列表中选取（标准编号）：\n{methods_str}"
            )
            lines.append("有年代号的保留，无年代号的取列表中对应方法的最新年代号。")
            lines.append("")

        if not lines:
            return "（本类别无项目和方法白名单约束）"

        return "\n".join(lines)

    def _build_config(self) -> dict[str, Any]:
        """构建 LangExtract 配置字典。

        Returns:
            dict: 配置字典。
        """
        return {
            "extraction_passes": self._settings.langextract_passes,
            "context_window_chars": self._settings.langextract_context_window_chars,
            "max_char_buffer": self._settings.langextract_max_char_buffer,
            "max_workers": self._settings.langextract_max_workers,
        }

    def _parse_extractions(
        self,
        result: Any,
        target: ExtractionTarget,
    ) -> list[ExtractedRecord]:
        """解析 LangExtract 抽取结果。

        LangExtract 返回的结果可能是：
        - list[Extraction] 对象列表
        - list[dict] 字典列表
        - 其他格式

        Args:
            result: LangExtract 抽取结果。
            target: 抽取目标。

        Returns:
            list[ExtractedRecord]: 抽取记录列表。
        """
        records: list[ExtractedRecord] = []

        if not result:
            return records

        # LangExtract 返回 AnnotatedDocument，需先取 extractions 列表；
        # 兼容直接返回 list 的旧格式
        if hasattr(result, "extractions"):
            extractions = result.extractions or []
        else:
            extractions = result

        for item in extractions:
            if isinstance(item, dict):
                # 字典格式
                records.append(ExtractedRecord(
                    feature=target.feature,
                    data=dict(item),
                ))
            elif hasattr(item, "extraction_class"):
                # Extraction 对象格式：extraction_text 为文本，attributes 为字段值
                data: dict[str, Any] = {}
                if item.extraction_text:
                    data["材料牌号"] = item.extraction_text
                if hasattr(item, "attributes") and item.attributes:
                    data.update(item.attributes)
                records.append(ExtractedRecord(
                    feature=target.feature,
                    data=data,
                ))

        logger.info(
            "LangExtract 结果解析完成",
            extra={
                "feature": target.feature,
                "raw_count": len(extractions),
                "parsed_count": len(records),
            },
        )
        return records
