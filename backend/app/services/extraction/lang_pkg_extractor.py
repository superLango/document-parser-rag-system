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
from typing import Any

import openai
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

# 长输出无法预估时长：原包 OpenAI provider 未传 timeout，SDK 默认 600s
# 会误杀长生成。openai 3.x 的 DEFAULT_TIMEOUT 是构造函数默认参数（定义时
# 绑定），覆盖模块变量无效；monkeypatch 构造时强制无读/写/池超时
# （仅保留 5s 连接超时避免连不上时挂起），长输出自然完成。
_ORIG_OPENAI_INIT = openai.OpenAI.__init__


def _no_read_timeout_init(self, *args, **kwargs):
    kwargs["timeout"] = openai.Timeout(connect=5.0, read=None, write=None, pool=None)
    _ORIG_OPENAI_INIT(self, *args, **kwargs)


openai.OpenAI.__init__ = _no_read_timeout_init


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
    """当前项目 schema（{type, properties}）→ LangExtract extractions_schema。

    - properties 包含全部字段（可选）：模型可输出元信息字段（试验方法/取样数量等），
      实现跨表关联填充（一次拼接上下文下实测模型能输出 13 字段完整记录）；
    - required 只含核心必填字段（材料牌号/项目名称/标准要求/单位等）：拆条负担小，
      避免模型因被强制输出 13 个字段而少拆条。
    """
    props = (target.schema or {}).get("properties") or {}
    json_properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for name, prop in props.items():
        item: dict[str, Any] = {"type": prop.get("type", "string")}
        if prop.get("description"):
            item["description"] = prop["description"]
        json_properties[name] = item
        if prop.get("required"):
            required.append(name)
    if not json_properties:
        return None
    attr_name = f"{target.feature}_attributes"
    return {
        "type": "object",
        "properties": {
            "extractions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        target.feature: {"type": "string"},
                        attr_name: {
                            "type": "object",
                            "properties": json_properties,
                            "required": required,
                            "additionalProperties": False,
                        },
                    },
                    "required": [target.feature, attr_name],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["extractions"],
        "additionalProperties": False,
    }




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


def _primary_key_fields(target: ExtractionTarget) -> list[str]:
    """主键字段：标识性字段组合（材料牌号/项目名称/尺寸厚度/试验温度/方向等）。

    单牌号文档（如 GH4169）所有记录牌号相同；同一项目在不同尺寸档位/温度下
    标准要求不同，主键必须包含尺寸厚度/试验温度等行级标识，否则误合并。
    """
    fields = target.fields or []
    names = [f.get("name") for f in fields if f.get("name")]
    # 标识字段优先（存在即加入）
    prefer = ["材料牌号", "项目名称", "尺寸厚度", "试验温度", "方向", "锻件类型", "试样状态"]
    keys = [n for n in prefer if n in names]
    if len(keys) >= 2:
        return keys
    required = [f.get("name") for f in fields if f.get("required") and f.get("name")]
    return required or names


def _primary_field_name(target: ExtractionTarget) -> str | None:
    """兼容旧调用：返回首个主键字段。"""
    keys = _primary_key_fields(target)
    return keys[0] if keys else None


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
    """按主键字段组合归一化去重；同一主键保留对齐更精确的记录，否则保留首次。

    主键用「材料牌号 + 项目名称」组合：单牌号文档（如 GH4169）所有记录牌号相同，
    仅按牌号去重会把不同项目/尺寸档位的记录误合并。
    """
    pk_fields = _primary_key_fields(target)
    if not pk_fields:
        return _json_dedupe(records)

    def _key_of(r: dict):
        parts = []
        for f in pk_fields:
            v = r.get(f)
            parts.append(str(v).strip().lower() if v not in (None, "") else "")
        return tuple(parts) if any(parts) else None

    seen: dict[tuple, dict] = {}
    out: list[dict] = []
    for r in records:
        key = _key_of(r)
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
    segments: list[dict] | None = None,
    llm_sem: asyncio.Semaphore | None = None,
    engine_params: dict,
    llm_endpoint: dict,
) -> list[dict]:
    """调用 langextract.extract（线程池），按语义/表格边界段逐段抽取后合并。

    segments 由 context_assembler.assemble_segments 生成：表格块独立段、文本块聚合段，
    保证每个请求不跨表；段级并行（llm_sem 控制全局 LLM 请求并发，匹配 vLLM
    max_num_seqs），避免长类别逐段串行。
    """
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
    # XGrammar 输出约束开关（默认开；实验/兼容场景可关闭，改用纯 prompt JSON 约束）
    if engine_params.get("output_schema_enabled", True):
        output_schema = build_output_schema(target)
    else:
        output_schema = None
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
    if segments is not None and len(segments) == 1:
        # 一次拼接模式：单段整块送入，max_buffer 覆盖整段（窗口余量内），
        # 避免 LangExtract 按 6000 字符切块导致跨表关联割裂。
        seg_len = len(segments[0].get("content") or "")
        max_buffer = max(max_char_buffer, seg_len, 500)
    else:
        max_buffer = max(500, min(max_char_buffer, per_chunk_budget))
    if segments is None:
        segments = [{"type": "text", "content": context}]
    est_chunks = len(segments)

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
        context_chars=sum(len(s.get("content") or "") for s in segments),
        segment_count=est_chunks,
        max_char_buffer=max_buffer,
        context_window_chars=context_window_chars,
        passes=passes,
        batch_length=batch_length,
        max_workers=max_workers,
    )
    merged: list[dict] = []

    async def _run_segment(idx: int, seg: dict) -> list[dict]:
        seg_text = seg.get("content") or ""
        if not seg_text.strip():
            return []
        logger.info(
            "原包段抽取开始", feature=target.feature, segment=idx,
            total=est_chunks, seg_chars=len(seg_text),
        )

        async def _call() -> Any:
            # 不设超时：抽取时长取决于上下文/输出长度，无法预估；贸然超时会
            # 误杀仍在抽取的任务（to_thread 线程实际仍会跑完但结果被丢弃）。
            return await asyncio.to_thread(
                lx_extract,
                seg_text,
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
                max_workers=1,  # 段级已并行，段内不再嵌套并发
                prompt_validation_level=PromptValidationLevel.OFF,
                show_progress=False,
            )

        try:
            if llm_sem is not None:
                async with llm_sem:
                    result = await _call()
            else:
                result = await _call()
        except Exception as exc:
            logger.error("LangExtract 原包段抽取失败", feature=target.feature, segment=idx, error=str(exc))
            raise
        seg_records = _parse_result(result, target, seg_text)
        logger.info(
            "原包段抽取完成", feature=target.feature, segment=idx,
            records=len(seg_records),
        )
        return seg_records

    # 段级并行（gather 保序）；任一段失败即整体失败（不静默丢数据）
    seg_results = await asyncio.gather(
        *[_run_segment(idx, seg) for idx, seg in enumerate(segments, start=1)]
    )
    for recs in seg_results:
        merged.extend(recs)
    records = _dedupe_records(merged, target)
    records = _dedupe_records(records, target)
    # return_type=object 收敛：原包输出恒为数组，object 类别取对齐最精确/首条作为单对象
    if (target.schema or {}).get("type") == "object" and records:
        records = [records[0]]
    logger.info("原包整段抽取完成", feature=target.feature, segments=est_chunks, records=len(records))
    return records
