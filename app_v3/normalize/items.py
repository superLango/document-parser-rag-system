"""项目名归一化（中英/缩写/单位/硬度）。"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DICT_PATH = Path(__file__).with_name("items.cn_en.json")
HARDNESS_CODES = {
    "HV": "维氏硬度(HV)",
    "HBW": "布氏硬度(HBW)",
    "HB": "布氏硬度(HB)",
    "HRB": "洛氏硬度(HRB)",
    "HRC": "洛氏硬度(HRC)",
}
UNIT_SUFFIX_RE = re.compile(r"(?:MPa|GPa|%|J|kJ|HV|HBW|HB|HRB|HRC|mm|℃)\s*$", re.IGNORECASE)
PAREN_RE = re.compile(r"[（(][^）)]*[）)]")


def clean_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def load_aliases() -> dict[str, str]:
    data = json.loads(DICT_PATH.read_text(encoding="utf-8"))
    return {str(key).lower().replace(" ", ""): str(value) for key, value in data.get("aliases", {}).items()}


def normalize_item(value: object) -> tuple[str, list[str]]:
    """返回 (规范项目名, 原始/别名列表)。"""
    raw = clean_text(value)
    if not raw:
        return "", []
    aliases = load_aliases()
    text = UNIT_SUFFIX_RE.sub("", raw).strip()
    key = text.lower().replace(" ", "")
    if key in aliases:
        return aliases[key], [raw]
    # 去掉括号后精确匹配
    bare = PAREN_RE.sub("", text).strip()
    bare_key = bare.lower().replace(" ", "")
    if bare_key in aliases:
        return aliases[bare_key], [raw]
    # 硬度代号
    upper = text.upper()
    for code, canonical in HARDNESS_CODES.items():
        if re.search(rf"(?<![A-Z]){code}(?![A-Z])", upper) and "硬度" in text:
            return canonical, [raw]
        if upper == code:
            return canonical, [raw]
    # 子串匹配（长键优先；短键仅精确匹配，避免 Al→A→断后伸长率 之类误配）
    lowered = text.lower().replace(" ", "")
    for alias, canonical in sorted(aliases.items(), key=lambda item: -len(item[0])):
        if len(alias) < 3:
            continue
        if alias and alias in lowered:
            return canonical, [raw]
    return text, [raw]
