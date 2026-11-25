"""牌号解析与归一化（S1）。

目标：不依赖具体文档/表类型，通用处理：
- 中英文牌号列识别；
- 多牌号单元格拆分（、,/;；/&/and）；
- 纯字母短代号（如 DN）允许，但排除状态代号（M/Y/R/Y2/ST/S/T）；
- 拒绝表头短语/长句（英文标准常见，如 "Up to 2.000,incl(1)"、"Sheet and strip"）；
- 牌号别名（Ti-6Al-4V ↔ 6Al-4V）。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

GRADE_HEADER_TOKENS_CN = ("牌号", "钢号", "钢种", "材料牌号", "合金牌号", "品种", "型号", "代号", "合金")
GRADE_HEADER_TOKENS_EN = ("grade", "type", "alloy", "uns", "material", "composition", "designation")
STATE_CODES = {
    "M", "Y", "R", "Y2", "ST", "S", "T", "O", "H", "F", "H24", "T4", "T6", "T651",
    "ANNEALED", "SOLUTION", "COLD", "HOT", "ROOM",
}
SPLIT_RE = re.compile(r"[、,，;；/|]+|\s+(?:and|&)\s+", re.IGNORECASE)
PAREN_NOTE_RE = re.compile(r"[（(]([^）)]{0,30})[）)]")
SENTENCE_RE = re.compile(r"[。；;]|适用|规定|文件|本标准|本文件|见表|见第")
# 典型牌号：中英文/数字/连字符，允许 Ti-6Al-4V、N4、NW4-0.07、NMg0.1、6Al-4V、Grade 5、UNS R56400
GRADE_PATTERN = re.compile(
    r"^(?:"
    r"[A-Z]{1,4}[A-Za-z]*-?\d{1,4}(?:[.-]\d{1,4})*(?:[A-Za-z])?"  # N4, NW4-0.07, NCu28-2.5-1.5
    r"|[A-Z][a-z]?[A-Za-z]*-?\d[A-Za-z0-9.-]*"                    # Ti-6Al-4V
    r"|\d[A-Za-z0-9.-]*[A-Za-z][A-Za-z0-9.-]*"                    # 6Al-4V
    r"|\d{3,6}[A-Za-z]?"                                         # 30408
    r"|Grade\s*\d+[A-Za-z]?"                                     # Grade 5
    r"|UNS\s+[A-Z]\d{5}"                                         # UNS R56400
    r"|[A-Z]{2,4}"                                               # DN
    r")$",
    re.IGNORECASE,
)
HEADER_PHRASE_RE = re.compile(
    r"up\s*to|sheet|strip|plate|bar|forging|wire|condition|temper|annealed|solution|cold|hot|"
    r"厚|宽|长|直径|规格|尺寸|状态|产品|板材|棒材|带材|丝材",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def header_is_grade_column(header: str) -> bool:
    text = clean_text(header).lower()
    tokens = tuple(token.lower() for token in GRADE_HEADER_TOKENS_CN + GRADE_HEADER_TOKENS_EN)
    return any(token in text for token in tokens)


def is_state_code(value: str) -> bool:
    return clean_text(value).upper().replace(" ", "") in STATE_CODES


def is_header_phrase(value: str) -> bool:
    """拒绝表头短语/长句/规格说明被当作牌号。"""
    text = clean_text(value)
    if not text:
        return True
    if len(text) > 24:
        return True
    if SENTENCE_RE.search(text):
        return True
    if HEADER_PHRASE_RE.search(text):
        return True
    # 以介词/量词开头的说明性文本
    if re.match(r"^(up\s*to|from|to|for|with|the|all|any|按|见|由|不大于|不小于)", text, re.IGNORECASE):
        return True
    return False


def _strip_notes(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    for match in PAREN_NOTE_RE.finditer(text):
        content = match.group(1).strip()
        if content:
            notes.append(content)
    stripped = PAREN_NOTE_RE.sub("", text).strip()
    return stripped, notes


def normalize_grade(value: str) -> dict[str, list[str]]:
    """规范化单个牌号，返回主牌号与别名。"""
    text = clean_text(value)
    uns_match = re.match(r"^UNS\s+([A-Z]\d{5})$", text, re.IGNORECASE)
    if uns_match:
        code = uns_match.group(1).upper()
        return {"grade": f"UNS {code}", "aliases": [f"UNS{code}"]}
    text = text.replace(" ", "")
    aliases: list[str] = []
    if re.fullmatch(r"[Tt][Ii]-?[0-9A-Za-z.-]+", text):
        bare = re.sub(r"^[Tt][Ii]-?", "", text)
        aliases.append(bare)
    elif re.fullmatch(r"\d+[A-Za-z][0-9A-Za-z.-]*", text) and re.search(r"\d[A-Z]|[A-Z]\d", text):
        aliases.append(f"Ti-{text}")
    if re.fullmatch(r"Grade\s*\d+[A-Za-z]?", value or "", re.IGNORECASE):
        text = re.sub(r"\s+", " ", clean_text(value))
    return {"grade": text, "aliases": list(dict.fromkeys(aliases))}


def parse_grade_cell(value: Any, header: str = "") -> dict[str, list[Any]]:
    """解析一个牌号单元格。

    返回 {"grades": [{"grade","aliases"}], "rejected": [...]}。
    """
    raw = clean_text(value)
    result: list[dict[str, Any]] = []
    rejected: list[str] = []
    if not raw:
        return {"grades": [], "rejected": []}
    in_grade_column = header_is_grade_column(header)
    parts = SPLIT_RE.split(raw) if SPLIT_RE.search(raw) else [raw]
    for part in parts:
        candidate = clean_text(part)
        if not candidate:
            continue
        stripped, notes = _strip_notes(candidate)
        if not stripped:
            continue
        # 括号注释可能是状态/说明，不当牌号
        if notes and re.search(r"状态|态|处理|mm|MPa|%", " ".join(notes)):
            rejected.append(candidate)
            continue
        if is_header_phrase(stripped):
            rejected.append(candidate)
            continue
        if in_grade_column and "grade" in header.lower() and re.fullmatch(r"\d{1,3}[A-Za-z]?", stripped):
            result.append(normalize_grade(f"Grade {stripped}"))
            continue
        if in_grade_column and "uns" in header.lower() and re.fullmatch(r"[A-Z]\d{5}", stripped):
            result.append({"grade": f"UNS {stripped}", "aliases": [stripped]})
            continue
        if is_state_code(stripped) and not in_grade_column:
            rejected.append(candidate)
            continue
        # 纯小写字母通常是说明性单词（如 "incl"），不作为牌号
        if re.fullmatch(r"[a-z]{2,12}", stripped):
            rejected.append(candidate)
            continue
        if not GRADE_PATTERN.match(stripped):
            # 纯字母短代号仅在牌号列允许（且非状态）
            if in_grade_column and re.fullmatch(r"[A-Za-z]{2,4}", stripped) and not is_state_code(stripped):
                result.append(normalize_grade(stripped))
            else:
                rejected.append(candidate)
            continue
        result.append(normalize_grade(stripped))
    # 去重
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result:
        key = item["grade"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return {"grades": unique, "rejected": rejected}


def split_grade_values(value: Any, header: str = "牌号") -> list[str]:
    """便捷函数：返回单元格拆分后的牌号字符串列表。"""
    return [item["grade"] for item in parse_grade_cell(value, header=header).get("grades") or []]


def choose_grade_columns(headers: Iterable[str]) -> list[int]:
    columns: list[int] = []
    for index, header in enumerate(headers):
        if header_is_grade_column(header):
            columns.append(index)
    return columns
