"""条件归一化（温度/状态/尺寸/方向/单位）。"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

STATE_ALIASES = {
    "M": "软态(M)",
    "Y": "冷加工态(Y)",
    "R": "热加工态(R)",
    "Y2": "半硬态(Y2)",
    "ST": "固溶退火态(ST)",
    "S": "S",
    "T": "T",
    "O": "O",
    "ANNEALED": "退火",
    "SOLUTION TREATED": "固溶处理",
    "COLD WORKED": "冷加工",
    "HOT WORKED": "热加工",
}
DIRECTION_MAP = {
    "longitudinal": "纵向", "long": "纵向", "l": "纵向", "纵向": "纵向",
    "transverse": "横向", "trans": "横向", "t": "横向", "横向": "横向",
    "short transverse": "短横向", "short-transverse": "短横向", "st": "短横向", "短横向": "短横向",
    "axial": "轴向", "axial direction": "轴向", "轴向": "轴向",
    "radial": "径向", "径向": "径向",
    "tangential": "切向", "切向": "切向",
}
ROOM_WORDS = {"室温", "常温", "rt", "room", "room temperature", "ambient", "室温试验"}
UNIT_ALIASES = {
    "mpa": "MPa", "兆帕": "MPa", "gpa": "GPa", "kpa": "kPa",
    "%": "%", "％": "%", "百分比": "%",
    "j": "J", "焦耳": "J", "kj": "kJ",
    "hbw": "HBW", "hb": "HB", "布氏硬度": "HBW",
    "hrb": "HRB", "hrc": "HRC", "hv": "HV",
    "维氏硬度": "HV", "洛氏硬度": "HRC",
    "mm": "mm", "毫米": "mm", "μm": "μm", "um": "μm", "微米": "μm",
    "℃": "℃", "°c": "℃", "度": "℃",
    "级": "级", "h": "h", "小时": "h", "min": "min",
}
SIZE_RE = re.compile(r"^[≤<>≥]?\s*\d+(?:\.\d+)?(?:\s*(?:~|至|-)\s*\d+(?:\.\d+)?)?\s*(?:mm)?$")
TEMP_RE = re.compile(r"^-?\d+(?:\.\d+)?\s*(?:℃|°C|度)?$")


def clean_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


UNIT_TOKEN_RE = re.compile(r"(HBW|HRB|HRC|HV|HB|GPa|MPa|kPa|%|J|kJ|mm|μm|℃|级|h|min)", re.IGNORECASE)


def normalize_unit(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    token = text.strip().lower()
    if token in UNIT_ALIASES:
        return UNIT_ALIASES[token]
    match = UNIT_TOKEN_RE.search(text)
    if match:
        raw = match.group(1)
        upper = raw.upper()
        if upper in {"HBW", "HRB", "HRC", "HV", "HB", "MPA", "KPA", "GPA"}:
            return {"MPA": "MPa", "KPA": "kPa", "GPA": "GPa"}.get(upper, upper)
        return raw
    return text


def normalize_state(value: Any, aliases: dict[str, str] | None = None) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if aliases and text in aliases:
        return aliases[text]
    upper = text.upper().replace(" ", "")
    if upper in STATE_ALIASES:
        return STATE_ALIASES[upper]
    if aliases and upper in {key.upper(): key for key in aliases}:
        for key, full in aliases.items():
            if key.upper() == upper:
                return full
    return text


def normalize_direction(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    key = text.lower().replace(" ", " ")
    if key in DIRECTION_MAP:
        return DIRECTION_MAP[key]
    if text in DIRECTION_MAP:
        return DIRECTION_MAP[text]
    # 兼容 "纵向/横向"
    parts = [part.strip() for part in re.split(r"[/、,，]", text) if part.strip()]
    mapped = [DIRECTION_MAP.get(part.lower(), part) for part in parts]
    return "/".join(dict.fromkeys(mapped))


def normalize_temperature(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in ROOM_WORDS or text in ROOM_WORDS:
        return "室温"
    match = TEMP_RE.match(text)
    if match:
        number = re.sub(r"\s*(℃|°C|度)\s*$", "", text)
        return f"{number}℃"
    return text


def classify_temperature(value: str) -> str:
    """返回 room / high / low / unknown。"""
    text = clean_text(value)
    if not text:
        return "unknown"
    if normalize_temperature(text) == "室温":
        return "room"
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return "unknown"
    number = float(match.group(0))
    if number < 0:
        return "low"
    if number >= 50:
        return "high"
    return "room" if number <= 35 else "high"


def normalize_size(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if text in {"所有厚度", "全厚度", "全部厚度", "任意厚度"}:
        return text
    compact = re.sub(r"\s+", "", text).replace("～", "~").replace("—", "-").replace("–", "-")
    compact = compact.replace("<=", "≤").replace(">=", "≥")
    if SIZE_RE.match(compact):
        if "mm" not in compact.lower():
            compact = f"{compact}mm"
        return compact
    return text


def normalize_conditions(conditions: dict[str, Any] | None, aliases: dict[str, str] | None = None) -> dict[str, str]:
    """归一化条件字典（保留中文字段名，未知键归入"其他"）。"""
    result: dict[str, str] = {}
    if not conditions:
        return result
    for key, value in conditions.items():
        text = clean_text(value)
        if not text:
            continue
        if key in {"试样状态", "状态"}:
            result["试样状态"] = normalize_state(text, aliases)
        elif key in {"方向"}:
            result["方向"] = normalize_direction(text)
        elif key in {"试验温度", "温度"}:
            result["试验温度"] = normalize_temperature(text)
        elif key in {"尺寸厚度", "尺寸", "规格", "厚度"}:
            result["尺寸厚度"] = normalize_size(text)
        elif key in {"试验方法", "方法"}:
            result["试验方法"] = text
        elif key in {"取样数量"}:
            result["取样数量"] = text
        elif key in {"取样说明"}:
            result["取样说明"] = text
        elif key in {"位置"}:
            result["位置"] = text
        elif key in {"锻件类型"}:
            result["锻件类型"] = text
        else:
            result["其他"] = (result.get("其他", "") + "；" if result.get("其他") else "") + f"{key}:{text}"
    return result
