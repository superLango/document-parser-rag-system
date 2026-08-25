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

# LLM 上下文窗口（按部署模型配置，见 settings.LLM_CONTEXT_WINDOW_TOKENS）
from app.core.config import settings as _settings

MODEL_CONTEXT_WINDOW_TOKENS = _settings.LLM_CONTEXT_WINDOW_TOKENS
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


def _extract_json_block(text: str) -> str | None:
    """括号平衡提取第一个完整 JSON 数组/对象（字符串内 ] } 不截断）。"""
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == open_ch:
                    depth += 1
                elif c == close_ch:
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
    return None


def parse_records(text: str, schema: dict) -> list[dict]:
    """解析 LLM 输出：优先整体 JSON；失败则括号平衡提取首个 JSON 数组/对象。"""
    cleaned = _strip_fences(text)
    data = None
    try:
        data = json.loads(cleaned)
    except ValueError:
        block = _extract_json_block(cleaned)
        if block is not None:
            try:
                data = json.loads(block)
            except ValueError:
                data = None
        if data is None:
            # 诊断：失败时保存完整原始输出
            try:
                with open("/tmp/llm_raw_output.txt", "w", encoding="utf-8") as _f:
                    _f.write(cleaned)
            except Exception:
                pass
            raise LLMError(f"LLM 输出不是合法 JSON（len={len(cleaned)}）：{cleaned[:200]}")
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
    """BaseExtract 直抽：整段上下文拼入 Prompt，一次给模型（不截断、不分段）。

    json_mode 默认关闭：vLLM 的 json_object 约束会把输出压成单对象（每类别仅 1 条），
    与脚本验证路线（无 response_format）不一致；可经 engine_params.json_mode 开启。
    """
    system, user = prompt_renderer.render_category(cfg, target, context)
    max_tokens = target.max_tokens or engine_params.get("max_tokens") or 4096
    json_mode = bool(engine_params.get("json_mode", False))
    return parse_records(
        await _call_llm(client, system, user, engine_params=engine_params, max_tokens=max_tokens, json_mode=json_mode),
        target.schema,
    )


async def extract_category(cfg, target, context: str, client, engine_params: dict, engine: str = "BaseExtract") -> list[dict]:
    """BaseExtract 直抽：整段上下文一次给模型（不截断、不分段）。

    LangExtractPkg 由 pipeline 走原包适配器，不进入此函数。
    """
    return await _extract_base(cfg, target, context, client, engine_params)
