"""E3 LLM 抽取：BaseExtract 直抽（引擎已收敛：BaseExtract / LangExtractPkg(原包)）。

- BaseExtract：单轮/分批直抽，消费 temperature/max_tokens/top_p/top_k/timeout/
  enable_thinking/batch.*（含 context_truncate）；
- 输入长度按模型上下文窗口与输出预算约束，避免 400（context over limit）。
"""

from __future__ import annotations

import json
import re

from app.core.logging import get_logger
from app.services.extraction import prompt_renderer
from app.services.llm.llm_client import LLMError

logger = get_logger(__name__)

# 当前 LLM 上下文窗口（Qwen3.6-35B-A3B-FP8 max_model_len=55000）
MODEL_CONTEXT_WINDOW_TOKENS = 55000
# 输入预算安全余量（Prompt 模板/系统提示等固定开销）
_INPUT_RESERVE_TOKENS = 3000


def input_char_budget(max_tokens: int, chars_per_token: float = 1.5) -> int:
    """按模型上下文窗口与输出预算计算单次请求最大输入字符数。"""
    budget = int((MODEL_CONTEXT_WINDOW_TOKENS - int(max_tokens) - _INPUT_RESERVE_TOKENS) * chars_per_token)
    return max(2000, budget)


def split_context(context: str, batch_chars: int, overlap: int, max_chars: int) -> list[str]:
    """将完整上下文切分为多个片段（不丢失内容，最后一段完整保留）。"""
    if not context:
        return []
    batch_chars = min(max(1, int(batch_chars)), max_chars)
    overlap = min(max(0, int(overlap)), max(0, batch_chars - 1))
    if len(context) <= batch_chars:
        return [context]
    segments: list[str] = []
    start = 0
    while start < len(context):
        end = min(start + batch_chars, len(context))
        if end < len(context) and overlap > 0:
            end = max(start + overlap, end - overlap)
        segments.append(context[start:end])
        start = end
    return segments


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
        raise LLMError("LLM 输出结构异常：应为 JSON 数组或对象")
    return [r for r in records if isinstance(r, dict)]


def parse_records(text: str, schema: dict) -> list[dict]:
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
    except ValueError as exc:
        raise LLMError(f"LLM 输出不是合法 JSON：{exc}") from exc
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
    input_budget = input_char_budget(max_tokens)
    single_threshold = min(int(batch_cfg.get("single_threshold") or 8000), input_budget)
    batch_chars = min(int(batch_cfg.get("batch_chars") or 6000), input_budget)
    overlap = int(batch_cfg.get("overlap") or 500)

    async def _call(user_text: str) -> str:
        return await _call_llm(client, system, user_text, engine_params=engine_params, max_tokens=max_tokens, json_mode=True)

    if len(context) <= single_threshold:
        return parse_records(await _call(user), target.schema)

    # 拆分 chunk 多次抽取，不截断；任一片段失败即整体失败（不静默丢数据）
    all_records: list[dict] = []
    segments = split_context(context, batch_chars, overlap, input_budget)
    for idx, batch_text in enumerate(segments, start=1):
        start_ch = (idx - 1) * batch_chars + 1
        end_ch = min(idx * batch_chars, len(context))
        logger.info("片段开始", feature=target.feature, segment=idx, total=len(segments), chars=len(batch_text))
        try:
            all_records.extend(parse_records(await _call(f"{user}\n\n[片段 {start_ch}-{end_ch}]\n{batch_text}"), target.schema))
        except LLMError as exc:
            logger.error("片段失败", feature=target.feature, segment=idx, error=str(exc))
            raise LLMError(f"片段 {idx} 抽取失败：{exc}") from exc
        logger.info("片段完成", feature=target.feature, segment=idx)
    return _dedupe_records(all_records)


async def extract_category(cfg, target, context: str, client, engine_params: dict, engine: str = "BaseExtract") -> list[dict]:
    """BaseExtract 直抽；LangExtractPkg 由 pipeline 走原包适配器，不进入此函数。"""
    batch_cfg = engine_params.get("batch") or {}
    max_tokens = target.max_tokens or engine_params.get("max_tokens") or 4096
    input_budget = input_char_budget(max_tokens)
    context_truncate = min(int(batch_cfg.get("context_truncate") or 32000), input_budget)
    if len(context) > context_truncate:
        context = context[:context_truncate]
    return await _extract_base(cfg, target, context, client, engine_params)
