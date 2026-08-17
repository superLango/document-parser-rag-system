"""LangExtract 原包适配器（langextract>=1.6.0）。

参考原项目 ``langextract_extractor.py``，按当前项目优化：
- LLM 端点直接复用 KB「资源与配置」services.llm_vllm（api_base/model/api_key）；
- Prompt 复用当前项目 ``prompt_renderer``（与 BaseExtract/自研 LangExtract 同一模板引擎）；
- output_schema 适配当前项目 {type, properties} 扁平 schema；
- 引擎参数全部读 GlobalLangExtractConfig，缺失用默认值；
- prompt_validation_level 默认 OFF（当前项目无该配置项，避免强校验阻塞流程）。

依赖：langextract>=1.6.0（已加入 backend/requirements.txt）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from langextract.core.data import ExampleData, Extraction, FormatType
from langextract.extraction import extract as lx_extract
from langextract.prompt_validation import PromptValidationLevel
from langextract.providers.openai import OpenAILanguageModel
from langextract.schema import extraction_item_schema, extractions_schema

from app.core.exceptions import BusinessException
from app.core.logging import get_logger
from app.services.extraction import prompt_renderer
from app.services.extraction.extraction_models import ExtractionTarget

logger = get_logger(__name__)


def build_output_schema(target: ExtractionTarget) -> dict | None:
    """当前项目 schema（{type, properties}）→ LangExtract extractions_schema。"""
    props = (target.schema or {}).get("properties") or {}
    json_properties: dict[str, dict[str, Any]] = {}
    for name, prop in props.items():
        item: dict[str, Any] = {"type": prop.get("type", "string")}
        if prop.get("description"):
            item["description"] = prop["description"]
        json_properties[name] = item
    if not json_properties:
        return None
    item_schema = extraction_item_schema(
        extraction_class=target.feature,
        attributes=json_properties,
        additional_properties=False,
    )
    return extractions_schema(item_schema)


def build_examples(target: ExtractionTarget, max_examples: int) -> list[ExampleData]:
    """few-shot v3：1 条完整正例（所有字段单值）+ 1 条多值拆条示例。"""
    if max_examples <= 0:
        return []
    full: dict[str, str] = {}
    for f in target.fields or []:
        name = f.get("name", "")
        ex = f.get("example")
        if not name:
            continue
        vals = ex if isinstance(ex, list) else [ex]
        full[name] = next((str(v) for v in vals if v is not None and str(v).strip()), "")
    examples: list[ExampleData] = []
    if full:
        parts = [target.feature] + [f"{k} {v}" for k, v in full.items() if v]
        sample_text = "，".join(parts)
        examples.append(ExampleData(
            text=sample_text,
            extractions=[Extraction(
                extraction_class=target.feature,
                extraction_text=sample_text,
                attributes=full,
            )],
        ))
    # 拆条示例：原文一个字段含多个值 → 拆成多条单值记录
    if max_examples >= 2:
        fields = [f.get("name", "") for f in (target.fields or []) if f.get("name")]
        pick = next((f for f in ["材料牌号", "项目名称", "尺寸厚度", "标准要求"] if f in fields), fields[0] if fields else None)
        if pick:
            text = f"原文片段（示例）：{pick}：示例值A、示例值B"
            rec1 = {pick: "示例值A"}
            rec2 = {pick: "示例值B"}
            examples.append(ExampleData(
                text=text,
                extractions=[
                    Extraction(extraction_class=target.feature, extraction_text="示例值A", attributes=rec1),
                    Extraction(extraction_class=target.feature, extraction_text="示例值B", attributes=rec2),
                ],
            ))
    return examples


def _primary_field_name(target: ExtractionTarget) -> str | None:
    fields = target.fields or []
    for f in fields:
        if f.get("required") and f.get("name"):
            return f["name"]
    return fields[0].get("name") if fields else None


def _parse_result(result: Any, target: ExtractionTarget) -> list[dict]:
    """AnnotatedDocument / list[Extraction] / list[dict] → 记录 dict 列表。"""
    records: list[dict] = []
    if not result:
        return records
    extractions = getattr(result, "extractions", None)
    if extractions is None:
        extractions = result if isinstance(result, list) else []
    for item in extractions:
        if isinstance(item, dict):
            records.append(dict(item))
        elif hasattr(item, "extraction_class"):
            data: dict[str, Any] = {}
            if item.extraction_text:
                pk = _primary_field_name(target)
                if pk:
                    data[pk] = item.extraction_text
            if getattr(item, "attributes", None):
                data.update(item.attributes)
            records.append(data)
    return records


async def extract_category_pkg(
    *,
    kb_id,
    cfg,
    target: ExtractionTarget,
    context: str,
    engine_params: dict,
    llm_endpoint: dict,
) -> list[dict]:
    """调用 langextract.extract（线程池），配置全部来自引擎参数与 KB LLM 资源。"""
    if not llm_endpoint or not llm_endpoint.get("api_base") or not llm_endpoint.get("model"):
        raise BusinessException(message="未配置抽取 LLM 端点（api_base/model），请在资源与配置中填写")
    fmt = (engine_params.get("format_type") or "JSON").upper()
    if fmt not in ("JSON", "YAML"):
        raise BusinessException(message="LangExtract 原包 format_type 仅支持 json/yaml")
    format_type = FormatType.YAML if fmt == "YAML" else FormatType.JSON
    fence_output = bool(engine_params.get("fence_output"))
    passes = int(engine_params.get("passes") or 2)
    window_chars = int(engine_params.get("context_window_chars") or 28000)
    max_buffer = int(engine_params.get("max_char_buffer") or 40000)
    max_workers = int((engine_params.get("concurrency") or {}).get("within_category") or 1)
    temperature = float(engine_params.get("temperature") or 0.0)
    max_tokens = target.max_tokens or engine_params.get("max_tokens") or 4096
    enable_thinking = bool(engine_params.get("enable_thinking"))
    max_examples = int(engine_params.get("max_examples") or 0)

    examples = build_examples(target, max_examples)
    output_schema = build_output_schema(target)
    # 原包约束：output_schema（XGrammar）与 fence_output 互斥；保留更强的 XGrammar 约束
    if output_schema is not None and fence_output:
        logger.warning(
            "LangExtract 原包：output_schema 与 fence_output 互斥，已关闭围栏以保留 XGrammar 强约束",
            feature=target.feature,
        )
        fence_output = False
    _, prompt_description = prompt_renderer.render_category(cfg, target, "")

    model = OpenAILanguageModel(
        model_id=llm_endpoint["model"],
        api_key=(llm_endpoint.get("api_key") or "EMPTY"),
        base_url=(llm_endpoint.get("api_base") or "").rstrip("/"),
        format_type=format_type,
        temperature=temperature,
        max_workers=max_workers,
        max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
    )

    try:
        result = await asyncio.to_thread(
            lx_extract,
            context,
            prompt_description=prompt_description,
            examples=examples or None,
            model=model,
            format_type=format_type,
            fence_output=fence_output,
            output_schema=output_schema,
            additional_context="",
            extraction_passes=passes,
            context_window_chars=window_chars,
            max_char_buffer=max_buffer,
            max_workers=max_workers,
            prompt_validation_level=PromptValidationLevel.OFF,
            show_progress=False,
        )
    except Exception as exc:
        logger.error("LangExtract 原包抽取失败", feature=target.feature, error=str(exc))
        raise
    return _parse_result(result, target)
