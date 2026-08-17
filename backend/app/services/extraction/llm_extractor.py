"""E3 LLM 抽取：BaseExtract 直抽 / LangExtract 结构化强约束。

- BaseExtract：单轮/分批直抽，消费 temperature/max_tokens/top_p/top_k/timeout/
  enable_thinking/batch.*（含 context_truncate）；
- LangExtract：few-shot 示例 + 多轮补充 + 上下文窗口切分 + 类别内并发，
  消费 format_type/fence_output/max_examples/passes/context_window_chars/
  max_char_buffer/within_category 及 BaseExtract 全部公共参数。
"""

from __future__ import annotations

import asyncio
import json
import re

from app.core.logging import get_logger
from app.services.extraction import prompt_renderer
from app.services.llm.llm_client import LLMError

logger = get_logger(__name__)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()
    return text


def _normalize_records(data) -> list[dict]:
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        if isinstance(data.get("records"), list):
            records = data["records"]
        else:
            records = [data]
    else:
        raise LLMError("LLM 输出结构异常：应为 JSON/YAML 数组或对象")
    return [r for r in records if isinstance(r, dict)]


def parse_records(text: str, schema: dict) -> list[dict]:
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
    except ValueError as exc:
        raise LLMError(f"LLM 输出不是合法 JSON：{exc}") from exc
    return _normalize_records(data)


def parse_yaml_records(text: str, schema: dict) -> list[dict]:
    import yaml

    cleaned = _strip_fences(text)
    try:
        data = yaml.safe_load(cleaned)
    except Exception as exc:
        raise LLMError(f"LLM 输出不是合法 YAML：{exc}") from exc
    return _normalize_records(data)


def missing_required_fields(records: list[dict], schema: dict) -> list[str]:
    props = (schema or {}).get("properties") or {}
    missing: list[str] = []
    for name, prop in props.items():
        if not prop.get("required"):
            continue
        if not any(r.get(name) not in (None, "") for r in records):
            missing.append(name)
    return missing


def _dedupe_records(records: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in records:
        key = json.dumps(r, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _build_few_shot_examples(target, max_examples: int) -> list[dict]:
    """从 Schema 字段 example 生成 1 条完整正例（所有字段单值）。"""
    if max_examples <= 0:
        return []
    rec: dict = {}
    for f in target.fields or []:
        name = f.get("name", "")
        ex = f.get("example")
        if not name:
            continue
        vals = ex if isinstance(ex, list) else [ex]
        val = next((str(v) for v in vals if v is not None and str(v).strip()), "")
        rec[name] = val
    return [rec] if rec else []


def _build_split_demo(target) -> dict | None:
    """构造多值拆条演示：原文含两个值 → 输出两条单值记录。"""
    fields = [f.get("name", "") for f in (target.fields or []) if f.get("name")]
    pick = next((f for f in ["材料牌号", "项目名称", "尺寸厚度", "标准要求"] if f in fields), fields[0] if fields else None)
    if not pick:
        return None
    text = f"原文片段（示例）：{pick}：示例值A、示例值B"
    return {
        "text": text,
        "records": [
            {pick: "示例值A"},
            {pick: "示例值B"},
        ],
    }


def _format_instruction(format_type: str, fence_output: bool) -> str:
    fmt = (format_type or "JSON").upper()
    if fmt == "YAML":
        instr = "输出 YAML 列表（每个元素为一条记录，键与 Schema 字段一致）"
    else:
        instr = "输出紧凑 JSON 数组（每个元素为一条记录，键与 Schema 字段一致）"
    if fence_output:
        instr += f"，并使用 ```{fmt.lower()} ... ``` 围栏包裹"
    return instr


def _split_windows(text: str, window_chars: int, overlap: int, max_buffer: int) -> list[str]:
    if len(text) <= window_chars:
        return [text[:max_buffer]]
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + window_chars, len(text))
        if end < len(text) and overlap > 0:
            end = max(start + overlap, end - overlap)
        windows.append(text[start:end][:max_buffer])
        start = end
    return windows


def _lang_prompt(
    user_base: str,
    examples: list[dict],
    format_type: str,
    fence_output: bool,
    pass_no: int,
    prev_records: list[dict],
    window_text: str,
    split_demo: dict | None = None,
) -> str:
    lines = [user_base]
    if examples:
        lines.append("[示例]（完整记录，值为占位示例，勿照抄）:")
        lines.append(json.dumps(examples, ensure_ascii=False))
    if split_demo:
        lines.append("[拆条示例]（原文一个字段含多个值时，必须拆成多条单值记录）:")
        lines.append(split_demo.get("text", ""))
        lines.append(json.dumps(split_demo.get("records", []), ensure_ascii=False))
    lines.append(f"[输出格式]: {_format_instruction(format_type, fence_output)}")
    if pass_no > 0:
        lines.append("[已抽取记录]: " + (json.dumps(prev_records, ensure_ascii=False) if prev_records else "无"))
        lines.append("请只补充文档中尚未抽取的新记录；如无新增返回空数组 []")
    lines.append("[文档内容片段]:")
    lines.append(window_text)
    return "\n".join(lines)


async def _call_llm(client, system: str, user: str, *, engine_params: dict, max_tokens: int, json_mode: bool) -> str:
    return await client.complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        json_mode=json_mode,
        temperature=float(engine_params.get("temperature") or 0.0),
        max_tokens=max_tokens,
        timeout=int(engine_params.get("timeout") or 300),
        top_p=engine_params.get("top_p"),
        top_k=engine_params.get("top_k"),
        enable_thinking=bool(engine_params.get("enable_thinking")),
    )


async def _extract_base(cfg, target, context: str, client, engine_params: dict) -> list[dict]:
    system, user = prompt_renderer.render_category(cfg, target, context)
    max_tokens = target.max_tokens or engine_params.get("max_tokens") or 4096
    batch_cfg = engine_params.get("batch") or {}
    single_threshold = int(batch_cfg.get("single_threshold") or 8000)
    batch_chars = int(batch_cfg.get("batch_chars") or 6000)
    overlap = int(batch_cfg.get("overlap") or 500)

    async def _call(user_text: str) -> str:
        return await _call_llm(client, system, user_text, engine_params=engine_params, max_tokens=max_tokens, json_mode=True)

    if len(context) <= single_threshold:
        return parse_records(await _call(user), target.schema)

    all_records: list[dict] = []
    start = 0
    while start < len(context):
        end = min(start + batch_chars, len(context))
        if end < len(context) and end - start >= overlap:
            end = max(start + overlap, end - overlap)
        batch_text = context[start:end]
        try:
            all_records.extend(parse_records(await _call(f"{user}\n\n[片段 {start + 1}-{end}]\n{batch_text}"), target.schema))
        except LLMError:
            logger.warning("分批抽取片段解析失败，跳过该片段", feature=target.feature)
        start = end
    return _dedupe_records(all_records)


async def _extract_lang(cfg, target, context: str, client, engine_params: dict) -> list[dict]:
    """LangExtract：few-shot + 多轮补充 + 窗口切分 + 类别内并发。"""
    system, user_base = prompt_renderer.render_category(cfg, target, "")
    max_tokens = target.max_tokens or engine_params.get("max_tokens") or 4096
    format_type = (engine_params.get("format_type") or "JSON").upper()
    fence_output = bool(engine_params.get("fence_output"))
    passes = int(engine_params.get("passes") or 2)
    max_examples = int(engine_params.get("max_examples") or 0)
    window_chars = int(engine_params.get("context_window_chars") or 28000)
    max_buffer = int(engine_params.get("max_char_buffer") or 40000)
    overlap = int((engine_params.get("batch") or {}).get("overlap") or 500)
    within = int((engine_params.get("concurrency") or {}).get("within_category") or 1)
    json_mode = format_type == "JSON"
    examples = _build_few_shot_examples(target, max_examples)
    split_demo = _build_split_demo(target) if max_examples >= 2 else None
    windows = _split_windows(context, window_chars, overlap, max_buffer)
    merged: list[dict] = []

    for pass_no in range(passes):
        sem = asyncio.Semaphore(max(1, within))
        prev = list(merged)

        async def _one(win_text: str, _pass_no: int = pass_no, _prev: list = prev, _sem: asyncio.Semaphore = sem) -> list[dict]:
            async with _sem:
                prompt = _lang_prompt(user_base, examples, format_type, fence_output, _pass_no, _prev, win_text, split_demo)
                raw = await _call_llm(client, system, prompt, engine_params=engine_params, max_tokens=max_tokens, json_mode=json_mode)
                if json_mode:
                    return parse_records(raw, target.schema)
                return parse_yaml_records(raw, target.schema)

        results = await asyncio.gather(*[_one(w) for w in windows], return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("LangExtract 窗口抽取失败，跳过该窗口", error=str(r))
                continue
            merged = _dedupe_records(merged + r)
        if pass_no == 0 and not merged:
            break  # 首轮无结果则不再补轮
    return merged


async def extract_category(cfg, target, context: str, client, engine_params: dict, engine: str = "BaseExtract") -> list[dict]:
    """按引擎分发：BaseExtract 直抽 / LangExtract 结构化强约束。"""
    batch_cfg = engine_params.get("batch") or {}
    context_truncate = int(batch_cfg.get("context_truncate") or 32000)
    if len(context) > context_truncate:
        context = context[:context_truncate]
    if engine == "LangExtract":
        return await _extract_lang(cfg, target, context, client, engine_params)
    return await _extract_base(cfg, target, context, client, engine_params)
