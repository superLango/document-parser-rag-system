"""E3 LLM 抽取：Prompt 渲染 → 调用 → JSON 解析（含基础分批）。"""

from __future__ import annotations

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


def parse_records(text: str, schema: dict) -> list[dict]:
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
    except ValueError as exc:
        raise LLMError(f"LLM 输出不是合法 JSON：{exc}") from exc
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


def missing_required_fields(records: list[dict], schema: dict) -> list[str]:
    props = (schema or {}).get("properties") or {}
    missing: list[str] = []
    for name, prop in props.items():
        if not prop.get("required"):
            continue
        if not any(r.get(name) not in (None, "") for r in records):
            missing.append(name)
    return missing


async def extract_category(cfg, target, context: str, client, engine_params: dict) -> list[dict]:
    system, user = prompt_renderer.render_category(cfg, target, context)
    temperature = float(engine_params.get("temperature") or 0.0)
    max_tokens = target.max_tokens or engine_params.get("max_tokens") or 4096
    batch_cfg = engine_params.get("batch") or {}
    single_threshold = int(batch_cfg.get("single_threshold") or 8000)
    batch_chars = int(batch_cfg.get("batch_chars") or 6000)
    overlap = int(batch_cfg.get("overlap") or 500)

    async def _call(user_text: str) -> str:
        return await client.complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )

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
    seen = set()
    deduped = []
    for r in all_records:
        key = json.dumps(r, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped
