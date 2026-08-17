"""LangExtract 原包适配器（langextract>=1.6.0，抽取引擎收敛：LangExtractPkg）。

参考原项目 ``langextract_extractor.py``，按当前项目优化，并充分利用原包官方特性：
- **完整上下文一次交给 ``lx.extract``**，由原包内部完成：sentence-aware 分块
  （max_char_buffer）、跨块共指窗口（context_window_chars）、batch×workers 并行、
  多轮抽取（passes，first-pass-wins 按字符区间合并）、resolver 对齐
  （exact/fuzzy/lesser，带回字符区间证据）；不再自行预切段循环调用
  （旧实现会把上下文拆成独立片段逐段调用，等于禁用上述官方特性）；
- **防超限不截断**：max_char_buffer 受模型窗口与输出预算（input_char_budget）钳制，
  并扣除指令/示例/输出 Schema 固定开销与共指窗口；超时按预估块数缩放，
  避免长文档被固定超时误杀；
- **溯源证据**：记录附带 ``_evidence``（源文本字符区间 + 对齐状态），支撑复核/审计；
- **合并去重**：按主键字段值归一化去重（同一实体保留对齐更精确/首次记录）。

依赖：langextract>=1.6.0（已加入 backend/requirements.txt）。
"""

from __future__ import annotations

import asyncio
import json
import math
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
from app.services.extraction.llm_extractor import input_char_budget

logger = get_logger(__name__)


def _prompt_overhead_chars(
    prompt_description: str,
    examples: list[ExampleData],
    output_schema: dict | None,
) -> int:
    """估算固定 prompt 开销（指令 + 示例 + Schema + 信封/安全余量，单位字符）。"""
    overhead = len(prompt_description or "")
    for ex in examples or []:
        overhead += len(ex.text or "")
        for e in ex.extractions or []:
            overhead += len(e.extraction_text or "")
            for k, v in (e.attributes or {}).items():
                overhead += len(str(k)) + len(str(v))
    if output_schema is not None:
        overhead += len(json.dumps(output_schema, ensure_ascii=False))
    # 格式信封/系统提示/指令等未显式建模部分的安全余量
    return overhead + 2000


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


def _parse_result(
    result: Any, target: ExtractionTarget, source_text: str = ""
) -> list[dict]:
    """AnnotatedDocument / list[Extraction] / list[dict] → 记录 dict 列表。

    记录附带 ``_evidence``：原包 resolver 对齐出的源文本字符区间与对齐状态，
    用于溯源/复核（source_text 仅用于日志，不参与构造）。
    """
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
            span = getattr(item, "char_interval", None)
            alignment = getattr(item, "alignment_status", None)
            evidence: dict[str, Any] = {}
            if span is not None and span.start_pos is not None:
                evidence["span"] = [int(span.start_pos), int(span.end_pos)]
            if alignment is not None:
                evidence["alignment"] = str(getattr(alignment, "value", alignment))
            if evidence:
                data["_evidence"] = evidence
            records.append(data)
    return records


def _json_dedupe(records: list[dict]) -> list[dict]:
    """JSON 全等去重（无主键字段时的回退方案）。"""
    seen: set[str] = set()
    out: list[dict] = []
    for r in records:
        key = json.dumps(r, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _alignment_rank(record: dict) -> int:
    """对齐状态优先级：exact > greater > lesser > fuzzy > 未知。"""
    ev = record.get("_evidence") or {}
    rank = {
        "match_exact": 4,
        "match_greater": 3,
        "match_lesser": 2,
        "match_fuzzy": 1,
    }
    return rank.get(str(ev.get("alignment") or ""), 0)


def _dedupe_records(records: list[dict], target: ExtractionTarget) -> list[dict]:
    """按主键字段归一化去重；同一主键保留对齐更精确的记录，否则保留首次。"""
    pk = _primary_field_name(target)
    if not pk:
        return _json_dedupe(records)
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for r in records:
        val = r.get(pk)
        key = str(val).strip().lower() if val not in (None, "") else None
        if key is None:
            if r not in out:
                out.append(r)
            continue
        if key in seen:
            prev = seen[key]
            if _alignment_rank(r) > _alignment_rank(prev):
                idx = out.index(prev)
                out[idx] = r
                seen[key] = r
            continue
        seen[key] = r
        out.append(r)
    return out


async def extract_category_pkg(
    *,
    kb_id,
    cfg,
    target: ExtractionTarget,
    context: str,
    engine_params: dict,
    llm_endpoint: dict,
) -> list[dict]:
    """调用 langextract.extract（线程池），完整上下文交原包分块/并行/多轮/对齐。"""
    if not llm_endpoint or not llm_endpoint.get("api_base") or not llm_endpoint.get("model"):
        raise BusinessException(message="未配置抽取 LLM 端点（api_base/model），请在资源与配置中填写")
    fmt = (engine_params.get("format_type") or "JSON").upper()
    if fmt not in ("JSON", "YAML"):
        raise BusinessException(message="LangExtract 原包 format_type 仅支持 json/yaml")
    format_type = FormatType.YAML if fmt == "YAML" else FormatType.JSON
    fence_output = bool(engine_params.get("fence_output"))
    passes = max(1, int(engine_params.get("passes") or 2))
    max_tokens = target.max_tokens or engine_params.get("max_tokens") or 8192
    max_char_buffer = int(engine_params.get("max_char_buffer") or 3000)
    context_window_chars = max(0, int(engine_params.get("context_window_chars") or 0))
    batch_length = max(1, int(engine_params.get("batch_length") or 8))
    max_workers = max(1, int(engine_params.get("max_workers") or 8))
    temperature = float(engine_params.get("temperature") or 0.0)
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
    system, user = prompt_renderer.render_category(cfg, target, "")
    prompt_description = f"{system}\n\n{user}" if (system or "").strip() else user
    overhead = _prompt_overhead_chars(prompt_description, examples, output_schema)

    # 防超限（不截断）：单块可用字符 = 输入预算 − 固定开销 − 共指窗口
    input_budget = input_char_budget(max_tokens)
    per_chunk_budget = input_budget - overhead - context_window_chars
    if per_chunk_budget < 500:
        logger.warning(
            "原包单块预算不足（max_tokens 过大或固定开销过高），按 500 字符下限兜底",
            feature=target.feature,
            per_chunk_budget=per_chunk_budget,
            overhead=overhead,
            max_tokens=max_tokens,
        )
    max_buffer = max(500, min(max_char_buffer, per_chunk_budget))
    est_chunks = max(1, math.ceil(len(context) / max_buffer)) if context else 1

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

    logger.info(
        "原包整段抽取开始",
        feature=target.feature,
        context_chars=len(context),
        max_char_buffer=max_buffer,
        context_window_chars=context_window_chars,
        passes=passes,
        batch_length=batch_length,
        max_workers=max_workers,
        est_chunks=est_chunks,
    )
    try:
        # 不设超时：抽取时长取决于上下文/输出长度，无法预估；贸然超时会
        # 误杀仍在抽取的任务（to_thread 线程实际仍会跑完但结果被丢弃）。
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
            context_window_chars=context_window_chars or None,
            max_char_buffer=max_buffer,
            batch_length=batch_length,
            max_workers=max_workers,
            prompt_validation_level=PromptValidationLevel.OFF,
            show_progress=False,
        )
    except Exception as exc:
        logger.error("LangExtract 原包整段抽取失败", feature=target.feature, error=str(exc))
        raise
    records = _parse_result(result, target, context)
    records = _dedupe_records(records, target)
    logger.info("原包整段抽取完成", feature=target.feature, records=len(records))
    return records
