"""S18 条款通道：LLM 从页面文本抽取带证据的规范要求记录。"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app_v3.channels.llm_client import chat
from app_v3.normalize.items import normalize_item

INSTRUCTION = """你是标准文档信息抽取器。输入是标准文档的页面文本（含页码标记）。
请抽取所有**明确的定量要求/规定**，输出 JSON 数组（只输出 JSON，不要解释）：
[{"category":"化学成分|室温拉伸|高温拉伸|冲击试验|硬度试验|弯曲试验|高倍|热处理制度|持久试验|蠕变试验|尺寸外形|其他",
  "item":"项目名称（用原文，如 抗拉强度(Rm)、晶粒度、非金属夹杂物、淬火温度）",
  "grade":"材料牌号；若原文是全部牌号/所有牌号，写 全部牌号",
  "requirement":"标准要求原文（含比较符/范围，如 ≤3、≥345、0.1~1.5）",
  "unit":"单位（MPa/%/J/级/℃/mm/HV/HB/HRC 等，可空）",
  "temperature":"试验温度（原文有才写，如 室温/20℃）",
  "direction":"方向（原文有才写，如 纵向/横向）",
  "state":"试样状态（原文有才写，如 退火/淬火）",
  "size":"尺寸/厚度（原文有才写）",
  "method":"试验方法（原文有才写）",
  "page":页码数字,
  "evidence":"原文证据句（不超过120字）"}]
规则：
1. 只抽取有明确数值/等级/要求的内容，不要编造；
2. 表格中的大批量数据只抽代表行/关键要求，避免重复；
3. 材料牌号必须来自原文；不能确定时写空字符串；
4. category 只能取给定值之一。
输入：
"""


def page_chunks(ocr: dict[str, Any], pages_per_chunk: int = 4) -> list[tuple[int, int, str]]:
    pages = sorted(ocr.get("pages") or [], key=lambda page: page.get("page_no") or 0)
    chunks = []
    for start in range(0, len(pages), pages_per_chunk):
        group = pages[start:start + pages_per_chunk]
        text_parts = []
        for page in group:
            page_no = page.get("page_no")
            markdown = str(page.get("markdown") or "")
            text_parts.append(f"\n===== page {page_no} =====\n{markdown}")
        chunks.append((int(group[0].get("page_no") or 0), int(group[-1].get("page_no") or 0), "".join(text_parts)))
    return chunks


def extract_chunk(text: str) -> list[dict[str, Any]]:
    raw = chat(INSTRUCTION + text, max_tokens=8192, timeout=180)
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        records = json.loads(raw[start:end + 1])
    except Exception:
        return []
    output = []
    for item in records if isinstance(records, list) else []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip()
        requirement = str(item.get("requirement") or "").strip()
        if not category or not requirement:
            continue
        item_raw = str(item.get("item") or "").strip()
        if not item_raw:
            continue
        output.append({
            "record_id": "",
            "channel": "clause",
            "category": category,
            "item": normalize_item(item_raw)[0],
            "grade": str(item.get("grade") or "").strip(),
            "requirement": requirement,
            "unit": str(item.get("unit") or "").strip(),
            "conditions": {
                key: str(item.get(key) or "").strip()
                for key in ("temperature", "direction", "state", "size", "method")
                if str(item.get(key) or "").strip()
            },
            "page_no": item.get("page"),
            "evidence": str(item.get("evidence") or "")[:200],
        })
    return output


def extract_document(ocr: dict[str, Any], pages_per_chunk: int = 4, concurrency: int = 3,
                     max_chunks: int = 20) -> list[dict[str, Any]]:
    chunks = page_chunks(ocr, pages_per_chunk)[:max_chunks]
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(extract_chunk, text) for _, _, text in chunks]
        for future in as_completed(futures):
            try:
                records.extend(future.result())
            except Exception:
                continue
    for index, record in enumerate(records):
        record["record_id"] = f"N{index}"
    return records
