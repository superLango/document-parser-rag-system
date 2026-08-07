"""LangExtract 抽取器（线路 A）。

使用 LangExtract 框架 + output_schema 强约束 + 类别内并发。

设计要点：
1. 通过 FewShotGenerator 从 Schema 模板字段 example 自动生成 examples
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
import json
import logging
from typing import Any

from app.core.exceptions import BusinessException
from app.core.logging import get_logger
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    ExtractedRecord,
    RetrievalContext,
)
from app.services.extraction.llm_extract.extractor_base import BaseExtractor
from app.services.extraction.llm_extract.few_shot_generator import few_shot_generator
from app.services.extraction.llm_extract.output_schema_builder import output_schema_builder
from app.services.extraction.prompts.config_prompt_renderer import config_prompt_renderer

logger = get_logger(__name__)


class LangExtractExtractor(BaseExtractor):
    """线路 A：LangExtract + output_schema 强约束。

    通过 langextract.extract 框架执行抽取，支持 few-shot 示例和
    XGrammar 结构化输出约束。类别内分块并行（max_workers=3）。
    """

    _engine_name = "langextract"

    def __init__(self, llm_semaphore: asyncio.Semaphore | None = None) -> None:
        super().__init__(llm_semaphore)

    async def extract(
        self,
        context: RetrievalContext,
        schema: dict[str, Any],
        target: ExtractionTarget,
        cfg: Any = None,
    ) -> list[ExtractedRecord]:
        """从检索上下文抽取记录（LangExtract 线路）。

        Args:
            context: 检索上下文。
            schema: schema 定义。
            target: 抽取目标。
            cfg: 抽取领域配置（Prompt 模板 / LLM 参数）。

        Returns:
            list[ExtractedRecord]: 抽取记录列表。
        """
        if not context.text:
            logger.warning("上下文为空，跳过抽取", extra={"feature": target.feature})
            return []

        # 生成 few-shot 示例（示例数走引擎分组 max_examples，缺失即报错，无硬编码回退）
        _ep = cfg.engine_params() if cfg is not None else {}
        _max_examples = _ep.get("max_examples")
        if _max_examples is None:
            raise BusinessException("未配置引擎分组参数 llm.engines.LangExtract.max_examples")
        examples = few_shot_generator.generate(target, max_examples=int(_max_examples))

        # 构建 output_schema
        output_schema = output_schema_builder.build(target)

        # 渲染 prompt（配置驱动，走 Prompt 模板；未配置模板时报错提示）
        prompt_description = self._build_prompt_description(target, cfg, context)

        # 构建 LangExtract config（配置驱动，缺失即报错）
        config = self._build_config(cfg)

        # 类别级 max_tokens 覆盖引擎分组（类别参数回退全局，不允许 env 兜底）
        _max_tokens = target.max_tokens or (cfg.max_output_tokens() if cfg is not None else None)

        # 【调试】LangExtract 抽取进入：打印引擎配置与 few-shot/output_schema 摘要
        logger.info(
            "【LangExtract·进入】抽取引擎入参与配置",
            extra={
                "engine": "LangExtract",
                "feature": target.feature,
                "context_text_len": len(context.text),
                "engine_params": cfg.engine_params() if cfg is not None else {},
                "max_tokens": _max_tokens,
                "temperature": cfg.engine_temperature() if cfg is not None else None,
                "endpoint": cfg.endpoint if cfg is not None else {},
                "few_shot_example_count": len(examples),
                "few_shot_examples": [json.dumps(e, ensure_ascii=False, default=str) for e in examples],
                "output_schema": json.dumps(output_schema, ensure_ascii=False) if output_schema else None,
                "lang_extract_config": config,
            },
        )

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
                    cfg,
                    _max_tokens,
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
        cfg: Any = None,
        max_tokens: int | None = None,
    ) -> Any:
        """同步调用 langextract.extract（在线程池中执行）。

        Args:
            text: 待抽取文本。
            prompt_description: prompt 描述。
            examples: few-shot 示例。
            output_schema: output_schema 定义。
            whitelist: 白名单 prompt（作为 additional_context）。
            config: LangExtract 配置（含 max_workers 等）。
            cfg: 抽取领域配置（LLM 参数）。
            max_tokens: 采样 max_tokens（类别级/引擎分组/全局，已由调用方解析）。

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
        _engine_params = cfg.engine_params() if cfg is not None else {}
        _endpoint = cfg.endpoint if cfg is not None else {}
        # max_tokens 由调用方解析（类别级/引擎分组），此处直接使用
        _max_workers = config["max_workers"]
        _enable_thinking = _engine_params.get("enable_thinking")
        _temperature = cfg.engine_temperature() if cfg is not None else None
        # 输出格式 / 围栏输出（引擎分组配置，缺失即报错，无硬编码回退）
        _ft = (_engine_params.get("format_type") or "").lower()
        if _ft not in ("json", "yaml"):
            raise BusinessException("未配置引擎分组参数 llm.engines.LangExtract.format_type（json/yaml）")
        _format_type = FormatType.YAML if _ft == "yaml" else FormatType.JSON
        _fence_output = _engine_params.get("fence_output")
        if _fence_output is None:
            raise BusinessException("未配置引擎分组参数 llm.engines.LangExtract.fence_output")
        # LLM 端点（kb.config.extraction 服务，缺失即报错）
        if not _endpoint.get("model") or not _endpoint.get("base_url"):
            raise BusinessException("未配置抽取 LLM 端点（api_base/model），请在资源与配置中填写")
        model = OpenAILanguageModel(
            model_id=_endpoint.get("model"),
            api_key=_endpoint.get("api_key") or "EMPTY",
            base_url=_endpoint.get("base_url"),
            format_type=_format_type,
            # 引擎温度：仅引擎分组自有配置，缺失已由提交前校验拦截
            temperature=_temperature,
            max_workers=_max_workers,
            max_tokens=_max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": _enable_thinking}},
        )

        # Prompt 校验级别（kb.config.extraction.prompt_validation_level，缺失即报错）
        _pvl_str = (cfg.prompt_validation_level if cfg is not None else "") or ""
        _pvl = {
            "off": PromptValidationLevel.OFF,
            "warning": PromptValidationLevel.WARNING,
            "error": PromptValidationLevel.ERROR,
        }.get(_pvl_str)
        if _pvl is None:
            raise BusinessException("未配置 Prompt 校验级别 prompt_validation_level（off/warning/error）")

        result = lx_extract(
            text,
            prompt_description=prompt_description,
            examples=examples,
            model=model,
            format_type=_format_type,
            fence_output=_fence_output,
            output_schema=output_schema,
            additional_context=whitelist,
            extraction_passes=config["extraction_passes"],
            context_window_chars=config["context_window_chars"],
            max_char_buffer=config["max_char_buffer"],
            max_workers=_max_workers,
            prompt_validation_level=_pvl,
            show_progress=False,
        )
        return result

    def _build_prompt_description(
        self,
        target: ExtractionTarget,
        cfg: Any = None,
        context: RetrievalContext | None = None,
    ) -> str:
        """构建 LangExtract prompt description（配置驱动）。

        Prompt 来源与 BaseExtract 一致，走 ``config_prompt_renderer.render_category``
        （Prompt 模板）。未配置模板时抛错提示，不再写死回退文本。

        Args:
            target: 抽取目标。
            cfg: 抽取领域配置。
            context: 检索上下文（含白名单 / 前批牌号）。

        Returns:
            str: prompt description（渲染后的 user_prompt）。
        """
        field_defs = config_prompt_renderer.build_field_defs(target)
        whitelist = context.whitelist_prompt if context is not None else ""

        # 输出格式说明由 Schema 模板 return_type 声明，Prompt 模板通过占位符引用
        system, user = config_prompt_renderer.render_category(
            target,
            cfg,
            context.text if context is not None else "",
            field_defs,
            "",
            whitelist,
            "",
        )

        if not user:
            raise BusinessException(
                f"未配置类别「{target.feature}」的 Prompt 模板，请配置！"
            )
        return user

    def _build_config(self, cfg: Any = None) -> dict[str, Any]:
        """构建 LangExtract 配置字典（配置驱动，缺失即报错，无 env 兜底）。

        Args:
            cfg: 抽取领域配置。

        Returns:
            dict: 配置字典。
        """
        # 类别内并发（within_category）映射为 max_workers
        _ep = cfg.engine_params() if cfg is not None else {}
        max_workers = cfg.within_category_concurrency() if cfg is not None else None
        return {
            "extraction_passes": _ep.get("passes"),
            "context_window_chars": _ep.get("context_window_chars"),
            "max_char_buffer": _ep.get("max_char_buffer"),
            "max_workers": max_workers,
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
                    # 主标识字段名取自 Schema 模板配置字段（缺失则跳过，不写死"材料牌号"）
                    _pk = self._primary_field_name(target)
                    if _pk:
                        data[_pk] = item.extraction_text
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

    def _primary_field_name(self, target: ExtractionTarget) -> str | None:
        """主标识字段名（Schema 模板配置字段）。

        取首个必填字段；无必填字段则取首个字段；无字段返回 None。
        """
        fields = target.fields or []
        for f in fields:
            if f.get("required") and f.get("name"):
                return f["name"]
        return fields[0].get("name") if fields else None
