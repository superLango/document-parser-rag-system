#!/usr/bin/env python3
"""Evaluate pipeline records against the 30-document human gold standard.

The gold corpus uses the fixed ``product_standard/1`` schema (13 item fields +
12 heat-treatment fields).  Pipeline records use ``grade / conditions /
properties``; this script adapts them into the same fixed field names, matches
rows by ``(项目大类, 项目名称, 材料牌号)`` and compares ``标准要求``.

Run from ``new_app``::

    python scripts/benchmark/gold_registry.py --refresh-api
    python scripts/benchmark/gold_eval.py
    python scripts/benchmark/gold_eval.py --gate --min-f1 0.80 --max-silent 0.02
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from teds import teds_score  # noqa: E402

NEW_APP_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = NEW_APP_DIR.parent
GOLD_DIR = REPO_ROOT / "gold_standard_30"
REPORT_DIR = NEW_APP_DIR / "docs" / "reports"
DEFAULT_REGISTRY = REPORT_DIR / "gold-registry.json"
DEFAULT_OUT_JSON = REPORT_DIR / "gold-eval.json"
DEFAULT_OUT_MD = REPORT_DIR / "gold-eval.md"

ITEM_FIELDS = (
    "项目名称",
    "材料牌号",
    "标准要求",
    "单位",
    "试验方法",
    "试验温度",
    "位置",
    "方向",
    "尺寸厚度",
    "试样状态",
    "取样数量",
    "取样说明",
    "锻件类型",
)
COND_FIELDS = ("试验温度", "位置", "方向", "尺寸厚度", "试样状态")
HARDNESS = {"布氏硬度", "洛氏硬度", "维氏硬度"}
# Prose/qualitative categories added on 2026-11-15; they are scored by feature
# coverage and must not change the historical numeric F1 baseline.
QUALITATIVE_FEATURES = {
    "低倍",
    "高倍组织",
    "晶粒度",
    "非金属夹杂",
    "超声波检测",
    "涡流检测",
    "铁素体",
    "外观",
    "尺寸",
    "相变温度",
    "晶间腐蚀",
    "脱脂",
    "表面粗糙度",
    "断口",
}

MEASURE_ALIASES = {
    "rm": "抗拉强度",
    "抗拉强度": "抗拉强度",
    "tensilestrength": "抗拉强度",
    "rp0.2": "规定塑性延伸强度",
    "rp0,2": "规定塑性延伸强度",
    "规定塑性延伸强度": "规定塑性延伸强度",
    "规定非比例延伸强度": "规定塑性延伸强度",
    "proofstrength": "规定塑性延伸强度",
    "reh": "上屈服强度",
    "上屈服强度": "上屈服强度",
    "rel": "下屈服强度",
    "下屈服强度": "下屈服强度",
    "a": "断后伸长率",
    "a50mm": "断后伸长率",
    "a5.65": "断后伸长率",
    "δ5": "断后伸长率",
    "断后伸长率": "断后伸长率",
    "z": "断面收缩率",
    "ψ": "断面收缩率",
    "断面收缩率": "断面收缩率",
    "kv2": "冲击吸收能量",
    "ku2": "冲击吸收能量",
    "KV2": "冲击吸收能量",
    "KU2": "冲击吸收能量",
    "KU5": "冲击吸收能量",
    "侧膨胀值": "侧膨胀值",
    "侧向膨胀值": "侧膨胀值",
    "aku": "冲击吸收能量",
    "冲击吸收能量": "冲击吸收能量",
    "冲击吸收功": "冲击吸收能量",
    "hb": "布氏硬度",
    "hbw": "布氏硬度",
    "布氏硬度": "布氏硬度",
    "hrc": "洛氏硬度",
    "hrb": "洛氏硬度",
    "洛氏硬度": "洛氏硬度",
    "hv": "维氏硬度",
    "维氏硬度": "维氏硬度",
    "kic": "断裂韧度",
    "KIC": "断裂韧度",
    "断裂韧度": "断裂韧度",
    "bend": "弯曲试验",
    "弯曲": "弯曲试验",
    "弯曲试验": "弯曲试验",
    "持久时间": "蠕变断裂时间",
    "蠕变断裂时间": "蠕变断裂时间",
    "cev": "碳当量",
    "碳当量": "碳当量",
    "pcm": "Pcm",
}

ELEMENT_NAMES = {
    "aluminium": "Al",
    "aluminum": "Al",
    "vanadium": "V",
    "iron": "Fe",
    "oxygen": "O",
    "carbon": "C",
    "nitrogen": "N",
    "hydrogen": "H",
    "titanium": "Ti",
    "zirconium": "Zr",
    "silicon": "Si",
    "manganese": "Mn",
    "magnesium": "Mg",
    "chromium": "Cr",
    "copper": "Cu",
    "zinc": "Zn",
    "molybdenum": "Mo",
    "nickel": "Ni",
    "cobalt": "Co",
    "boron": "B",
    "lead": "Pb",
    "bismuth": "Bi",
    "selenium": "Se",
    "palladium": "Pd",
    "ruthenium": "Ru",
    "niobium": "Nb",
    "columbium(niobium)": "Nb",
    "tantalum": "Ta",
    "tungsten": "W",
    "tin": "Sn",
    "antimony": "Sb",
    "arsenic": "As",
    "cadmium": "Cd",
    "beryllium": "Be",
    "tellurium": "Te",
    "yttrium": "Y",
    "silver": "Ag",
    "phosphorus": "P",
    "sulfur": "S",
    "sulphur": "S",
    "calcium": "Ca",
    "lithium": "Li",
    "potassium": "K",
    "hafnium": "Hf",
    "sodium": "Na",
    "cerium": "Ce",
    "lanthanum": "La",
    "neodymium": "Nd",
    "praseodymium": "Pr",
    "gadolinium": "Gd",
    "dysprosium": "Dy",
    "erbium": "Er",
}

UNIT_PATTERN = re.compile(r"(mpa|gpa|%|℃|°c|mm|kg/mm2|hrc|hbw|hv)", re.I)
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def nfkc(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or ""))


def compact(value: Any) -> str:
    return re.sub(r"\s+", "", nfkc(value)).lower()


def canon_grade(value: Any) -> str:
    text = nfkc(value).strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^UNS", "", text, flags=re.I)
    text = re.sub(r"^ALLOY", "", text, flags=re.I)
    text = text.replace("牌号", "")
    # Descriptive names embed the UNS designation, e.g.
    # "90%tantalum-10%tungsten(R05255)" -> "r05255".
    uns = re.search(r"(?<![A-Za-z0-9])([A-Z]\d{5})(?![0-9])", text)
    if uns:
        return uns.group(1).lower()
    # ASTM/AMS grades often carry footnote lists, e.g. ``2HB,C`` -> ``2H``.
    text = re.sub(r"^(\d+[A-Z])[A-Z](?:,[A-Z])+$", r"\1", text)
    text = re.sub(r",[A-Z](?:,[A-Z])*$", "", text)
    return text.lower()


def split_grades(value: Any) -> list[str]:
    text = nfkc(value).strip()
    if re.fullmatch(r"\d+[A-Z][A-Z](?:,[A-Z])+", text):
        return [canon_grade(text)]
    parts = [part.strip() for part in re.split(r"[、/，,；;]", text) if part.strip()]
    if len(parts) <= 1:
        return [canon_grade(text)] if text else [""]
    base = parts[0]
    prefix = re.sub(r"[A-Za-z]$", "", base)
    expanded = [base]
    for part in parts[1:]:
        if re.fullmatch(r"[A-Za-z]{1,2}", part):
            expanded.append(f"{base}{part}" if base.isdigit() else f"{prefix}{part}")
        else:
            expanded.append(part)
    return [canon_grade(item) for item in expanded]


ELEMENT_SYMBOLS = set(ELEMENT_NAMES.values())
MECH_NAMES = {
    "抗拉强度",
    "规定塑性延伸强度",
    "上屈服强度",
    "下屈服强度",
    "断后伸长率",
    "断面收缩率",
    "冲击吸收能量",
    "布氏硬度",
    "洛氏硬度",
    "维氏硬度",
    "断裂韧度",
    "弯曲试验",
    "蠕变断裂时间",
}
NUMERIC_REQ = re.compile(r"^(?:[≥≤<>]?[\d.]+(?:~[≥≤<>]?[\d.]+)?|余量)$")
PLACEHOLDER_REQS = {"~", "-", "—", "/", "...", "…"}


def is_chem_measure(name: str) -> bool:
    if name in {"碳当量", "Pcm", "Als"} or name.startswith("其他元素"):
        return True
    if "+" in name:
        return True
    return name in ELEMENT_SYMBOLS


def is_numeric_requirement(text: str) -> bool:
    return bool(NUMERIC_REQ.fullmatch(canon_req(text)))


def canon_element(value: Any) -> str:
    text = compact(value)
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = text.replace(" ", "").replace("-", "")
    if text in ELEMENT_NAMES:
        return ELEMENT_NAMES[text]
    if re.fullmatch(r"[a-z]{1,3}(?:\+[a-z]{1,3})?", text):
        return "+".join(part.capitalize() for part in text.split("+"))
    return text


def canon_measure(value: Any, feature: str) -> str:
    text = compact(value)
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    if feature == "化学成分":
        if text in {"cev", "碳当量cev"}:
            return "碳当量"
        if text in {"pcm", "焊接裂纹敏感性指数pcm"}:
            return "Pcm"
        if text == "als":
            return "Als"
        return canon_element(text)
    if text in MEASURE_ALIASES:
        return MEASURE_ALIASES[text]
    for prefix in (
        "抗拉强度",
        "规定塑性延伸强度",
        "规定非比例延伸强度",
        "上屈服强度",
        "下屈服强度",
        "断后伸长率",
        "断面收缩率",
        "冲击吸收能量",
        "冲击吸收功",
        "布氏硬度",
        "洛氏硬度",
        "维氏硬度",
        "断裂韧度",
        "弯曲",
        "蠕变断裂时间",
        "持久",
    ):
        if text.startswith(prefix):
            return MEASURE_ALIASES.get(prefix, prefix)
    return text


def canon_req(value: Any) -> str:
    text = nfkc(value)
    text = text.replace("不大于", "≤").replace("不小于", "≥")
    text = text.replace("<=", "≤").replace(">=", "≥")
    text = text.replace("≦", "≤").replace("⩽", "≤").replace("≧", "≥").replace("⩾", "≥")
    text = text.replace("～", "~").replace("—", "~").replace("–", "~").replace("−", "-")
    text = text.replace("－", "-").replace("＿", "_")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    text = UNIT_PATTERN.sub("", text)
    text = re.sub(r"(?<=\d)[a-z]$", "", text)
    text = NUMBER_PATTERN.sub(lambda match: format(float(match.group(0)), "g"), text)
    return text


def canon_condition(value: Any) -> str:
    text = nfkc(value)
    text = text.replace("＞", ">").replace("＜", "<").replace("～", "~").replace("—", "~")
    text = text.replace("－", "-")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    text = NUMBER_PATTERN.sub(lambda match: format(float(match.group(0)), "g"), text)
    return text


def req_from_property(prop: dict[str, Any], measure_name: str = "") -> str:
    raw = str(prop.get("raw") or "").strip()
    value = prop.get("value")
    column = str(prop.get("column") or "")
    operator = str(prop.get("operator") or "").strip()
    if not raw and value is None:
        return ""
    if raw in {"不大于", "不小于", "不小于或等于", "不大于或等于"}:
        return ""
    text = raw
    if not re.search(r"[≥≤<>~]", text):
        lowered = column.lower()
        if operator in {"≥", "≤", "<", ">"}:
            text = f"{operator}{text}"
        elif "不小于" in column or re.search(r"\bmin\b|minimum|not less than", lowered):
            text = f"≥{text}"
        elif "不大于" in column or re.search(r"\bmax\b|maximum|not more than", lowered):
            text = f"≤{text}"
        elif "小于" in column:
            text = f"<{text}"
        elif "大于" in column:
            text = f">{text}"
        elif measure_name in {
            "抗拉强度",
            "屈服强度",
            "规定塑性延伸强度",
            "规定非比例延伸强度",
            "上屈服强度",
            "下屈服强度",
            "断后伸长率",
            "断面收缩率",
            "冲击吸收能量",
        } or measure_name.startswith("断裂韧度"):
            # AMS/ASTM 性能表只印数值，最低值语义由标准条款给出（金标统一 ≥）。
            text = f"≥{text}"
    return text


def map_conditions(conditions: dict[str, Any]) -> dict[str, str]:
    mapped = {field: "" for field in COND_FIELDS}
    extras: list[str] = []
    for key, value in (conditions or {}).items():
        text = compact(key)
        val = str(value or "").strip()
        if not val:
            continue
        target = ""
        if any(token in text for token in ("厚度", "尺寸", "直径", "规格", "壁厚", "外径", "内径")):
            target = "尺寸厚度"
        elif "温度" in text:
            target = "试验温度"
        elif "方向" in text:
            target = "方向"
        elif any(token in text for token in ("位置", "部位")):
            target = "位置"
        elif any(
            token in text
            for token in ("状态", "交货", "热处理", "表面", "形式", "品种", "状态")
        ):
            target = "试样状态"
        elif "试验方法" in text or text in {"方法", "检验方法"}:
            target = "试验方法"
        elif "取样数量" in text or "试样数量" in text:
            target = "取样数量"
        elif "取样说明" in text:
            target = "取样说明"
        elif "锻件类型" in text:
            target = "锻件类型"
        if target:
            mapped[target] = f"{mapped[target]}；{val}" if mapped.get(target) else val
        else:
            extras.append(f"{key}={val}")
    mapped["_extras"] = "；".join(extras)
    return mapped


def infer_feature(
    profile: str, measure: str, conditions: dict[str, str], record: dict[str, Any]
) -> str | None:
    if profile == "chemical_composition":
        return "化学成分"
    if profile in {"heat_treatment", "heat-treatment", "heat_treatment_rule"}:
        return "热处理制度"
    if measure in HARDNESS:
        return measure
    if measure == "冲击吸收能量":
        return "夏比冲击"
    if measure == "断裂韧度":
        return "断裂韧度"
    if measure == "蠕变断裂时间":
        return "高温光滑持久"
    if measure.startswith("弯曲"):
        return "弯曲"
    text = (
        str(record.get("condition_key") or "")
        + conditions.get("试样状态", "")
        + conditions.get("试验温度", "")
    )
    temperature = str(conditions.get("试验温度") or "")
    numeric_temperature = re.search(r"(\d{2,4})", temperature)
    if numeric_temperature and int(numeric_temperature.group(1)) >= 100:
        return "高温拉伸"
    if "高温" in text:
        return "高温拉伸"
    if "低温" in text:
        return "低温拉伸"
    return "室温拉伸"


def adapt_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    profile = str(record.get("profile") or "")
    grades = split_grades(record.get("grade"))
    conditions = map_conditions(record.get("conditions") or {})
    record_fields = record.get("conditions") or {}
    rows: list[dict[str, Any]] = []
    for measure, prop in (record.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        meta = prop.get("meta") if isinstance(prop.get("meta"), dict) else {}
        chem_name = canon_measure(measure, "化学成分")
        mech_name = canon_measure(measure, "")
        if profile == "chemical_composition" and is_chem_measure(chem_name):
            name, feature = chem_name, "化学成分"
        else:
            name = mech_name
            feature = infer_feature("", name, conditions, record)
        if not feature:
            continue
        requirement = req_from_property(prop, name)
        if not requirement or not is_numeric_requirement(requirement):
            continue
        for grade in grades:
            rows.append(
                {
                    "feature": feature,
                    "项目名称": name,
                    "材料牌号": grade,
                    "标准要求": canon_req(requirement),
                    "单位": str(prop.get("unit") or ""),
                    "试验方法": str(
                        meta.get("试验方法") or record_fields.get("试验方法") or ""
                    ),
                    "试验温度": conditions["试验温度"],
                    "位置": str(meta.get("位置") or conditions["位置"] or ""),
                    "方向": conditions["方向"],
                    "尺寸厚度": conditions["尺寸厚度"],
                    "试样状态": conditions["试样状态"],
                    "取样数量": str(
                        meta.get("取样数量") or record_fields.get("取样数量") or ""
                    ),
                    "取样说明": str(
                        meta.get("取样说明") or record_fields.get("取样说明") or ""
                    ),
                    "锻件类型": str(
                        meta.get("锻件类型") or record_fields.get("锻件类型") or ""
                    ),
                    "_page": record.get("page_no"),
                    "_record_id": record.get("record_id") or "",
                    "_measure": measure,
                }
            )
    return rows


def adapt_heat_record(record: dict[str, Any]) -> dict[str, Any]:
    """Adapt a pipeline heat_treatment record to the 6 comparable gold fields."""
    properties = record.get("properties") or {}
    conditions = record.get("conditions") or {}

    def raw(name: str) -> str:
        return compact((properties.get(name) or {}).get("raw") or "")

    process = ""
    for key in ("工序名称", "工序", "状态"):
        if compact(conditions.get(key)):
            process = compact(conditions[key])
            break
    return {
        "材料牌号": canon_grade(record.get("grade")),
        "工序名称": process,
        "项目大类": "热处理制度",
        "保温温度": canon_req(raw("保温温度")),
        "保温时间": compact(raw("保温时间")),
        "冷却介质": compact(raw("冷却介质")),
    }


def load_gold_rows(doc_id: str) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    payload = json.loads((GOLD_DIR / "documents" / f"{doc_id}.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    qualitative: list[dict[str, Any]] = []
    placeholders = 0
    for category in payload.get("categories") or []:
        feature = str(category.get("feature") or "")
        if feature in {"标准信息", "热处理制度"}:
            continue
        for record in category.get("records") or []:
            requirement = canon_req(record.get("标准要求"))
            if requirement in PLACEHOLDER_REQS:
                placeholders += 1
                continue
            if not requirement:
                continue
            item = {
                "feature": feature,
                "项目名称": canon_measure(record.get("项目名称"), feature),
                "材料牌号": canon_grade(record.get("材料牌号")),
                "标准要求": requirement,
                "单位": str(record.get("单位") or ""),
                "试验方法": str(record.get("试验方法") or ""),
                "试验温度": str(record.get("试验温度") or ""),
                "位置": str(record.get("位置") or ""),
                "方向": str(record.get("方向") or ""),
                "尺寸厚度": str(record.get("尺寸厚度") or ""),
                "试样状态": str(record.get("试样状态") or ""),
                "取样数量": record.get("取样数量") or "",
                "取样说明": str(record.get("取样说明") or ""),
                "锻件类型": str(record.get("锻件类型") or ""),
            }
            if feature in QUALITATIVE_FEATURES:
                qualitative.append(item)
            else:
                rows.append(item)
    return rows, placeholders, qualitative


def load_gold_heat(doc_id: str) -> list[dict[str, Any]]:
    payload = json.loads((GOLD_DIR / "documents" / f"{doc_id}.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for category in payload.get("categories") or []:
        if category.get("feature") != "热处理制度":
            continue
        for record in category.get("records") or []:
            rows.append(
                {
                    "材料牌号": canon_grade(record.get("材料牌号")),
                    "工序名称": compact(record.get("工序名称")),
                    "项目大类": str(record.get("项目大类") or ""),
                    "保温温度": canon_req(record.get("保温温度")),
                    "保温时间": compact(record.get("保温时间")),
                    "冷却介质": compact(record.get("冷却介质")),
                }
            )
    return rows


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (row["feature"], row["项目名称"], row["材料牌号"])


def condition_score(gold: dict[str, Any], pred: dict[str, Any]) -> int:
    score = 0
    for field in COND_FIELDS:
        gold_value = canon_condition(gold.get(field))
        pred_value = canon_condition(pred.get(field))
        if not gold_value or not pred_value:
            continue
        score += 1 if gold_value == pred_value else -1
    return score


def qualitative_metrics(
    gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Feature-level coverage for prose/qualitative requirements."""
    gold_features = {row["feature"] for row in gold_rows if row.get("feature")}
    pred_features = {row["feature"] for row in pred_rows if row.get("feature")}
    matched = gold_features & pred_features
    gold_reqs: dict[str, list[str]] = defaultdict(list)
    pred_reqs: dict[str, list[str]] = defaultdict(list)
    for row in gold_rows:
        gold_reqs[row["feature"]].append(compact(row.get("标准要求")))
    for row in pred_rows:
        pred_reqs[row["feature"]].append(compact(row.get("标准要求")))
    requirement_hits = 0
    for feature in matched:
        if any(
            gold and pred and (gold in pred or pred in gold)
            for gold in gold_reqs.get(feature, [])
            for pred in pred_reqs.get(feature, [])
        ):
            requirement_hits += 1
    return {
        "gold_features": len(gold_features),
        "pred_features": len(pred_features),
        "matched_features": len(matched),
        "feature_recall": round(len(matched) / len(gold_features), 4)
        if gold_features
        else 0.0,
        "requirement_hits": requirement_hits,
        "requirement_rate": round(requirement_hits / len(matched), 4)
        if matched
        else 0.0,
        "missing_features": sorted(gold_features - pred_features),
        "extra_features": sorted(pred_features - gold_features),
    }


def match_rows(
    gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    gold_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    pred_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in gold_rows:
        gold_by_key[row_key(row)].append(row)
    for row in pred_rows:
        pred_by_key[row_key(row)].append(row)

    matched = 0
    pred_common = 0
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for key, predictions in pred_by_key.items():
        golds = gold_by_key.get(key)
        if not golds:
            continue
        pred_common += len(predictions)
        used: set[int] = set()
        for prediction in predictions:
            best_index = None
            best_score = -10_000
            for index, gold in enumerate(golds):
                if index in used:
                    continue
                if prediction["标准要求"] != gold["标准要求"]:
                    continue
                score = condition_score(gold, prediction)
                if score > best_score:
                    best_index = index
                    best_score = score
            if best_index is None:
                continue
            used.add(best_index)
            matched += 1
            pairs.append((golds[best_index], prediction))

    gold_total = len(gold_rows)
    pred_total = len(pred_rows)
    precision = matched / pred_total if pred_total else 0.0
    recall = matched / gold_total if gold_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    silent = pred_common - matched
    return {
        "gold": gold_total,
        "pred": pred_total,
        "matched": matched,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "pred_common": pred_common,
        "silent": silent,
        "silent_rate": round(silent / pred_common, 4) if pred_common else 0.0,
        "pairs": pairs,
    }


def top_missing(
    gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]], limit: int = 8
) -> list[dict[str, Any]]:
    gold_counter = Counter((row["feature"], row["项目名称"]) for row in gold_rows)
    pred_counter = Counter((row["feature"], row["项目名称"]) for row in pred_rows)
    missing = []
    for (feature, name), count in gold_counter.items():
        gap = count - pred_counter.get((feature, name), 0)
        if gap > 0:
            missing.append({"feature": feature, "name": name, "missing": gap})
    missing.sort(key=lambda item: item["missing"], reverse=True)
    return missing[:limit]


def top_extra(
    gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]], limit: int = 8
) -> list[dict[str, Any]]:
    gold_counter = Counter((row["feature"], row["项目名称"]) for row in gold_rows)
    pred_counter = Counter((row["feature"], row["项目名称"]) for row in pred_rows)
    extra = []
    for (feature, name), count in pred_counter.items():
        gap = count - gold_counter.get((feature, name), 0)
        if gap > 0:
            extra.append({"feature": feature, "name": name, "extra": gap})
    extra.sort(key=lambda item: item["extra"], reverse=True)
    return extra[:limit]


def load_records(
    document: dict[str, Any], api: str, records_dir: Path | None
) -> tuple[list[dict[str, Any]], str]:
    if records_dir:
        path = records_dir / f"{document['doc_id']}.json"
        if not path.exists():
            return [], f"missing snapshot {path.name}"
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records") if isinstance(payload, dict) else payload
        return list(records or []), "snapshot"
    run_id = document.get("run_id")
    if not run_id:
        return [], "no run"
    response = httpx.get(f"{api}/v1/runs/{run_id}/records", timeout=60)
    if response.status_code != 200:
        return [], f"records HTTP {response.status_code}"
    return list(response.json().get("records") or []), "api"


PROFILE_BY_TYPE = {
    "chemical": "chemical_composition",
    "mechanical": "mechanical_properties",
    "inspection": "inspection_rules",
}


def table_grid(value: Any) -> list[list[str]]:
    return [list(row) for row in value or []]


def pad_grid(grid: list[list[str]], rows: int, cols: int) -> list[list[str]]:
    padded = []
    for index in range(rows):
        row = list(grid[index][:cols]) if index < len(grid) else []
        padded.append(row + [""] * (cols - len(row)))
    return padded


def grid_hits(
    expected: list[list[str]], actual: list[list[str]]
) -> tuple[int, int]:
    rows = max(len(expected), len(actual))
    cols = max((len(row) for row in expected + actual), default=0)
    if not rows or not cols:
        return 0, 0
    left = pad_grid(expected, rows, cols)
    right = pad_grid(actual, rows, cols)
    hits = 0
    for row_index in range(rows):
        for col_index in range(cols):
            if compact(left[row_index][col_index]) == compact(right[row_index][col_index]):
                hits += 1
    return hits, rows * cols


def load_gold_tables(doc_id: str) -> list[dict[str, Any]]:
    path = GOLD_DIR / "source_tables" / f"{doc_id}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    tables = []
    for table in payload.get("tables") or []:
        header = table_grid(table.get("header_rows"))
        data = table_grid(table.get("data_rows"))
        grid = header + data
        if not grid:
            grid = table_grid(table.get("rows"))
        tables.append(
            {
                "table_id": str(table.get("table_id") or ""),
                "page_no": table.get("page_no"),
                "table_type": str(table.get("table_type") or ""),
                "header_count": len(header),
                "grid": grid,
            }
        )
    return tables


def load_pipeline_artifact(
    run_id: str,
    role: str,
    api: str,
    client: httpx.Client,
    s3: Any,
    bucket: str,
) -> dict[str, Any]:
    if not run_id or s3 is None:
        return {}
    artifacts = client.get(f"{api}/v1/runs/{run_id}/artifacts", timeout=60).json()
    key = next(
        (item.get("storage_key") for item in artifacts or [] if item.get("role") == role),
        None,
    )
    if not key:
        return {}
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return json.loads(body)


def load_pipeline_tables(
    run_id: str,
    api: str,
    client: httpx.Client,
    s3: Any,
    bucket: str,
) -> list[dict[str, Any]]:
    payload = load_pipeline_artifact(run_id, "tables.json", api, client, s3, bucket)
    tables = payload if isinstance(payload, list) else (payload.get("tables") or [])
    return [
        {
            "table_id": str(item.get("table_id") or ""),
            "page_no": item.get("page_no"),
            "profile": str(item.get("profile") or ""),
            "header_count": int(item.get("header_rows") or 0),
            "grid": table_grid(item.get("rows")),
        }
        for item in tables
    ]


def table_metrics(
    gold_tables: list[dict[str, Any]], pred_tables: list[dict[str, Any]]
) -> dict[str, Any]:
    if not gold_tables or not pred_tables:
        return {
            "table_gold": len(gold_tables),
            "table_pred": len(pred_tables),
            "table_matched": 0,
            "table_profile_checked": 0,
            "table_profile_hits": 0,
            "table_header_hits": 0,
            "table_header_total": 0,
            "table_cell_hits": 0,
            "table_cell_total": 0,
            "table_teds": [],
        }
    used: set[int] = set()
    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for gold in gold_tables:
        prediction = next(
            (
                item
                for item in pred_tables
                if item["table_id"] == gold["table_id"] and id(item) not in used
            ),
            None,
        )
        if prediction is None:
            prediction = next(
                (
                    item
                    for item in pred_tables
                    if item["page_no"] == gold["page_no"] and id(item) not in used
                ),
                None,
            )
        if prediction is None:
            continue
        used.add(id(prediction))
        matched.append((gold, prediction))

    profile_checked = 0
    profile_hits = 0
    header_hits = 0
    header_total = 0
    cell_hits = 0
    cell_total = 0
    teds_values: list[float] = []
    for gold, prediction in matched:
        expected_profile = PROFILE_BY_TYPE.get(gold["table_type"])
        if expected_profile:
            profile_checked += 1
            profile_hits += 1 if prediction["profile"] == expected_profile else 0
        gold_header = gold["grid"][: gold["header_count"]]
        pred_header = prediction["grid"][: prediction["header_count"]]
        hits, total = grid_hits(gold_header, pred_header)
        header_hits += hits
        header_total += total
        hits, total = grid_hits(gold["grid"], prediction["grid"])
        cell_hits += hits
        cell_total += total
        if total <= 120:
            teds_values.append(teds_score(gold["grid"], prediction["grid"]))
    return {
        "table_gold": len(gold_tables),
        "table_pred": len(pred_tables),
        "table_matched": len(matched),
        "table_profile_checked": profile_checked,
        "table_profile_hits": profile_hits,
        "table_header_hits": header_hits,
        "table_header_total": header_total,
        "table_cell_hits": cell_hits,
        "table_cell_total": cell_total,
        "table_teds": teds_values,
    }


def evaluate_document(
    document: dict[str, Any],
    api: str,
    records_dir: Path | None,
    dump_dir: Path | None,
    client: httpx.Client | None = None,
    s3: Any = None,
    bucket: str = "",
) -> dict[str, Any]:
    records, source = load_records(document, api, records_dir)
    if dump_dir and source == "api":
        dump_dir.mkdir(parents=True, exist_ok=True)
        (dump_dir / f"{document['doc_id']}.json").write_text(
            json.dumps({"doc_id": document["doc_id"], "run_id": document.get("run_id"),
                        "records": records}, ensure_ascii=False),
            encoding="utf-8",
        )
    pred_rows: list[dict[str, Any]] = []
    heat_pred: list[dict[str, Any]] = []
    qualitative_pred_rows: list[dict[str, Any]] = []
    qualitative_records = 0
    qualitative_properties = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("profile") == "heat_treatment":
            heat_pred.append(adapt_heat_record(record))
            continue
        if record.get("profile") == "qualitative":
            # Prose requirements stay out of the numeric field F1 and are
            # reported separately through feature-level coverage.
            qualitative_records += 1
            for measure, prop in (record.get("properties") or {}).items():
                if not isinstance(prop, dict):
                    continue
                raw = str(prop.get("raw") or "").strip()
                if not raw:
                    continue
                meta = prop.get("meta") if isinstance(prop.get("meta"), dict) else {}
                qualitative_pred_rows.append(
                    {
                        "feature": str(measure),
                        "标准要求": canon_req(raw),
                        "材料牌号": canon_grade(record.get("grade")),
                        "试验方法": str(meta.get("试验方法") or ""),
                    }
                )
            qualitative_properties += len(record.get("properties") or {})
            continue
        pred_rows.extend(adapt_record(record))
    gold_rows, placeholders, gold_qualitative = load_gold_rows(document["doc_id"])
    qualitative = qualitative_metrics(gold_qualitative, qualitative_pred_rows)
    metrics = match_rows(gold_rows, pred_rows)
    feature_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"gold": 0, "pred": 0, "matched": 0}
    )
    for row in gold_rows:
        feature_stats[row["feature"]]["gold"] += 1
    for row in pred_rows:
        feature_stats[row["feature"]]["pred"] += 1
    for gold, _ in metrics["pairs"]:
        feature_stats[gold["feature"]]["matched"] += 1
    heat_gold = load_gold_heat(document["doc_id"])
    heat_metrics = match_heat(heat_gold, heat_pred)
    table_result: dict[str, Any] = {
        "table_gold": len(load_gold_tables(document["doc_id"])),
        "table_pred": 0,
        "table_matched": 0,
        "table_profile_checked": 0,
        "table_profile_hits": 0,
        "table_header_hits": 0,
        "table_header_total": 0,
        "table_cell_hits": 0,
        "table_cell_total": 0,
        "table_teds_sum": 0.0,
        "table_teds_count": 0,
    }
    if s3 is not None:
        try:
            table_client = client or httpx.Client(timeout=60)
            predicted_tables = load_pipeline_tables(
                document.get("run_id") or "", api, table_client, s3, bucket
            )
            table_result = table_metrics(
                load_gold_tables(document["doc_id"]), predicted_tables
            )
            teds_values = table_result.pop("table_teds", [])
            table_result["table_teds_sum"] = round(sum(teds_values), 4)
            table_result["table_teds_count"] = len(teds_values)
        except Exception as exc:  # noqa: BLE001 - table metrics are optional
            table_result["table_error"] = str(exc)[:160]
    intelligence: dict[str, Any] = {}
    intelligence_error = ""
    if s3 is not None and document.get("run_id"):
        try:
            artifact_client = client or httpx.Client(timeout=60)
            payload = load_pipeline_artifact(
                document["run_id"],
                "document_intelligence",
                api,
                artifact_client,
                s3,
                bucket,
            )
            if isinstance(payload, dict):
                intelligence = payload
        except Exception as exc:  # noqa: BLE001 - intelligence metrics are optional
            intelligence_error = str(exc)[:160]
    intel_stats = intelligence.get("stats") or {}
    intel_coverage = intel_stats.get("coverage") or {}
    dictionary = intel_stats.get("dictionary") or {}
    method_filled = sum(1 for row in pred_rows if row.get("试验方法"))
    sampling_filled = sum(
        1
        for row in pred_rows
        if row.get("取样数量") or row.get("位置") or row.get("取样说明")
    )
    unit_hits, unit_checked = unit_accuracy(metrics["pairs"])
    condition_hits, condition_checked = condition_accuracy(metrics["pairs"])
    return {
        "doc_id": document["doc_id"],
        "standard_no": document.get("standard_no") or "",
        "run_id": document.get("run_id") or "",
        "run_status": document.get("run_status") or "",
        "source": source,
        "records": len(records),
        "gold": metrics["gold"],
        "gold_placeholder": placeholders,
        "pred": metrics["pred"],
        "matched": metrics["matched"],
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "f1": metrics["f1"],
        "pred_common": metrics["pred_common"],
        "silent": metrics["silent"],
        "silent_rate": metrics["silent_rate"],
        "unit_hits": unit_hits,
        "unit_checked": unit_checked,
        "unit_accuracy": round(unit_hits / unit_checked, 4) if unit_checked else 0.0,
        "condition_hits": condition_hits,
        "condition_checked": condition_checked,
        "condition_accuracy": round(condition_hits / condition_checked, 4)
        if condition_checked
        else 0.0,
        "qualitative_records": qualitative_records,
        "qualitative_records_artifact": int(
            intel_stats.get("qualitative_records") or 0
        ),
        "qualitative_properties": qualitative_properties,
        "qualitative_items": int(intel_stats.get("qualitative_items") or 0),
        "qualitative_coverage": round(
            int(intel_stats.get("qualitative_records") or 0)
            / int(intel_stats.get("qualitative_items") or 1),
            4,
        )
        if int(intel_stats.get("qualitative_items") or 0)
        else 0.0,
        "qualitative_gold_features": qualitative["gold_features"],
        "qualitative_pred_features": qualitative["pred_features"],
        "qualitative_matched_features": qualitative["matched_features"],
        "qualitative_feature_recall": qualitative["feature_recall"],
        "qualitative_requirement_hits": qualitative["requirement_hits"],
        "qualitative_requirement_rate": qualitative["requirement_rate"],
        "qualitative_missing_features": qualitative["missing_features"],
        "qualitative_extra_features": qualitative["extra_features"],
        "clauses": int(intel_stats.get("clauses") or 0),
        "inventory_items": int(intel_stats.get("inventory_items") or 0),
        "inventory_aligned_ratio": float(intel_coverage.get("aligned_ratio") or 0.0),
        "references": int((intel_stats.get("references") or {}).get("total") or 0),
        "reference_resolution_rate": float(
            (intel_stats.get("references") or {}).get("resolution_rate") or 0.0
        ),
        "method_bindings": int(intel_stats.get("method_bindings") or 0),
        "methods_filled": int(intel_stats.get("methods_filled") or 0),
        "classifications": int(intel_stats.get("classifications") or 0),
        "dictionary_items_checked": int(dictionary.get("items_checked") or 0),
        "dictionary_items_matched": int(dictionary.get("items_matched") or 0),
        "dictionary_hit_rate": float(dictionary.get("hit_rate") or 0.0),
        "dictionary_method_checked": int(dictionary.get("methods_checked") or 0),
        "dictionary_method_matched": int(dictionary.get("methods_matched") or 0),
        "dictionary_method_hit_rate": float(
            dictionary.get("method_hit_rate") or 0.0
        ),
        "dictionary_version": str(dictionary.get("version") or ""),
        "method_filled": method_filled,
        "sampling_filled": sampling_filled,
        "fill_total": len(pred_rows),
        "intelligence_error": intelligence_error,
        **table_result,
        "missing_top": top_missing(gold_rows, pred_rows),
        "extra_top": top_extra(gold_rows, pred_rows),
        "features": dict(feature_stats),
        "heat_gold": heat_metrics["gold"],
        "heat_pred": heat_metrics["pred"],
        "heat_matched": heat_metrics["matched"],
        "heat_f1": heat_metrics["f1"],
    }


def match_heat(
    gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    if not gold_rows or not pred_rows:
        return {"gold": len(gold_rows), "pred": len(pred_rows), "matched": 0, "f1": 0.0}
    # 金标里热处理行的“项目大类”并不一致（GB/T 3280 继承成了“室温拉伸”），
    # 该字段不参与匹配，统一归为“热处理制度”。
    gold_by_key = Counter(
        (row["材料牌号"], row["工序名称"], "热处理制度") for row in gold_rows
    )
    matched = 0
    used: Counter = Counter()
    for row in pred_rows:
        key = (row["材料牌号"], row["工序名称"], "热处理制度")
        limit = gold_by_key.get(key, 0)
        if used[key] < limit:
            used[key] += 1
            matched += 1
    precision = matched / len(pred_rows)
    recall = matched / len(gold_rows)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "gold": len(gold_rows),
        "pred": len(pred_rows),
        "matched": matched,
        "f1": round(f1, 4),
    }


def unit_accuracy(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> tuple[int, int]:
    checked = 0
    hits = 0
    for gold, pred in pairs:
        gold_unit = compact(gold.get("单位"))
        if not gold_unit:
            continue
        checked += 1
        if compact(pred.get("单位")) == gold_unit:
            hits += 1
    return hits, checked


def condition_accuracy(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]]
) -> tuple[int, int]:
    checked = 0
    hits = 0
    for gold, pred in pairs:
        for field in COND_FIELDS:
            gold_value = canon_condition(gold.get(field))
            if not gold_value:
                continue
            checked += 1
            if canon_condition(pred.get(field)) == gold_value:
                hits += 1
    return hits, checked


def aggregate(documents: list[dict[str, Any]]) -> dict[str, Any]:
    gold = sum(item["gold"] for item in documents)
    placeholders = sum(item.get("gold_placeholder", 0) for item in documents)
    pred = sum(item["pred"] for item in documents)
    matched = sum(item["matched"] for item in documents)
    pred_common = sum(item["pred_common"] for item in documents)
    silent = sum(item["silent"] for item in documents)
    precision = matched / pred if pred else 0.0
    recall = matched / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    heat_gold = sum(item["heat_gold"] for item in documents)
    heat_pred = sum(item["heat_pred"] for item in documents)
    heat_matched = sum(item["heat_matched"] for item in documents)
    unit_hits = sum(item.get("unit_hits", 0) for item in documents)
    unit_checked = sum(item.get("unit_checked", 0) for item in documents)
    condition_hits = sum(item.get("condition_hits", 0) for item in documents)
    condition_checked = sum(item.get("condition_checked", 0) for item in documents)
    table_gold = sum(item.get("table_gold", 0) for item in documents)
    table_pred = sum(item.get("table_pred", 0) for item in documents)
    table_matched = sum(item.get("table_matched", 0) for item in documents)
    table_profile_checked = sum(item.get("table_profile_checked", 0) for item in documents)
    table_profile_hits = sum(item.get("table_profile_hits", 0) for item in documents)
    table_header_hits = sum(item.get("table_header_hits", 0) for item in documents)
    table_header_total = sum(item.get("table_header_total", 0) for item in documents)
    table_cell_hits = sum(item.get("table_cell_hits", 0) for item in documents)
    table_cell_total = sum(item.get("table_cell_total", 0) for item in documents)
    table_teds_sum = sum(item.get("table_teds_sum", 0.0) for item in documents)
    table_teds_count = sum(item.get("table_teds_count", 0) for item in documents)
    clauses = sum(item.get("clauses", 0) for item in documents)
    inventory_items = sum(item.get("inventory_items", 0) for item in documents)
    aligned_docs = [
        item for item in documents if item.get("inventory_items")
    ]
    inventory_aligned_ratio = (
        round(
            sum(item.get("inventory_aligned_ratio", 0.0) for item in aligned_docs)
            / len(aligned_docs),
            4,
        )
        if aligned_docs
        else 0.0
    )
    qualitative_records_artifact = sum(
        item.get("qualitative_records_artifact", 0) for item in documents
    )
    qualitative_items = sum(item.get("qualitative_items", 0) for item in documents)
    references = sum(item.get("references", 0) for item in documents)
    reference_docs = [item for item in documents if item.get("references")]
    reference_resolution_rate = (
        round(
            sum(item.get("reference_resolution_rate", 0.0) for item in reference_docs)
            / len(reference_docs),
            4,
        )
        if reference_docs
        else 0.0
    )
    method_bindings = sum(item.get("method_bindings", 0) for item in documents)
    methods_filled = sum(item.get("methods_filled", 0) for item in documents)
    classifications = sum(item.get("classifications", 0) for item in documents)
    dictionary_items_checked = sum(
        item.get("dictionary_items_checked", 0) for item in documents
    )
    dictionary_items_matched = sum(
        item.get("dictionary_items_matched", 0) for item in documents
    )
    dictionary_method_checked = sum(
        item.get("dictionary_method_checked", 0) for item in documents
    )
    dictionary_method_matched = sum(
        item.get("dictionary_method_matched", 0) for item in documents
    )
    dictionary_version = next(
        (item.get("dictionary_version") for item in documents if item.get("dictionary_version")),
        "",
    )
    qualitative_gold_features = sum(
        item.get("qualitative_gold_features", 0) for item in documents
    )
    qualitative_pred_features = sum(
        item.get("qualitative_pred_features", 0) for item in documents
    )
    qualitative_matched_features = sum(
        item.get("qualitative_matched_features", 0) for item in documents
    )
    qualitative_requirement_hits = sum(
        item.get("qualitative_requirement_hits", 0) for item in documents
    )
    method_filled = sum(item.get("method_filled", 0) for item in documents)
    sampling_filled = sum(item.get("sampling_filled", 0) for item in documents)
    fill_total = sum(item.get("fill_total", 0) for item in documents)
    return {
        "documents": len(documents),
        "documents_with_pred": sum(1 for item in documents if item["pred"]),
        "gold": gold,
        "gold_placeholder": placeholders,
        "gold_all": gold + placeholders,
        "pred": pred,
        "matched": matched,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "pred_common": pred_common,
        "silent": silent,
        "silent_rate": round(silent / pred_common, 4) if pred_common else 0.0,
        "coverage": round(
            sum(1 for item in documents if item["pred"]) / len(documents), 4
        )
        if documents
        else 0.0,
        "unit_accuracy": round(unit_hits / unit_checked, 4) if unit_checked else 0.0,
        "condition_accuracy": round(condition_hits / condition_checked, 4)
        if condition_checked
        else 0.0,
        "unit_checked": unit_checked,
        "condition_checked": condition_checked,
        "table_gold": table_gold,
        "table_pred": table_pred,
        "table_matched": table_matched,
        "table_match_rate": round(table_matched / table_gold, 4) if table_gold else 0.0,
        "table_profile_accuracy": round(table_profile_hits / table_profile_checked, 4)
        if table_profile_checked
        else 0.0,
        "table_header_accuracy": round(table_header_hits / table_header_total, 4)
        if table_header_total
        else 0.0,
        "table_cell_accuracy": round(table_cell_hits / table_cell_total, 4)
        if table_cell_total
        else 0.0,
        "table_teds": round(table_teds_sum / table_teds_count, 4)
        if table_teds_count
        else 0.0,
        "heat_gold": heat_gold,
        "heat_pred": heat_pred,
        "heat_matched": heat_matched,
        "heat_f1": round(
            2 * (heat_matched / heat_pred) * (heat_matched / heat_gold)
            / ((heat_matched / heat_pred) + (heat_matched / heat_gold)),
            4,
        )
        if heat_pred and heat_gold and heat_matched
        else 0.0,
        "clauses": clauses,
        "inventory_items": inventory_items,
        "inventory_aligned_ratio": inventory_aligned_ratio,
        "qualitative_records": qualitative_records_artifact,
        "qualitative_items": qualitative_items,
        "qualitative_coverage": round(
            qualitative_records_artifact / qualitative_items, 4
        )
        if qualitative_items
        else 0.0,
        "qualitative_gold_features": qualitative_gold_features,
        "qualitative_pred_features": qualitative_pred_features,
        "qualitative_matched_features": qualitative_matched_features,
        "qualitative_feature_recall": round(
            qualitative_matched_features / qualitative_gold_features, 4
        )
        if qualitative_gold_features
        else 0.0,
        "qualitative_requirement_hits": qualitative_requirement_hits,
        "qualitative_requirement_rate": round(
            qualitative_requirement_hits / qualitative_matched_features, 4
        )
        if qualitative_matched_features
        else 0.0,
        "references": references,
        "reference_resolution_rate": reference_resolution_rate,
        "method_bindings": method_bindings,
        "methods_filled": methods_filled,
        "classifications": classifications,
        "dictionary_version": dictionary_version,
        "dictionary_hit_rate": round(
            dictionary_items_matched / dictionary_items_checked, 4
        )
        if dictionary_items_checked
        else 0.0,
        "dictionary_method_hit_rate": round(
            dictionary_method_matched / dictionary_method_checked, 4
        )
        if dictionary_method_checked
        else 0.0,
        "method_fill_rate": round(method_filled / fill_total, 4)
        if fill_total
        else 0.0,
        "sampling_fill_rate": round(sampling_filled / fill_total, 4)
        if fill_total
        else 0.0,
        "fill_total": fill_total,
    }


def aggregate_features(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"gold": 0, "pred": 0, "matched": 0}
    )
    for document in documents:
        for feature, values in (document.get("features") or {}).items():
            stats[feature]["gold"] += values["gold"]
            stats[feature]["pred"] += values["pred"]
            stats[feature]["matched"] += values["matched"]
    output: dict[str, dict[str, Any]] = {}
    for feature, values in sorted(stats.items()):
        precision = values["matched"] / values["pred"] if values["pred"] else 0.0
        recall = values["matched"] / values["gold"] if values["gold"] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        output[feature] = {
            "gold": values["gold"],
            "pred": values["pred"],
            "matched": values["matched"],
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return output


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# 金标评测报告（30 份人工金标）",
        "",
        f"> 生成时间：{payload['generated_at']}",
        f"> 金标：{summary['documents']} 份 / {summary['gold']} 条可评测 items"
        f"（另有 {summary['gold_placeholder']} 条占位行不计入）",
        f"> 结论：Field F1 **{summary['f1']:.4f}**，静默错误率 "
        f"**{summary['silent_rate']:.4f}**，覆盖率 **{summary['coverage']:.4f}**",
        "",
        "## 1. 总览",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 金标 items（可评测） | {summary['gold']} |",
        f"| 金标占位行（`~`/`-`/`...`） | {summary['gold_placeholder']} |",
        f"| 金标 items 合计 | {summary['gold_all']} |",
        f"| 解析产出 items | {summary['pred']} |",
        f"| 匹配 | {summary['matched']} |",
        f"| Precision | {summary['precision']:.4f} |",
        f"| Recall | {summary['recall']:.4f} |",
        f"| Field F1 | {summary['f1']:.4f} |",
        f"| 静默错误率 | {summary['silent_rate']:.4f} |",
        f"| 单位一致率（匹配行） | {summary['unit_accuracy']:.4f} "
        f"（{summary['unit_checked']} 项） |",
        f"| 条件一致率（匹配行） | {summary['condition_accuracy']:.4f} "
        f"（{summary['condition_checked']} 项） |",
        f"| 表格匹配 | {summary['table_matched']} / {summary['table_gold']} "
        f"（{summary['table_match_rate']:.4f}） |",
        f"| 表型命中率 | {summary['table_profile_accuracy']:.4f} |",
        f"| 表头命中率 | {summary['table_header_accuracy']:.4f} |",
        f"| 单元格匹配率 | {summary['table_cell_accuracy']:.4f} |",
        f"| TEDS（≤120 单元格） | {summary['table_teds']:.4f} |",
        f"| 文档覆盖率 | {summary['coverage']:.4f} |",
        f"| 热处理 gold / pred / matched | {summary['heat_gold']} / "
        f"{summary['heat_pred']} / {summary['heat_matched']} |",
        f"| 热处理 F1 | {summary['heat_f1']:.4f} |",
        f"| 正文条款数 | {summary['clauses']} |",
        f"| 项目清单项 | {summary['inventory_items']} |",
        f"| 清单与记录 feature 对齐率 | {summary['inventory_aligned_ratio']:.4f} |",
        f"| 定性项 gold / 记录 | {summary['qualitative_items']} / "
        f"{summary['qualitative_records']} |",
        f"| 定性项覆盖率 | {summary['qualitative_coverage']:.4f} |",
        f"| 正文项目 feature gold / pred / matched | "
        f"{summary['qualitative_gold_features']} / "
        f"{summary['qualitative_pred_features']} / "
        f"{summary['qualitative_matched_features']} |",
        f"| 正文项目 feature 召回率 | {summary['qualitative_feature_recall']:.4f} |",
        f"| 正文要求文本命中率 | {summary['qualitative_requirement_rate']:.4f} |",
        f"| 引用标准数 / 解析率 | {summary['references']} / "
        f"{summary['reference_resolution_rate']:.4f} |",
        f"| 方法绑定 / 补填 | {summary['method_bindings']} / "
        f"{summary['methods_filled']} |",
        f"| 分类项 | {summary['classifications']} |",
        f"| 词典命中率（项目） | {summary['dictionary_hit_rate']:.4f} |",
        f"| 词典命中率（方法） | {summary['dictionary_method_hit_rate']:.4f} |",
        f"| 试验方法填充率 | {summary['method_fill_rate']:.4f} "
        f"（{summary['fill_total']} 行） |",
        f"| 取样字段填充率 | {summary['sampling_fill_rate']:.4f} |",
        "",
        "## 2. 分类指标",
        "",
        "| 项目大类 | gold | pred | matched | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for feature, values in payload["features"].items():
        lines.append(
            f"| {feature} | {values['gold']} | {values['pred']} | {values['matched']} | "
            f"{values['precision']:.4f} | {values['recall']:.4f} | {values['f1']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## 3. 文档明细",
            "",
            "| 文档 | 状态 | gold | pred | matched | P | R | F1 | 静默率 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in sorted(payload["documents"], key=lambda row: row["f1"]):
        lines.append(
            f"| {item['doc_id']} | {item['run_status']} | {item['gold']} | {item['pred']} | "
            f"{item['matched']} | {item['precision']:.4f} | {item['recall']:.4f} | "
            f"{item['f1']:.4f} | {item['silent_rate']:.4f} |"
        )
    lines.extend(["", "## 4. 主要缺口", ""])
    for item in payload["documents"]:
        if not item["missing_top"] and not item["extra_top"]:
            continue
        lines.append(f"### {item['doc_id']}")
        if item["missing_top"]:
            missing = "；".join(
                f"{row['feature']}/{row['name']} 缺 {row['missing']}"
                for row in item["missing_top"][:5]
            )
            lines.append(f"- 漏抽：{missing}")
        if item["extra_top"]:
            extra = "；".join(
                f"{row['feature']}/{row['name']} 多 {row['extra']}"
                for row in item["extra_top"][:5]
            )
            lines.append(f"- 多抽：{extra}")
        lines.append("")
    if payload["failures"]:
        lines.extend(["## 5. 门禁", ""])
        lines.extend(f"- {failure}" for failure in payload["failures"])
    lines.extend(
        [
            "",
            "## 附：运行方式",
            "",
            "```powershell",
            "python scripts/benchmark/gold_registry.py --refresh-api",
            "python scripts/benchmark/gold_eval.py --gate",
            "python scripts/benchmark/gate_scale.py --require-gold",
            "```",
            "",
            "`gold_eval.py` 默认读取 API 的 run records 和 MinIO 的 `tables.json`；离线时可加 "
            "`--records-dir <dir>` 读取已导出的 records，`--skip-tables` 跳过表格指标。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_s3_client(endpoint: str, access_key: str, secret_key: str) -> Any:
    try:
        import boto3
    except ImportError:
        return None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--api", default="http://localhost:18000")
    parser.add_argument("--records-dir", type=Path)
    parser.add_argument("--dump-records", type=Path)
    parser.add_argument("--skip-tables", action="store_true")
    parser.add_argument("--storage-endpoint", default="http://localhost:19000")
    parser.add_argument("--bucket", default="hanson-docs")
    parser.add_argument("--access-key", default="minioadmin")
    parser.add_argument("--secret-key", default="minioadmin")
    parser.add_argument("--doc", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--min-f1", type=float, default=0.80)
    parser.add_argument("--max-silent", type=float, default=0.02)
    parser.add_argument("--min-coverage", type=float, default=0.90)
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    documents = registry["documents"]
    if args.doc:
        wanted = set(args.doc)
        documents = [item for item in documents if item["doc_id"] in wanted]
    if args.limit:
        documents = documents[: args.limit]

    client = httpx.Client(timeout=60)
    s3 = None if args.skip_tables else make_s3_client(
        args.storage_endpoint, args.access_key, args.secret_key
    )
    results = [
        evaluate_document(
            item,
            args.api,
            args.records_dir,
            args.dump_records,
            client=client,
            s3=s3,
            bucket=args.bucket,
        )
        for item in documents
    ]
    summary = aggregate(results)
    features = aggregate_features(results)
    failures: list[str] = []
    if args.gate:
        if summary["f1"] < args.min_f1:
            failures.append(f"Field F1 {summary['f1']:.4f} < {args.min_f1:.2f}")
        if summary["silent_rate"] > args.max_silent:
            failures.append(
                f"静默错误率 {summary['silent_rate']:.4f} > {args.max_silent:.2f}"
            )
        if summary["coverage"] < args.min_coverage:
            failures.append(f"覆盖率 {summary['coverage']:.4f} < {args.min_coverage:.2f}")
    payload = {
        "generated_at": now_iso(),
        "registry": str(args.registry),
        "summary": summary,
        "features": features,
        "documents": results,
        "failures": failures,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(args.out_md, payload)
    print(json.dumps(summary, ensure_ascii=False))
    print(f"failures {len(failures)}")
    for failure in failures:
        print(" -", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
