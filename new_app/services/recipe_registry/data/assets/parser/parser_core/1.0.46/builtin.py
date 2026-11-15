"""Deterministic built-in recipe engine.

Only the Python standard library is used: this file is copied into the
sandbox runtime image and executed with a read-only root filesystem.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

FOOTNOTE_RE = re.compile(r"[①-⑳]|\[\d+\]|\(\d+\)|（\d+）|\*+$")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
UNIT_RE = re.compile(r"^[A-Za-z%‰°℃Ωμ]+(?:\.[A-Za-z]+)?$")
GRADE_MAX_LEN = 64
PARSER_REVISION = "1.0.2"
_revision_reported = False
# Layout OCR sometimes emits the same table twice (page continuation copies).
_table_fingerprints: set[tuple] = set()
GRADE_SENTENCE_CHARS = ("。", "；", "，", "：", ";")
GRADE_HEADER_MARKERS = (
    "不小于",
    "不大于",
    "牌号",
    "屈服强度",
    "抗拉强度",
    "断后伸长率",
    "伸长率",
    "断面收缩率",
    "冲击",
    "硬度",
    "化学成分",
    "力学性能",
    "试验",
    "单位",
)
ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$")
# Footnote references attached to merged table cells, e.g. "T3 4/ (See 6.4)".
GRADE_FOOTNOTE_RE = re.compile(
    r"[（(]\s*(?:see|note|见|注)\s*(?:note|见|注)?\s*[\d.]*\s*[)）]",
    re.IGNORECASE,
)
GRADE_TAIL_MARKER_RE = re.compile(r"(?:^|\s)\d+/\s*$")
CJK_SPACED_RE = re.compile(r"^[\u4e00-\u9fff]+\s+[\u4e00-\u9fff\s]+$")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# Cells that only mean "not specified"; they must not become properties.
SKIP_CELL_VALUES = {
    "-", "--", "—", "–", "/", "…", "...", "－", "―",
    "remainder", "balance", "bal.",
}
# Row-key cells that label a block or a value limit, never a material grade.
PLACEHOLDER_GRADE_RE = re.compile(
    r"^(?:元素|element|含量|基|基体|余|余量|类别|状态|日期|更改人|更改内容(?:及说明)?|"
    r"版次|页码|编号|备注|检测标准|化学成分|主要成分|熔炼分析|成品分析|"
    r"max(?:imum)?|min(?:imum)?|最大(?:值)?|最小(?:值)?|上限|下限|"
    r"规定值|标准|要求|元素含量.*|wt%.*)$",
    re.IGNORECASE,
)
STANDARD_CODE_RE = re.compile(
    r"^(?:GB|GJB|JB|NB|YB|YS|ASTM|ASME|API|ISO|EN|DIN|RCC-M|HAF)\s*/?\s*[A-Z]?\s*\d",
    re.IGNORECASE,
)


def _placeholder_grade(value: str) -> bool:
    """True when a row-key cell labels a block instead of a material grade."""
    text = normalize(strip_footnote(value))
    if not text or text in {"0", "~", "-", "/"}:
        return True
    return bool(PLACEHOLDER_GRADE_RE.fullmatch(text))


CONDITION_GRADE_RE = re.compile(
    r"^(?:long[- ]?transverse|longitudinal|transverse|long|trans|lt|st|"
    r"纵向|横向|弦向|径向|切向)(?:\([^)]*\))?$",
    re.IGNORECASE,
)
_DOCUMENT_TEXT_CACHE: str | None = None


def _document_text() -> str:
    """Read the OCR markdown once per sandbox run (no-op outside the engine)."""
    global _DOCUMENT_TEXT_CACHE
    if _DOCUMENT_TEXT_CACHE is not None:
        return _DOCUMENT_TEXT_CACHE
    _DOCUMENT_TEXT_CACHE = ""
    request_path = Path(os.environ.get("HANSON_REQUEST", "/work/input/request.json"))
    ocr_path = request_path.parent / "ocr.json"
    try:
        payload = json.loads(ocr_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _DOCUMENT_TEXT_CACHE
    markdown = str(payload.get("markdown") or "")
    if not markdown:
        markdown = "\n".join(
            str(page.get("markdown") or "") for page in (payload.get("pages") or [])[:2]
        )
    _DOCUMENT_TEXT_CACHE = markdown
    return markdown


def _title_region(text: str) -> str:
    head = str(text or "")[:4000]
    for marker in ("RATIONALE", "1. SCOPE", "1. Scope", "1 范围", "Foreword", "前言"):
        index = head.find(marker)
        if index > 80:
            head = head[:index]
            break
    return head


def _document_grade_hint(text: str) -> str:
    """Infer one document-level grade from the title/scope block.

    AMS/ASTM tables often omit the grade column because the alloy designation is
    only printed in the specification title.  The returned hint is used only
    for records whose grade is ``~`` or a specimen-direction word.
    """
    head = _title_region(text)
    if not head:
        return ""
    lowered = head.lower()
    # 标题里显式写了 “UNS R56401” 时以该牌号为准；但 AMS 封面常见的
    # “(Composition similar to UNS R56400)” 只是成分对照，不能覆盖 6Al-4V。
    for explicit_uns in re.finditer(r"UNS\s*([A-Z]\d{5})\b", head):
        window = head[max(0, explicit_uns.start() - 48) : explicit_uns.start()].lower()
        if "similar to" in window:
            continue
        return explicit_uns.group(1)
    if re.search(r"钛\s*[-－—]?\s*6\s*铝\s*[-－—]?\s*4\s*钒", head) or re.search(
        r"titanium\s*[-–—]?\s*6\s*[-–—]?\s*alumin(?:i)?um\s*[-–—]?\s*4\s*[-–—]?\s*vanadium",
        lowered,
    ):
        return "Ti-6Al-4V"
    if (
        re.search(r"镍\s*[-－—]?\s*钛", head)
        or "nickel-titanium" in lowered
        or "nickel titanium" in lowered
        or "nitinol" in lowered
    ):
        # NiTi shape-memory alloys are named by family, not by a grade code.
        return "NiTi"
    upper = head.upper()
    if ("AEROSPACE" in upper or "AMS" in upper[:300]) and re.search(
        r"6\s*Al\s*-\s*4\s*V", head, re.IGNORECASE
    ):
        return "6Al-4V"
    temper = re.search(r"\b(\d{4}-[TTH]\d{2,4})\b", head, re.IGNORECASE)
    if temper:
        return temper.group(1)
    uns = []
    # Do not read a UNS number out of a standard code such as "GB/T 24627".
    for match in re.findall(r"(?<![A-Za-z/])([A-Z]\d{5})\b", head):
        if match not in uns:
            uns.append(match)
    if len(uns) == 1:
        return uns[0]
    return ""


def _apply_document_grade(
    records: list[dict[str, Any]], diagnostics: list[dict[str, Any]], table_id: str
) -> int:
    if not records:
        return 0
    hint = _document_grade_hint(_document_text())
    if not hint:
        valid = {
            str(record.get("grade") or "")
            for record in records
            if str(record.get("grade") or "") not in {"", "~"}
            and not CONDITION_GRADE_RE.fullmatch(str(record.get("grade") or ""))
        }
        if len(valid) == 1:
            hint = next(iter(valid))
    if not hint and records and all(
        set(record.get("properties") or {}).issubset(ORPHAN_MEASURES | {"侧向膨胀值"})
        for record in records
    ):
        # 旧项目 schema 的约定：冲击性能表若只给出“试样尺寸”，材料牌号记为
        # “全部牌号”。没有这条兜底，这类记录会被当作“无主表”丢掉。
        hint = "全部牌号"
    if not hint:
        return 0
    filled = 0
    for record in records:
        grade = str(record.get("grade") or "").strip()
        if grade in {"", "~"}:
            record["grade"] = hint
            filled += 1
            continue
        if CONDITION_GRADE_RE.fullmatch(grade):
            conditions = record.setdefault("conditions", {})
            conditions.setdefault("方向", grade)
            record["condition_key"] = _condition_key(conditions)
            record["grade"] = hint
            filled += 1
    if filled:
        diagnostics.append(
            {
                "code": "DOCUMENT_GRADE_FALLBACK",
                "message": f"table {table_id} filled {filled} document-level grades",
                "severity": "info",
                "detail": {"table_id": table_id, "grade": hint, "filled": filled},
            }
        )
    return filled


HEAT_COLUMN_RE = re.compile(
    r"热处理|固溶|淬火|回火|正火|退火|时效|沉淀硬化|冷却方式|冷却介质"
)
HEAT_TEMP_RE = re.compile(
    r"(?:\d{2,4}(?:\.\d+)?\s*(?:℃|°C)\s*[~～\-—至]\s*\d{2,4}(?:\.\d+)?\s*(?:℃|°C)"
    r"|(?:≥|≤|不小于|不大于|约)?\s*\d{2,4}(?:\.\d+)?\s*"
    r"(?:[~～\-—至]\s*\d{2,4}(?:\.\d+)?)?\s*(?:℃|°C)"
    r"(?:\s*±\s*\d{1,3}\s*(?:℃|°C))?)"
)
HEAT_TIME_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:h|min|小时|分钟)", re.IGNORECASE)
HEAT_COOLING_TERMS = (
    "水冷", "油冷", "空冷", "炉冷", "风冷", "快冷", "缓冷",
    "水淬", "气淬", "空淬", "自然冷却", "随炉冷却", "按要求冷却",
)
HEAT_PROCESS_TERMS = (
    "固溶处理", "沉淀硬化处理", "退火处理", "时效处理",
    "固溶", "淬火", "回火", "正火", "退火", "时效",
)


def _first_number(value: Any) -> float | None:
    match = NUMBER_RE.search(str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _heat_cooling(text: str) -> str:
    hits = [(text.find(term), term) for term in HEAT_COOLING_TERMS if term in text]
    hits.sort()
    return "、".join(dict.fromkeys(term for _, term in hits))


def _parse_heat_schedule(text: str) -> dict[str, str]:
    raw = str(text or "")
    temps = [item.strip() for item in HEAT_TEMP_RE.findall(raw)]
    times: list[str] = []
    for item in HEAT_TIME_RE.findall(raw):
        number = _first_number(item)
        if number is None:
            continue
        if re.search(r"h$", item, re.IGNORECASE) and number > 72:
            # "AMS 2772 heat treat" must not become a 2772-hour hold.
            continue
        if re.search(r"min$", item, re.IGNORECASE) and number > 600:
            continue
        times.append(item.strip())
    return {
        "temp": "；".join(dict.fromkeys(temps)),
        "time": "；".join(dict.fromkeys(times)),
        "cooling": _heat_cooling(raw),
    }


def _heat_process(header: str, caption: str, schedule: dict[str, str]) -> str:
    probe = _header_text(header)
    for term in HEAT_PROCESS_TERMS:
        if term in probe:
            return term
    for term in HEAT_PROCESS_TERMS:
        if term in str(caption or ""):
            return term
    caption_text = str(caption or "")
    if "奥氏体" in caption_text or "austenit" in caption_text.lower():
        return "固溶处理"
    temperature = _first_number(schedule.get("temp"))
    if temperature is not None and temperature >= 1000:
        return "固溶处理"
    if "铁素体" in caption_text:
        return "退火处理"
    return ""


def _heat_properties(schedule: dict[str, str], column: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    if schedule["temp"]:
        properties["保温温度"] = {
            "raw": schedule["temp"],
            "value": _first_number(schedule["temp"]),
            "unit": "℃",
            "column": column,
        }
    if schedule["time"]:
        properties["保温时间"] = {
            "raw": schedule["time"],
            "value": _first_number(schedule["time"]),
            "unit": "h",
            "column": column,
        }
    if schedule["cooling"]:
        properties["冷却介质"] = {
            "raw": schedule["cooling"],
            "value": None,
            "unit": "",
            "column": column,
        }
    return properties


def _parse_heat_table(
    table: dict[str, Any],
    *,
    table_id: str,
    page_no: int,
    recipe_id: str,
    recipe_version: str,
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Parse a heat-treatment schedule table (grade rows, process columns)."""
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    row_total = 0
    caption = str(table.get("caption") or "")
    for block_id, headers, data_rows, _meta in _iter_blocks(table):
        if not headers or not data_rows:
            continue
        row_total += len(data_rows)
        grade_col: int | None = None
        for index, header in enumerate(headers):
            text = normalize(header)
            if "统一数字代号" in text or "uns" in text:
                continue
            if "牌号" in text or "钢号" in text or "grade" in text:
                grade_col = index
                if "牌号" in text:
                    break
        if grade_col is None:
            continue
        heat_cols = [
            (index, _header_text(header))
            for index, header in enumerate(headers)
            if index != grade_col and HEAT_COLUMN_RE.search(str(header))
        ]
        if not heat_cols:
            continue
        last_grade = ""
        for row_index, row in enumerate(data_rows):
            if _is_footnote_row(row):
                continue
            grade = strip_footnote(row[grade_col]) if grade_col < len(row) else ""
            if not grade and last_grade:
                grade = last_grade
            if not grade or _placeholder_grade(grade):
                continue
            last_grade = grade
            for col, label in heat_cols:
                cell = str(row[col] if col < len(row) else "").strip()
                if not cell or cell in SKIP_CELL_VALUES or len(cell) < 2:
                    continue
                schedule = _parse_heat_schedule(cell)
                if not schedule["temp"] and not schedule["cooling"]:
                    continue
                process = _heat_process(label, caption, schedule)
                if not process:
                    continue
                record_id = f"{table_id}-H{row_index + 1}-C{col + 1}"
                conditions = {"工序名称": process}
                records.append(
                    {
                        "record_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "recipe_id": recipe_id,
                        "recipe_version": recipe_version,
                        "profile": "heat_treatment",
                        "grade": grade,
                        "grade_raw": None,
                        "conditions": conditions,
                        "condition_key": _condition_key(conditions),
                        "properties": _heat_properties(schedule, label),
                        "evidence_refs": [record_id],
                        "source": {
                            "table_id": table_id,
                            "block_id": block_id,
                            "page_no": page_no,
                            "row_index": row_index,
                        },
                    }
                )
                evidence.append(
                    {
                        "evidence_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "raw_row": list(row),
                        "cells": {"牌号": grade, label: cell},
                    }
                )
    if not records:
        diagnostics.append(
            {
                "code": "NO_RECORDS",
                "message": f"table {table_id} produced no records",
                "severity": "warning",
                "detail": {"table_id": table_id},
            }
        )
    summary = {
        "table_id": table_id,
        "page_no": page_no,
        "profile": "heat_treatment",
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "rows": row_total,
        "records": len(records),
    }
    return records, evidence, summary


def _derive_heat_records(
    records: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    table_id: str,
) -> list[dict[str, Any]]:
    """Promote heat schedules embedded in mechanical conditions to records."""
    derived: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        if str(record.get("profile") or "") == "heat_treatment":
            continue
        conditions = record.get("conditions") or {}
        schedule_text = ""
        for key, value in conditions.items():
            key_text = str(key)
            if not any(
                token in key_text
                for token in ("热处理", "固溶", "淬火", "回火", "退火", "正火", "时效")
            ):
                continue
            if str(value or "").strip():
                schedule_text = str(value).strip()
                break
        if not schedule_text:
            continue
        schedule = _parse_heat_schedule(schedule_text)
        if not schedule["temp"] and not schedule["cooling"]:
            continue
        process = ""
        for key in ("状态", "工序", "工序名称"):
            if str(conditions.get(key) or "").strip():
                process = str(conditions[key]).strip()
                break
        if not process:
            process = _heat_process("", "", schedule)
        if not process:
            continue
        grade = str(record.get("grade") or "").strip()
        if not grade:
            continue
        dedupe = (grade, schedule_text, process)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        record_id = f"{record.get('record_id') or table_id}-HT"
        conditions_out = {"工序名称": process}
        derived.append(
            {
                "record_id": record_id,
                "table_id": record.get("table_id") or table_id,
                "block_id": record.get("block_id") or "",
                "page_no": record.get("page_no") or 0,
                "row_index": record.get("row_index") or 0,
                "recipe_id": record.get("recipe_id") or "",
                "recipe_version": record.get("recipe_version") or "",
                "profile": "heat_treatment",
                "grade": grade,
                "grade_raw": None,
                "conditions": conditions_out,
                "condition_key": _condition_key(conditions_out),
                "properties": _heat_properties(schedule, "热处理"),
                "evidence_refs": list(record.get("evidence_refs") or []),
                "source": record.get("source") or {},
            }
        )
    if derived:
        diagnostics.append(
            {
                "code": "HEAT_TREATMENT_DERIVED",
                "message": f"table {table_id} derived {len(derived)} heat records",
                "severity": "info",
                "detail": {"table_id": table_id, "records": len(derived)},
            }
        )
    return derived


HEAT_PROSE_RE = re.compile(
    r"heat[- ]?treat|solution|precipitation|anneal|aging|\bage\b|固溶|时效|退火|淬火|回火|正火",
    re.IGNORECASE,
)


def document_heat_records(
    ocr: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract heat-treatment schedules written as prose in AMS specifications.

    AMS standards often give the schedule in the body ("Solution heat treat and
    precipitation heat treat per AMS 2772 ... T7451") instead of a table.
    """
    text = str(ocr.get("markdown") or "")
    head = _title_region(text)
    lowered_head = head.lower()
    if "aerospec" not in lowered_head and "ams" not in lowered_head[:400]:
        return [], []
    grade = _document_grade_hint(text)
    if not grade:
        return [], []
    default_process = ""
    if "annealed" in lowered_head or "退火" in head:
        default_process = "退火"
    elif "solution heat treated" in lowered_head:
        default_process = "固溶+时效"
    chunks = re.split(r"\n{1,}|[。；]|(?<=[.!?])\s+", text)
    processes: dict[str, tuple[str, dict[str, str]]] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 24:
            continue
        lowered = chunk.lower()
        has_temperature = bool(re.search(r"°\s*[fc]|℃|℉", lowered))
        if not HEAT_PROSE_RE.search(chunk) and not (
            default_process
            and has_temperature
            and re.search(r"\bheat\b|\bhold\b", lowered)
        ):
            continue
        if not has_temperature and "ams 2772" not in lowered and "ams2772" not in lowered:
            continue
        process = ""
        if "solution" in lowered and re.search(r"precipitat|ag(e|ing)", lowered):
            process = "固溶+时效"
            if re.search(r"overag|过时效", lowered):
                process = "固溶+过时效"
            elif "t7451" in lowered:
                process = "固溶+人工时效"
        elif "solution" in lowered or "固溶" in chunk:
            process = "固溶"
        elif re.search(r"anneal|退火", lowered):
            process = "退火"
        elif default_process:
            process = default_process
        if not process:
            continue
        if process == "固溶+时效":
            if "t7451" in text.lower():
                process = "固溶+人工时效"
            elif "t7452" in text.lower():
                process = "固溶+过时效"
        processes.setdefault(process, (chunk, _parse_heat_schedule(chunk)))
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for index, (process, (source_text, schedule)) in enumerate(processes.items(), start=1):
        record_id = f"DOC-HT{index}"
        conditions = {"工序名称": process}
        records.append(
            {
                "record_id": record_id,
                "table_id": "DOC",
                "block_id": "",
                "page_no": 0,
                "row_index": index - 1,
                "recipe_id": "document_heat",
                "recipe_version": "1.0.0",
                "profile": "heat_treatment",
                "grade": grade,
                "grade_raw": None,
                "conditions": conditions,
                "condition_key": _condition_key(conditions),
                "properties": _heat_properties(schedule, "正文"),
                "evidence_refs": [record_id],
                "source": {"table_id": "DOC", "page_no": 0, "row_index": index - 1},
            }
        )
        evidence.append(
            {
                "evidence_id": record_id,
                "table_id": "DOC",
                "block_id": "",
                "page_no": 0,
                "row_index": index - 1,
                "raw_row": [grade, process],
                "cells": {"正文": source_text[:300]},
            }
        )
    return records, evidence


def _header_text(header: str) -> str:
    """Readable header path for condition/grade text without joining separators."""
    text = strip_footnote(str(header or ""))
    return re.sub(r"\s*/\s*", " ", text).strip()


def _group_label(header: str) -> str:
    """Return the header group that owns a measure column.

    Multi-group tables repeat the same measure under different temperatures or
    directions (``室温拉伸试验 / Rm``, ``350℃拉伸试验 / Rm``).  The group label is
    the path above the measure column.
    """
    text = str(header or "")
    if " / " not in text:
        return ""
    return strip_footnote(text.rsplit(" / ", 1)[0]).strip()

MEASURE_ALIASES: dict[str, list[str]] = {
    "Rm": ["抗拉强度", "拉伸强度", "σb", "tensile strength", "tensile"],
    "Rp0.2": [
        "屈服强度",
        "规定塑性延伸强度",
        "σ0.2",
        "yield strength",
        "0.2 percent offset",
        "proof strength",
    ],
    "Rp1.0": ["屈服强度", "σ1.0", "proof strength"],
    "ReH": ["上屈服强度", "屈服强度", "upper yield"],
    "ReL": ["下屈服强度", "屈服强度", "lower yield"],
    "A": [
        "断后伸长率",
        "伸长率",
        "延伸率",
        "δs",
        "δ5",
        "elongation",
        "extension",
    ],
    "Z": ["断面收缩率", "收缩率", "ψ", "reduction of area"],
    "KU2": ["冲击吸收能量", "冲击功", "kv2", "kuj", "akuj", "impact energy", "charpy"],
    "KV2": ["冲击吸收能量", "冲击功", "ku2", "akv", "impact energy", "charpy"],
    "KU5": ["冲击吸收能量", "冲击功", "impact energy", "charpy"],
    "HB": ["布氏硬度", "硬度", "hbw", "brinell", "hardness"],
    "HBW": ["布氏硬度", "硬度", "hb", "brinell", "hardness"],
    "HRC": ["洛氏硬度", "rockwell"],
    "HRB": ["洛氏硬度", "rockwell"],
    "HV": ["维氏硬度", "vickers"],
    "E": [
        "弹性模量",
        "杨氏模量",
        "elastic modulus",
        "modulus of elasticity",
        "young's modulus",
    ],
    "侧向膨胀值": ["侧向膨胀值", "侧向膨胀", "lateral expansion"],
    "持久时间": ["持久时间", "断裂时间", "stress rupture", "rupture life", "time to rupture"],
    "持久应力": [
        "持久应力",
        "持久强度",
        "初始应力",
        "应力",
        "stress rupture strength",
    ],
    "持久温度": ["持久温度", "rupture temperature"],
    "蠕变速率": ["蠕变速率", "creep rate"],
    "蠕变变形": ["蠕变变形", "creep deformation", "creep strain"],
    "KIC": ["断裂韧性", "fracture toughness", "kic"],
    "弯曲试验系数": ["弯曲试验系数", "弯曲系数", "bend test factor", "bend factor"],
    "断裂韧度L-T": ["l-t", "l-t ksi", "l-t mpa"],
    "断裂韧度T-L": ["t-l", "t-l ksi", "t-l mpa"],
    "断裂韧度S-L": ["s-l", "s-l ksi", "s-l mpa"],
    "弯曲压头直径": [
        "弯心直径",
        "弯曲压头",
        "压头直径",
        "mandrel diameter",
        "bend diameter",
    ],
    "弯曲半径": ["弯曲半径", "bend radius", "mandrel radius"],
    "弯曲半径90°": ["弯曲半径90", "弯曲半径 90", "90°", "90 °", "bend 90"],
    "弯曲半径180°": ["弯曲半径180", "弯曲半径 180", "180°", "180 °", "bend 180"],
    "弯曲试验": ["弯曲试验", "bend test", "bending test"],
    "CEV": ["碳当量", "carbon equivalent"],
    "Pcm": ["焊接裂纹敏感性", "crack sensitivity"],
    "Fe": ["铁", "iron"],
    "Si": ["硅", "silicon"],
    "Mn": ["锰", "manganese"],
    "P": ["磷", "phosphorus"],
    "S": ["硫", "sulfur", "sulphur"],
    "Ni": ["镍", "nickel"],
    "Cr": ["铬", "chromium"],
    "Mo": ["钼", "molybdenum"],
    "Cu": ["铜", "copper"],
    "Al": ["铝", "aluminum", "aluminium"],
    "Ti": ["钛", "titanium"],
    "V": ["钒", "vanadium"],
    "Nb": ["铌", "niobium", "columbium"],
    "N": ["氮", "nitrogen"],
    "O": ["氧", "oxygen"],
    "H": ["氢", "hydrogen"],
    "B": ["硼", "boron"],
    "W": ["钨", "tungsten"],
    "Co": ["钴", "cobalt"],
    "Zr": ["锆", "zirconium"],
    "Ta": ["钽", "tantalum"],
    "Re": ["铼", "rhenium"],
    "Sn": ["锡", "tin"],
    "As": ["砷", "arsenic"],
    "Pb": ["铅", "lead"],
    "Sb": ["锑", "antimony"],
    "Bi": ["铋", "bismuth"],
    "Ca": ["钙", "calcium"],
    "Mg": ["镁", "magnesium"],
    "Zn": ["锌", "zinc"],
    "Ce": ["铈", "cerium"],
    "La": ["镧", "lanthanum"],
    "Y": ["钇", "yttrium"],
    "Nd": ["钕", "neodymium"],
    "Se": ["硒", "selenium"],
    "Te": ["碲", "tellurium"],
    "Ag": ["银", "silver"],
}

# Header symbols are authoritative: a column labelled KV2 must stay KV2 even
# when the recipe binds KU2 (and HBW must not be relabelled HB, etc.).
SYMBOL_CANON: dict[str, str] = {name.lower(): name for name in MEASURE_ALIASES}
SYMBOL_CANON.update(
    {
        "rel": "ReL",
        "reh": "ReH",
        "σb": "Rm",
        "σ0.2": "Rp0.2",
        "σ1.0": "Rp1.0",
        "δs": "A",
        "δ5": "A",
        "ψ": "Z",
    }
)
# ``Re`` is rhenium in chemistry but yield strength in mechanical tables; the
# recipe binding decides which one applies.
SYMBOL_CANON.pop("re", None)
SYMBOL_RE = re.compile(r"[A-Za-z]+(?:[0-9]+(?:\.[0-9]+)?)?")

ELEMENT_SYMBOLS = {
    "H", "B", "C", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S", "K",
    "Ca", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "As", "Se", "Sr", "Y", "Zr", "Nb", "Mo", "Ag", "Cd", "In", "Sn", "Sb",
    "Te", "Ba", "La", "Ce", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er",
    "Yb", "Ta", "W", "Re", "Pb", "Bi", "Th", "U", "Be", "Li", "Sc", "Hf",
    "Cs", "Rb",
}

# 英文元素全名 -> 符号。不能只靠“首字母大写+次字母”的启发式：Iron 会得到 Ir，
# Copper 会得到 Co（钴），Carbon 会得到 Ca（钙）。
ELEMENT_NAMES = {
    "hydrogen": "H", "beryllium": "Be", "boron": "B", "carbon": "C",
    "nitrogen": "N", "oxygen": "O", "fluorine": "F", "sodium": "Na",
    "magnesium": "Mg", "aluminum": "Al", "aluminium": "Al", "silicon": "Si",
    "phosphorus": "P", "sulfur": "S", "sulphur": "S", "potassium": "K",
    "calcium": "Ca", "scandium": "Sc", "titanium": "Ti", "vanadium": "V",
    "chromium": "Cr", "manganese": "Mn", "iron": "Fe", "cobalt": "Co",
    "nickel": "Ni", "copper": "Cu", "zinc": "Zn", "gallium": "Ga",
    "germanium": "Ge", "arsenic": "As", "selenium": "Se", "rubidium": "Rb",
    "strontium": "Sr", "yttrium": "Y", "zirconium": "Zr", "niobium": "Nb",
    "molybdenum": "Mo", "silver": "Ag", "cadmium": "Cd", "indium": "In",
    "tin": "Sn", "antimony": "Sb", "tellurium": "Te", "cesium": "Cs",
    "caesium": "Cs", "barium": "Ba", "lanthanum": "La", "cerium": "Ce",
    "neodymium": "Nd", "samarium": "Sm", "europium": "Eu",
    "gadolinium": "Gd", "terbium": "Tb", "dysprosium": "Dy", "holmium": "Ho",
    "erbium": "Er", "ytterbium": "Yb", "hafnium": "Hf", "tantalum": "Ta",
    "tungsten": "W", "rhenium": "Re", "lead": "Pb", "bismuth": "Bi",
    "thorium": "Th", "uranium": "U",
}

CONDITION_TOKENS = (
    "规格",
    "尺寸",
    "方向",
    "试验温度",
    "温度",
    "状态",
    "热处理",
    "取样",
    "厚度",
    "交货",
    "交货状态",
    "热处理状态",
    "试样",
    "试样状态",
    "取样方向",
    "部位",
    "公称",
    "类型",
    "壁厚",
    "外径",
    "产品形式",
    "表面状态",
    "轧制",
    "冷轧",
    "热轧",
    "固溶",
    "时效",
    "退火",
    "正火",
    "回火",
    "淬火",
    "thickness",
    "orientation",
    "diameter",
    "width",
    "length",
    "temperature",
    "specimen",
)
DIMENSION_HEADER_MARKERS = (
    "厚度",
    "thickness",
    "规格",
    "尺寸",
    "直径",
    "diameter",
    "宽度",
    "width",
    "长度",
    "length",
    "外径",
)
DEFAULT_ROW_KEY = (
    "牌号",
    "钢号",
    "grade",
    "材料牌号",
    "常用材料",
    "钢种",
    "材料",
    "合金牌号",
    "材料名称",
    "级别",
    "钢级",
    "质量等级",
    "统一数字代号",
    "新牌号",
    "原牌号",
    "锻件种类",
    "temper",
    "element",
    "alloy",
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def strip_footnote(text: str) -> str:
    return FOOTNOTE_RE.sub("", (text or "").strip()).strip()


DATA_CELL_RE = re.compile(r"^[<>≤≥~～]?\s*\d+(?:\.\d+)?$")


def _collapse_duplicate_columns(
    headers: list[str], data: list[list[str]]
) -> tuple[list[str], list[list[str]]]:
    """合并列：表头文字与所有数据行取值都相同的重复列只保留一列。

    OCR 会把表头的合并单元格展开成多列（``C`` 出现 3 次），导致后续
    元素/性能列整体错位；重复列的数据完全一致时可以安全折叠。
    """
    if not headers or not data:
        return headers, data
    keep: list[int] = []
    for index, header in enumerate(headers):
        duplicated = False
        for previous in keep:
            if headers[previous] != header:
                continue
            if all(
                (row[previous] if previous < len(row) else "")
                == (row[index] if index < len(row) else "")
                for row in data
            ):
                duplicated = True
                break
        if not duplicated:
            keep.append(index)
    if len(keep) == len(headers):
        return headers, data
    return (
        [headers[index] for index in keep],
        [[row[index] if index < len(row) else "" for index in keep] for row in data],
    )


def _header_columns(table: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    rows = table.get("rows") or []
    header_rows = int(table.get("header_rows") or 1)
    paths = table.get("header_paths") or []
    n_cols = int(table.get("n_cols") or 0)

    if paths:
        headers = [" / ".join(part for part in p if part) for p in paths]
        # TableGrid.rows keeps the header rows; header_paths describes them.
        data = rows[header_rows:] if header_rows > 0 else rows
        return _collapse_duplicate_columns(headers, data)
    if not rows:
        return [], []
    header_rows = max(1, min(header_rows, len(rows)))
    width = n_cols or max(len(r) for r in rows)
    headers = []
    for col in range(width):
        parts = []
        for row in rows[:header_rows]:
            if col < len(row) and row[col] and row[col] not in parts:
                parts.append(row[col])
        headers.append(" / ".join(parts))
    data = rows[header_rows:]
    return _collapse_duplicate_columns(headers, data)


def _block_meta(
    table: dict[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    """W3: per-column units/conditions/elements emitted by the OCR table grid."""
    return (
        [str(value or "") for value in (table.get("column_units") or [])],
        [str(value or "") for value in (table.get("column_conditions") or [])],
        [str(value or "") for value in (table.get("column_elements") or [])],
    )


def _iter_blocks(table: dict[str, Any]):
    """Yield (block_id, headers, data_rows, meta) for a table or its blocks."""
    headers, data = _header_columns(table)
    if headers and data:
        yield table.get("block_id") or "", headers, data, _block_meta(table)
        return
    for block in table.get("blocks") or []:
        block_table = {
            "rows": block.get("rows") or [],
            "header_rows": block.get("header_rows") or 1,
            "header_paths": block.get("header_paths") or [],
            "n_cols": len(block.get("rows", [[]])[0]) if block.get("rows") else 0,
            "column_units": block.get("column_units") or [],
            "column_conditions": block.get("column_conditions") or [],
            "column_elements": block.get("column_elements") or [],
        }
        block_headers, block_data = _header_columns(block_table)
        if block_headers:
            yield block.get("block_id") or "", block_headers, block_data, _block_meta(
                block_table
            )


def _is_dimension_header(header: str) -> bool:
    text = normalize(header)
    return any(marker in text for marker in DIMENSION_HEADER_MARKERS)


LIMIT_LABELS = {
    "不大于", "不小于", "不大于或等于", "不小于或等于",
    "≥", "≤", ">", "<", "max", "min", "maximum", "minimum",
}
DIRECTION_LABELS = {
    "纵向", "横向", "弦向", "径向", "切向",
    "longitudinal", "transverse", "long-transverse", "long-trans",
    "long", "trans", "lt",
    "longitudinaldirection", "transversedirection",
}


def _is_limit_row(row: list[str]) -> bool:
    """Header remnant rows that only carry 不大于/不小于 limits.

    Merged header rows sometimes survive as data rows (GB/T 1591 Table 1) and
    would otherwise become a fake grade with limit-text properties.
    """
    cells = [str(cell or "").strip() for cell in row if str(cell or "").strip()]
    if len(cells) < 3:
        return False
    hits = sum(1 for cell in cells if normalize(cell) in LIMIT_LABELS)
    return hits / len(cells) >= 0.6


CONDITION_HEADER_NAMES = (
    (("方向", "orientation", "direction"), "方向"),
    (("厚度", "thickness", "直径", "diameter", "尺寸"), "规格"),
    (("温度", "temperature"), "温度"),
    (("状态", "condition", "temper"), "状态"),
)


def _condition_name(header: str) -> str:
    """Name of the condition a column carries when the table has no grade key."""
    text = normalize(header)
    if "℃" in text:
        return ""
    for tokens, name in CONDITION_HEADER_NAMES:
        if any(token in text for token in tokens):
            return name
    return ""


HEADER_MARK_STRIP = "≤≥<>=±≤≥*＊"
# Symbols that OCR commonly splits with spaces ("R m", "KU 2", "HB W").
SPACED_SYMBOLS = {
    "rm",
    "rp0.2",
    "rp1.0",
    "rel",
    "reh",
    "ku2",
    "kv2",
    "ku5",
    "hbw",
    "hbs",
    "hrc",
    "hrb",
    "hv",
}


def _header_parts(header: str) -> list[str]:
    """Split a header into comparable tokens.

    Limit markers are part of the printed header (``P≤``, ``Cu≤``) but not part
    of the measure name, so they are stripped before matching.
    """
    parts = []
    for part in re.split(r"[/\s()（）,，;；%％]+", str(header or "")):
        token = normalize(part).strip(HEADER_MARK_STRIP)
        if token:
            parts.append(token)
    return parts


def _alias_matches(header: str, token: str) -> bool:
    """Short ASCII symbols must match a whole header component.

    ``hb`` must not match ``hbw`` and ``c`` must not match ``cr``; longer
    English phrases (``yield strength``) keep substring matching. Chinese
    aliases also keep substring matching because headers add qualifiers.
    """
    if CJK_RE.search(token):
        # Chinese qualifiers must match inside longer labels: "方向" in
        # "试样方向", "磷" in "磷含量".
        return token in header
    if not re.fullmatch(r"[a-z0-9.]+", token):
        # Greek symbols (σb, σ0.2, δ5) are printed as a prefix of the unit.
        if token in header:
            return True
    if len(token) <= 8:
        if token in _header_parts(header):
            return True
    else:
        return token in header
    if token in SPACED_SYMBOLS:
        # OCR splits printed symbols: "R m", "KU 2", "R eL (R ) p0.2".
        compact = re.sub(r"[()（）]", "", header)
        if compact.startswith(token):
            return True
        if any(char.isdigit() for char in token) and token in compact:
            return True
    return False


YIELD_FAMILY = {"Rp0.2", "Rp1.0", "ReL", "ReH"}


def _canonical_measure(name: str) -> str:
    return "HB" if name in {"HBW", "HBS"} else name


def _same_measure_family(printed: str, measure: str) -> bool:
    left, right = _canonical_measure(printed), _canonical_measure(measure)
    return left == right or (
        left in YIELD_FAMILY and right in YIELD_FAMILY
    )


def _printed_measure(header: str) -> str:
    """First known measure symbol printed in a normalized header."""
    text = re.sub(r"(?:n/mm2|n/mm²|j/cm2|j/cm²|mpa|gpa)", "", header)
    has_cjk = bool(CJK_RE.search(text))
    parts = set(_header_parts(text))
    for symbol in SYMBOL_RE.findall(text):
        canonical = SYMBOL_CANON.get(symbol)
        if not canonical:
            continue
        if len(symbol) == 1 and (has_cjk or symbol not in parts):
            continue
        return _canonical_measure(canonical)
    return ""


def _find_column(
    headers: list[str],
    aliases: list[str],
    used: set[int],
    *,
    skip_group: bool = False,
    measure: str | None = None,
    bound_measures: set[str] | None = None,
) -> int | None:
    def scoped(header: str) -> str:
        # Multi-level headers repeat a group heading above each measure
        # ("拉伸性能 / 抗拉强度Rm", "硬度 / 冲击吸收能量KV2"); the heading must
        # not satisfy an unrelated alias such as "硬度".
        if skip_group and " / " in header:
            head, rest = header.split(" / ", 1)
            if CJK_RE.search(head) and rest.strip() and not UNIT_RE.match(rest.strip()):
                return rest
        return header

    normalized = [normalize(scoped(h)) for h in headers]
    # Keep the printed word boundaries ("Minimum KIC ksi sqrtinch") because
    # short ASCII aliases must match whole words, not concatenated headers.
    spaced = [str(scoped(h) or "").lower() for h in headers]
    for alias in aliases:
        token = normalize(alias)
        if not token:
            continue
        for idx, header in enumerate(normalized):
            if idx in used:
                continue
            if measure:
                printed = _printed_measure(header)
                if (
                    printed
                    and not _same_measure_family(printed, measure)
                    and (bound_measures is None or printed in bound_measures)
                ):
                    # "冲击吸收能量" aliases are shared by KU2/KV2; the printed
                    # symbol decides which measure a column belongs to when that
                    # measure is also bound by the recipe.
                    continue
            if _alias_matches(header, token) or _alias_matches(spaced[idx], token):
                return idx
    return None


def _key_column_candidates(headers: list[str], tokens: list[str]) -> list[int]:
    normalized = [normalize(header) for header in headers]
    found: list[int] = []
    for token in tokens:
        needle = normalize(str(token))
        if not needle:
            continue
        for index, header in enumerate(normalized):
            if index not in found and _alias_matches(header, needle):
                found.append(index)
    return found


def _grade_cell_score(cell: str) -> float:
    text = strip_footnote(str(cell or "")).strip()
    if not text or _placeholder_grade(text):
        return 0.0
    if re.search(r"\d", text):
        return 2.0
    if re.search(r"[A-Za-z]", text):
        return 1.0 if len(text) > 1 else 0.3
    return 0.0


def _pick_key_column(
    headers: list[str], data_rows: list[list[str]], tokens: list[str]
) -> int | None:
    """多列都匹配“牌号”时（如“材料牌号/材料牌号”），选真正装牌号的那一列。

    OCR 常把“类别 + 牌号”拆成两列且都叫“材料牌号”；取第一列会把
    “结构钢”当成牌号，导致大量重复键。
    """
    candidates = _key_column_candidates(headers, tokens)
    best: int | None = None
    best_score: tuple[float, int] = (-1.0, -1)
    for index in candidates:
        header = normalize(headers[index])
        penalty = 5.0 if any(
            marker in header for marker in ("质量等级", "等级", "class", "类别", "分类")
        ) else 0.0
        values = [
            _grade_cell_score(row[index] if index < len(row) else "")
            for row in data_rows[:30]
        ]
        hits = [score for score in values if score > 0]
        if not hits:
            continue
        score = (sum(hits) / len(hits) - penalty, len(hits))
        if score > best_score:
            best, best_score = index, score
    return best


def _unit_for_measure(measure: str, header: str, unit: str) -> str:
    """Printed fracture-toughness units are ksi√inch / MPa√m, not plain ksi."""
    name = str(measure or "")
    if name.upper() == "KIC" or name.startswith("断裂韧度"):
        text = normalize(header)
        if "sqrt" in text or "√" in text:
            if "ksi" in text:
                return "ksi√inch"
            if "mpa" in text:
                return "MPa√m"
    return unit


def _detect_measure(header: str, bound: str) -> str:
    """Return the symbol printed in the header when it is a known measure."""
    text = normalize(header)
    # Drop unit tails so ``抗拉强度/N/mm2`` is not mistaken for nitrogen.
    text = re.sub(r"(?:n/mm2|n/mm²|j/cm2|j/cm²|mpa|gpa)", "", text)
    if re.search(r"p0[.,]2(?!\d)", text):
        # 兼容 ISO 写法 Rp0,2（逗号）以及 “Tensile strength / Rp0,2” 组合表头。
        return "Rp0.2"
    if "/" in text:
        text = text.rsplit("/", 1)[0]
    if bound in {"Rp0.2", "ReL", "ReH"} and "p0.2" in text:
        # Headers such as ``ReL (Rp0.2)`` print both symbols; the proof
        # strength is the canonical measure (matches the legacy baseline).
        return "Rp0.2"
    has_cjk = bool(CJK_RE.search(text))
    parts = set(_header_parts(text))
    for symbol in SYMBOL_RE.findall(text):
        canonical = SYMBOL_CANON.get(symbol)
        if not canonical:
            continue
        if len(symbol) == 1 and (has_cjk or symbol not in parts):
            # Footnote markers such as "拉伸试验b" are not measures.
            continue
        return "HB" if canonical in {"HBW", "HBS"} else canonical
    return "HB" if bound in {"HBW", "HBS"} else bound


UNIT_WORDS = (
    ("n/mm2", "N/mm2"),
    ("n/mm²", "N/mm2"),
    ("mpa", "MPa"),
    ("ksi", "ksi"),
    ("j/cm2", "J/cm2"),
    ("j/cm²", "J/cm2"),
    ("percent", "%"),
    ("%", "%"),
    ("hbw", "HBW"),
    ("hb", "HB"),
    ("hrc", "HRC"),
    ("hrb", "HRB"),
    ("hv", "HV"),
)


TRUNCATED_UNITS = {
    "mp": "MPa",
    "m pa": "MPa",
    "mpa.": "MPa",
    "m p a": "MPa",
}


UNIT_TOKEN_RE = re.compile(
    r"^(?:mpa|gpa|ksi|n/mm2|j/cm2|hbw?|hbs|hr[abcv]|hv|%)$"
)


def _known_unit(text: str) -> str:
    """只认真正的计量单位，避免把 min/max 之类的限定词当成单位。"""
    value = normalize(strip_footnote(str(text or "")))
    if value in TRUNCATED_UNITS:
        return TRUNCATED_UNITS[value]
    if UNIT_TOKEN_RE.match(value):
        return UNIT_ROW_TOKENS.get(value, value)
    return ""


ELONGATION_MARKERS = (
    "elongation",
    "reduction of area",
    "伸长率",
    "延伸率",
    "断后伸长",
    "断面收缩",
)


def _extract_unit(header: str, explicit: str | None) -> str:
    lowered = normalize(header)
    # 延伸率/断面收缩率的标距（"2 in. or 50 mm"）不是单位。
    if any(marker in lowered for marker in ELONGATION_MARKERS):
        return "%"
    if "/" in header:
        # 形如“化学成分(质量分数)/% / C”的头，最后一段是元素符号而不是单位，
        # 因此按段从左到右找第一个像单位的片段。
        for part in (piece.strip() for piece in header.split("/")):
            canonical = _known_unit(part)
            if canonical:
                return canonical
    for token, unit in UNIT_WORDS:
        if token == "%":
            # “0.2% Offset”里的 % 属于牌号/指标名，不是单位。
            if re.search(r"(?<![\d.])%", lowered):
                return unit
            continue
        if token in lowered:
            return unit
    return explicit.strip() if explicit else ""


# OCR 常把单位行识别成数据行（如“Tensile Strength, min, ksi”下的 ksi/ksi/%），
# 这些单元格会被当成牌号或数值。按整行都是已知单位 token 判定为单位行。
UNIT_ROW_TOKENS = {
    "mpa": "MPa",
    "n/mm2": "N/mm2",
    "n/mm²": "N/mm2",
    "ksi": "ksi",
    "gpa": "GPa",
    "%": "%",
    "j": "J",
    "j/cm2": "J/cm2",
    "j/cm²": "J/cm2",
    "hbw": "HBW",
    "hb": "HB",
    "hrc": "HRC",
    "hrb": "HRB",
    "hv": "HV",
    "℃": "℃",
}


def _unit_cell(text: str) -> str:
    value = normalize(str(text or "").strip())
    return UNIT_ROW_TOKENS.get(value, "")


def _strip_unit_rows(
    rows: list[list[str]], sink: dict[int, str]
) -> list[list[str]]:
    """Drop repeated header/unit rows and record per-column units instead.

    OCR 常把单位行识别为数据行，甚至出现“表头 + 单位 + 单位”连续多行；
    这些行既不是牌号也不是数值，必须按列吸收为单位，否则会同一条记录
    混入 ksi/% 之类的原始文本，或把单位误标成整表唯一的“%”。
    """
    kept: list[list[str]] = []
    scanned = 0
    for row in rows:
        cells = [str(cell or "").strip() for cell in row]
        if scanned < 3:
            tokens = [cell for cell in cells if cell]
            units = [cell for cell in tokens if _unit_cell(cell)]
            header_like = bool(
                tokens
                and normalize(tokens[0]) in {"grade", "牌号", "钢号", "钢级", "质量等级"}
            )
            if units and not any(
                re.fullmatch(r"[<>≤≥≈~]?\s*\d+(?:\.\d+)?", cell) for cell in tokens
            ) and (len(units) >= 2 or header_like):
                for col, cell in enumerate(cells):
                    unit = _unit_cell(cell)
                    if unit and col not in sink:
                        sink[col] = unit
                scanned += 1
                continue
        kept.append(row)
    return kept


def _parse_value(cell: str, strip_marks: bool) -> dict[str, Any] | None:
    raw = strip_footnote(cell) if strip_marks else (cell or "").strip()
    if not raw:
        return None
    match = NUMBER_RE.search(raw)
    value = float(match.group()) if match else None
    operator = None
    for candidate in ("≥", "≤", ">", "<", "～", "~"):
        if candidate in raw:
            operator = candidate
            break
    return {"value": value, "raw": raw, "operator": operator}


def _measure_aliases(measure: str) -> list[str]:
    aliases = list(MEASURE_ALIASES.get(measure, []))
    # Single-letter element symbols (C, P, S, N, ...) must be searchable too.
    aliases.insert(0, measure)
    return list(dict.fromkeys(aliases))


def _binding_measure_aliases(
    measure: str, binding_aliases: dict[str, list[str]]
) -> list[str]:
    """L2 候选包可为单个 measure 追加 aliases（bindings.measures[*].aliases）。"""
    return list(
        dict.fromkeys([*_measure_aliases(measure), *binding_aliases.get(measure, [])])
    )


def _grade_valid(grade: str, *, allow_numeric: bool = False) -> bool:
    if not grade or len(grade) > GRADE_MAX_LEN:
        return False
    if len(grade) > 10 and CJK_RE.search(grade):
        # Footnote sentences ("SMLS,非冷扩径[见API Spec 5L...]") are not grades.
        return False
    if STANDARD_CODE_RE.match(grade):
        return False
    if any(mark in grade for mark in GRADE_SENTENCE_CHARS):
        return False
    if grade.startswith(("注", "说明", "备注")):
        return False
    if any(marker in grade for marker in GRADE_HEADER_MARKERS):
        return False
    if CJK_SPACED_RE.fullmatch(grade):
        # OCR-spaced section headers such as "结 梅 钢" / "不 锈 钢 及 耐 热 钢".
        return False
    if grade.endswith(("-", "—", "/")):
        # Footnote fragments such as "F1472-".
        return False
    if " + " in grade:
        # Combined document titles such as "ISO 5832-3 + ASTM F136-13".
        return False
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", grade):
        # Numeric grades (45, 20, 65Mn style) are valid only when the column
        # was explicitly identified as the row key.
        return allow_numeric and bool(re.fullmatch(r"\d{1,6}", grade))
    return True


GRADE_SPLIT_RE = re.compile(r"[、,，;；\s]+")
NUMERIC_GRADE_RE = re.compile(r"\d{1,4}")


def _grade_like(piece: str) -> bool:
    if not piece or len(piece) > 30:
        return False
    if NUMERIC_GRADE_RE.fullmatch(piece):
        return True
    if not re.search(r"\d", piece):
        return False
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", piece):
        return False
    return not any(ch in piece for ch in "。；，：;~≤≥<>%％")


def _split_grades(grade: str) -> list[str]:
    """Split merged grade cells that use explicit separators.

    Concatenated grades without separators are intentionally left untouched:
    splitting them would corrupt legitimate stainless grades such as
    ``022Cr17Ni12Mo2``.
    """
    text = GRADE_FOOTNOTE_RE.sub("", grade)
    text = GRADE_TAIL_MARKER_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = [part.strip() for part in GRADE_SPLIT_RE.split(text) if part.strip()]
    if len(parts) <= 1:
        return [text] if text else []
    valid = [part for part in parts if _grade_like(part)]
    return valid if len(valid) > 1 else [text]


def _condition_key(conditions: dict[str, str]) -> str:
    return "|".join(sorted(normalize(value) for value in conditions.values() if value))


def _is_footnote_row(cells: list[str]) -> bool:
    text = "".join(cells).strip()
    if not text:
        return True
    if text.startswith(("注", "注：", "说明", "备注")) or re.match(r"^[①-⑳]", text):
        return True
    # 长段落（如 ASTM 版权/说明脚注）常被 OCR 塞进表格最后一行，
    # 其中出现的数字不能当作测量值。
    if len(text) > 160:
        letters = len(re.findall(r"[\u4e00-\u9fffA-Za-z]", text))
        if letters / max(1, len(text)) > 0.6:
            return True
    # 以 "a." "b." 开头的脚注条目。
    return bool(re.match(r"^[a-gA-G][.、]\s*[A-Za-z\u4e00-\u9fff]", text))


def _element_symbol(text: str) -> str:
    cleaned = strip_footnote(text).strip()
    if ELEMENT_RE.fullmatch(cleaned) and cleaned in ELEMENT_SYMBOLS:
        return cleaned
    base = re.sub(r"\(.*?\)|（.*?）|[%％]", "", cleaned).strip()
    if ELEMENT_RE.fullmatch(base) and base in ELEMENT_SYMBOLS:
        return base
    name = ELEMENT_NAMES.get(re.sub(r"[^a-z]", "", base.lower()))
    if name:
        return name
    tokens = re.findall(r"[A-Z][a-z]?", base)
    if len(tokens) == 1 and tokens[0] in ELEMENT_SYMBOLS:
        return tokens[0]
    # Chinese labels keep the symbol in parentheses: 镍(Ni), 碳(C).
    tokens = re.findall(r"[A-Z][a-z]?", cleaned)
    if len(tokens) == 1 and tokens[0] in ELEMENT_SYMBOLS:
        return tokens[0]
    if ("+" in cleaned or "＋" in cleaned) and len(tokens) >= 2:
        if all(token in ELEMENT_SYMBOLS for token in tokens):
            return "+".join(tokens)
    return ""


def _nonvalue_label(raw: str) -> bool:
    """A cell that repeats an element/header label instead of holding a value."""
    text = str(raw or "").strip()
    return bool(_element_symbol(text)) or "元素" in text


def _prose_cell(raw: str, parsed: dict[str, Any]) -> bool:
    """Footnote prose accidentally aligned with a measure column."""
    text = str(raw or "").strip()
    if len(text) > 80:
        # 长段落里的数字（如脚注 "equal to 75mm"）不是该列的测量值。
        return True
    if parsed.get("value") is not None:
        return False
    return _nonvalue_label(text) or (len(text) > 24 and bool(CJK_RE.search(text)))


# 金属材料常见性能的合理区间；超出视为错列/错行/单位错误，不入记录。
PLAUSIBLE_MEASURE_RANGES = {
    "Rm": (100.0, 2500.0),
    "Rp0.2": (60.0, 2200.0),
    "Rp1.0": (60.0, 2200.0),
    "ReL": (60.0, 2200.0),
    "ReH": (60.0, 2200.0),
    "A": (1.0, 95.0),
    "Z": (1.0, 90.0),
    "KV2": (1.0, 400.0),
    "KU2": (1.0, 400.0),
    "KU5": (1.0, 400.0),
    "HB": (30.0, 700.0),
    "HBW": (30.0, 700.0),
    "HRC": (10.0, 75.0),
    "HRB": (30.0, 130.0),
    "HV": (30.0, 1000.0),
}


def _plausible_measure(measure: str, value: Any, unit: str = "") -> bool:
    bounds = PLAUSIBLE_MEASURE_RANGES.get(str(measure))
    if bounds is None or not isinstance(value, (int, float)):
        return True
    numeric = float(value)
    label = normalize(unit or "")
    # 强度类区间按 MPa 定义；单位缺失或标注错误时，允许按 ksi / kgf·mm⁻²
    # 解释，避免把真实的英制数值当异常丢弃。
    candidates = [numeric]
    if label in {"ksi", "ksl"}:
        candidates = [numeric * 6.89476]
    elif label in {"kgf/mm2", "kgf/mm²"}:
        candidates = [numeric * 9.80665]
    else:
        candidates += [numeric * 6.89476, numeric * 9.80665]
    return any(bounds[0] <= item <= bounds[1] for item in candidates)


def _grade_from_header(header: str) -> str:
    text = strip_footnote(header)
    text = text.split("/")[-1].strip() or text
    text = re.sub(r"^(牌号|钢号|grade|材料牌号)\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


MIN_LABEL_RE = re.compile(
    r"^(min|minimum|min\.|最小值|下限)$", re.IGNORECASE
)
MAX_LABEL_RE = re.compile(
    r"^(max|maximum|max\.|最大值|上限)$", re.IGNORECASE
)


def _column_empty(data_rows: list[list[str]], col: int) -> bool:
    for row in data_rows:
        value = str(row[col] if col < len(row) else "").strip()
        if value and value not in SKIP_CELL_VALUES:
            return False
    return True


def _min_max_columns(
    columns: list[tuple[int, str]], data_rows: list[list[str]]
) -> tuple[int, int] | None:
    """Return (min_col, max_col) when the value columns are Min/Max pairs."""
    min_col = next(
        (
            col
            for col, condition in columns
            if MIN_LABEL_RE.fullmatch(normalize(condition))
        ),
        None,
    )
    max_col = next(
        (
            col
            for col, condition in columns
            if MAX_LABEL_RE.fullmatch(normalize(condition))
        ),
        None,
    )
    if min_col is None and max_col is None:
        return None
    if max_col is not None and _column_empty(data_rows, max_col) and min_col is not None:
        # OCR sometimes mislabels the Max column as a second "Min"; the values
        # (and the following column) still show where Max lives.
        candidate = min_col + 1
        if candidate != max_col and not _column_empty(data_rows, candidate):
            max_col = candidate
    if min_col is not None and _column_empty(data_rows, min_col) and max_col is not None:
        candidate = max_col - 1
        if candidate != min_col and not _column_empty(data_rows, candidate):
            min_col = candidate
    return min_col if min_col is not None else -1, max_col if max_col is not None else -1


def _range_property(
    low: dict[str, Any] | None, high: dict[str, Any] | None, unit: str
) -> dict[str, Any] | None:
    """Merge Min/Max cells into one requirement (range, ≤max or ≥min)."""
    low_raw = str((low or {}).get("raw") or "").strip()
    high_raw = str((high or {}).get("raw") or "").strip()
    if low_raw in SKIP_CELL_VALUES:
        low_raw = ""
    if high_raw in SKIP_CELL_VALUES:
        high_raw = ""
    if not low_raw and not high_raw:
        return None
    if low_raw and high_raw:
        if low_raw == high_raw:
            raw, operator, value = low_raw, "", (low or {}).get("value")
        else:
            raw, operator, value = f"{low_raw}~{high_raw}", "~", (low or {}).get("value")
    elif high_raw:
        raw, operator, value = f"≤{high_raw}", "≤", (high or {}).get("value")
    else:
        raw, operator, value = f"≥{low_raw}", "≥", (low or {}).get("value")
    return {"raw": raw, "operator": operator, "value": value, "unit": unit}


def _parse_element_table(
    table: dict[str, Any],
    *,
    table_id: str,
    page_no: int,
    profile: str,
    recipe_id: str,
    recipe_version: str,
    strip_marks: bool,
    units: list[str],
    binding_units: dict[str, str],
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Parse chemical tables that are organised by element instead of by grade.

    Two layouts are supported: element labels in the first column (values per
    condition column) and element labels in the header (values per row group).
    """
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None

    for block_id, headers, data_rows, meta in _iter_blocks(table):
        meta_units = meta[0]
        row_total += len(data_rows)
        if not headers or not data_rows:
            continue

        # 转置布局：首列几乎全是元素符号，且表头里没有元素列（否则是“元素为列、
        # 行为依据”的混合布局）。牌号列存在时说明按牌号成行，也不是转置。
        grade_col = _find_column(headers, ["牌号", "钢号", "钢级", "grade"], set())
        first_cells = [
            strip_footnote(row[0] if row else "")
            for row in data_rows[:12]
            if row and strip_footnote(row[0] if row else "")
        ]
        symbol_hits = sum(1 for cell in first_cells if _element_symbol(cell))
        header_elements = sum(1 for header in headers[1:] if _element_symbol(header))
        element_row_layout = (
            len(first_cells) >= 2
            and symbol_hits >= 2
            and symbol_hits >= 0.8 * len(first_cells)
            and header_elements == 0
        )
        # OCR 常保留“牌号 / 牌号”两列合并表头，元素标签落进牌号块内部；
        # 此时元素列在表头第 1~3 列，值列相对牌号表头右移一列。
        grade_columns = [
            (index, _grade_from_header(str(header)))
            for index, header in enumerate(headers)
            if str(header).strip()
            and "元素" not in str(header)
            and str(header).strip().lower() != "element"
            and any(char.isdigit() for char in str(header))
            and _grade_valid(strip_footnote(str(header)), allow_numeric=True)
        ]
        merged_label_col: int | None = None
        merged_offset = 0
        if not element_row_layout and grade_columns:
            first_grade = grade_columns[0][0]
            best_index: int | None = None
            best_hits = 0
            for index in (first_grade - 2, first_grade - 1, first_grade):
                if not (0 <= index < len(headers)):
                    continue
                hits = sum(
                    1
                    for row in data_rows[:12]
                    if index < len(row) and _element_symbol(str(row[index]))
                )
                # 优先命中数最多的列：GB/T 6516 的合并标签列前一列也含
                # "Co"/"Ni+Co" 等符号，取“第一个命中”会错位。
                if hits > best_hits:
                    best_index, best_hits = index, hits
            if best_hits >= 2 and best_index is not None:
                merged_label_col = best_index
            if merged_label_col is not None and merged_label_col == first_grade:
                merged_offset = 1
        if element_row_layout or merged_label_col is not None:
            if element_row_layout:
                columns = [
                    (col, _grade_from_header(headers[col]))
                    for col in range(1, len(headers))
                ]
                label_index = 0
                value_offset = 0
                min_max = _min_max_columns(columns, data_rows)
                if min_max is not None:
                    min_col, max_col = min_max
                    properties: dict[str, Any] = {}
                    cells: dict[str, str] = {}
                    for row in data_rows:
                        if label_index >= len(row):
                            continue
                        symbol = _element_symbol(str(row[label_index]))
                        if not symbol:
                            continue
                        low = (
                            _parse_value(row[min_col], strip_marks)
                            if 0 <= min_col < len(row)
                            else None
                        )
                        high = (
                            _parse_value(row[max_col], strip_marks)
                            if 0 <= max_col < len(row)
                            else None
                        )
                        unit = (
                            binding_units.get(symbol, "")
                            or ("%" if profile == "chemical_composition" else "")
                        )
                        merged = _range_property(low, high, unit)
                        if merged is None:
                            continue
                        merged["column"] = headers[max_col if max_col >= 0 else min_col]
                        properties[symbol] = merged
                        cells[symbol] = merged["raw"]
                    if properties:
                        record_id = f"{table_id}-C1"
                        conditions = {"依据": "Min/Max"}
                        records.append(
                            {
                                "record_id": record_id,
                                "table_id": table_id,
                                "block_id": block_id,
                                "page_no": page_no,
                                "row_index": 0,
                                "recipe_id": recipe_id,
                                "recipe_version": recipe_version,
                                "profile": profile,
                                "grade": "~",
                                "conditions": conditions,
                                "condition_key": _condition_key(conditions),
                                "properties": properties,
                                "evidence_refs": [record_id],
                                "source": {
                                    "table_id": table_id,
                                    "block_id": block_id,
                                    "page_no": page_no,
                                    "row_index": 0,
                                },
                            }
                        )
                        evidence.append(
                            {
                                "evidence_id": record_id,
                                "table_id": table_id,
                                "block_id": block_id,
                                "page_no": page_no,
                                "row_index": 0,
                                "raw_row": list(cells.values()),
                                "cells": cells,
                            }
                        )
                    continue
            else:
                columns = list(grade_columns)
                label_index = merged_label_col or 0
                value_offset = merged_offset
            for col, condition in columns:
                if not condition or _placeholder_grade(condition):
                    # Keep the printed block label (e.g. "元素含量，wt.% Min").
                    condition = _header_text(headers[col]) or f"col{col + 1}"
                value_col = col + value_offset
                properties: dict[str, Any] = {}
                cells: dict[str, str] = {}
                for row in data_rows:
                    if label_index >= len(row) or value_col >= len(row):
                        continue
                    label_text = str(row[label_index])
                    symbol = _element_symbol(label_text)
                    if not symbol:
                        continue
                    parsed = _parse_value(row[value_col], strip_marks)
                    if parsed is None:
                        raw_cell = str(row[value_col] or "").strip()
                        # 金标把 Ti=Balance/余量 也作为成分项保留，不能当空值丢掉。
                        if symbol and normalize(raw_cell) in {
                            "balance",
                            "bal.",
                            "余量",
                            "余",
                        }:
                            properties[symbol] = {
                                "value": None,
                                "raw": raw_cell,
                                "operator": None,
                                "unit": "",
                            }
                            cells[symbol] = raw_cell
                        continue
                    if not parsed.get("operator"):
                        # The limit is printed in the element label
                        # ("Co,不大于" / "(Ni+Co),不小于") or in the merged
                        # group label to its left ("杂质含量,不大于").
                        limit_text = " ".join(
                            [label_text, *[str(cell) for cell in row[:label_index]]]
                        )
                        if "不大于" in limit_text or re.search(
                            r"\bmax(?:imum)?\b", limit_text, re.IGNORECASE
                        ):
                            parsed["operator"] = "≤"
                        elif "不小于" in limit_text or re.search(
                            r"\bmin(?:imum)?\b", limit_text, re.IGNORECASE
                        ):
                            parsed["operator"] = "≥"
                    raw_value = str(parsed.get("raw") or "").strip()
                    if raw_value in SKIP_CELL_VALUES:
                        continue
                    if _prose_cell(raw_value, parsed):
                        continue
                    unit = (
                        _extract_unit(headers[col], explicit_unit)
                        or (meta_units[col] if col < len(meta_units) else "")
                        or binding_units.get(symbol, "")
                    )
                    if not unit and profile == "chemical_composition":
                        unit = "%"
                    parsed["unit"] = unit
                    parsed["column"] = headers[col]
                    properties[symbol] = parsed
                    cells[symbol] = row[value_col]
                if not properties:
                    continue
                record_id = f"{table_id}-C{col + 1}"
                grade = "~" if element_row_layout else condition
                conditions = {"依据": condition} if element_row_layout else {}
                records.append(
                    {
                        "record_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": col - 1,
                        "recipe_id": recipe_id,
                        "recipe_version": recipe_version,
                        "profile": profile,
                        "grade": grade,
                        "conditions": conditions,
                        "condition_key": normalize(condition)
                        if element_row_layout
                        else "",
                        "properties": properties,
                        "evidence_refs": [record_id],
                        "source": {
                            "table_id": table_id,
                            "block_id": block_id,
                            "page_no": page_no,
                            "row_index": col - 1,
                        },
                    }
                )
                evidence.append(
                    {
                        "evidence_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": col - 1,
                        "raw_row": list(cells.values()),
                        "cells": cells,
                    }
                )
            continue

        element_cols = [
            (
                idx,
                _element_symbol(header)
                or (meta[2][idx] if idx < len(meta[2]) else ""),
            )
            for idx, header in enumerate(headers[1:], start=1)
        ]
        element_cols = [(idx, symbol) for idx, symbol in element_cols if symbol]
        if not element_cols:
            diagnostics.append(
                {
                    "code": "ELEMENT_COLUMNS_NOT_FOUND",
                    "message": f"table {table_id} has no element labels",
                    "severity": "warning",
                    "detail": {"table_id": table_id, "headers": headers},
                }
            )
            continue
        for row_index, row in enumerate(data_rows):
            if _is_footnote_row(row):
                continue
            label_col = grade_col if grade_col is not None else 0
            label = (
                strip_footnote(row[label_col] if label_col < len(row) else "") or "含量"
            )
            if not _grade_valid(label):
                continue
            grade = label if grade_col is not None else "~"
            conditions = {} if grade_col is not None else {"依据": label}
            properties = {}
            cells = {}
            for col, symbol in element_cols:
                if col >= len(row):
                    continue
                parsed = _parse_value(row[col], strip_marks)
                if parsed is None:
                    continue
                raw_value = str(parsed.get("raw") or "").strip()
                if raw_value in SKIP_CELL_VALUES:
                    continue
                if _prose_cell(raw_value, parsed):
                    continue
                unit = (
                    _extract_unit(headers[col], explicit_unit)
                    or (meta_units[col] if col < len(meta_units) else "")
                    or binding_units.get(symbol, "")
                )
                if not unit and profile == "chemical_composition":
                    unit = "%"
                parsed["unit"] = unit
                parsed["column"] = headers[col]
                properties[symbol] = parsed
                cells[symbol] = row[col]
            if not properties:
                continue
            record_id = f"{table_id}-R{row_index + 1}"
            records.append(
                {
                    "record_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "profile": profile,
                    "grade": grade,
                    "conditions": conditions,
                    "condition_key": _condition_key(conditions),
                    "properties": properties,
                    "evidence_refs": [record_id],
                    "source": {
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                    },
                }
            )
            evidence.append(
                {
                    "evidence_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "raw_row": list(row),
                    "cells": cells,
                }
            )

    if not records:
        diagnostics.append(
            {
                "code": "NO_RECORDS",
                "message": f"table {table_id} produced no records",
                "severity": "warning",
                "detail": {"table_id": table_id},
            }
        )
    summary = {
        "table_id": table_id,
        "page_no": page_no,
        "profile": profile,
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "rows": row_total,
        "records": len(records),
    }
    return records, evidence, summary


def _parse_chemical_columns(
    table: dict[str, Any],
    *,
    table_id: str,
    page_no: int,
    profile: str,
    recipe_id: str,
    recipe_version: str,
    strip_marks: bool,
    units: list[str],
    binding_units: dict[str, str],
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Fallback for grade-less chemical tables (element columns, one data row)."""
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None
    for block_id, headers, data_rows, meta in _iter_blocks(table):
        meta_units = meta[0]
        row_total += len(data_rows)
        element_cols = [
            (idx, symbol or (meta[2][idx] if idx < len(meta[2]) else ""))
            for idx, header in enumerate(headers)
            if (symbol := _element_symbol(header))
            or (idx < len(meta[2]) and meta[2][idx])
        ]
        if len(element_cols) < 3:
            continue
        # 即使没有绑定标量，元素列齐全时仍可按行成记录；此时牌号列（若存在）
        # 是该行的真实牌号，不能再用占位符“~”。
        grade_col = _find_column(headers, ["牌号", "钢号", "钢级", "grade"], set())
        last_grade = ""
        for row_index, row in enumerate(data_rows):
            if _is_footnote_row(row):
                continue
            grade = ""
            if grade_col is not None and grade_col < len(row):
                grade = strip_footnote(row[grade_col])
                if _placeholder_grade(grade) or not _grade_valid(grade):
                    continue
                last_grade = grade
            elif last_grade:
                # 牌号纵向合并：续行牌号为空时沿用上一条，避免落成占位符。
                grade = last_grade
            if not grade:
                grade = "~"
            properties: dict[str, Any] = {}
            cells: dict[str, str] = {}
            for col, symbol in element_cols:
                if col >= len(row):
                    continue
                parsed = _parse_value(row[col], strip_marks)
                if parsed is None:
                    continue
                raw_value = str(parsed.get("raw") or "").strip()
                if raw_value in SKIP_CELL_VALUES:
                    continue
                if _prose_cell(raw_value, parsed):
                    continue
                unit = (
                    _extract_unit(headers[col], explicit_unit)
                    or (meta_units[col] if col < len(meta_units) else "")
                    or binding_units.get(symbol, "")
                )
                if not unit and profile == "chemical_composition":
                    unit = "%"
                parsed["unit"] = unit
                parsed["column"] = headers[col]
                properties[symbol] = parsed
                cells[symbol] = row[col]
            if len(properties) < 2:
                continue
            record_id = f"{table_id}-R{row_index + 1}"
            records.append(
                {
                    "record_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "profile": profile,
                    "grade": grade,
                    "conditions": {},
                    "condition_key": "",
                    "properties": properties,
                    "evidence_refs": [record_id],
                    "source": {
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                    },
                }
            )
            evidence.append(
                {
                    "evidence_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "raw_row": list(row),
                    "cells": cells,
                }
            )
    if not records:
        diagnostics.append(
            {
                "code": "NO_RECORDS",
                "message": f"table {table_id} produced no records",
                "severity": "warning",
                "detail": {"table_id": table_id},
            }
        )
    summary = {
        "table_id": table_id,
        "page_no": page_no,
        "profile": profile,
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "rows": row_total,
        "records": len(records),
    }
    return records, evidence, summary


ORPHAN_MEASURES = {"KV2", "KU2", "KU5", "KV8"}
TEMPERATURE_CONDITIONS = {"温度", "试验温度"}


def _merge_signature(item: Any) -> tuple:
    """比较两个测量值是否描述同一事实（忽略表头拼写差异）。"""
    if not isinstance(item, dict):
        return (str(item),)
    value = item.get("value")
    if value is None:
        return ("raw", str(item.get("raw") or "").strip(), str(item.get("unit") or ""))
    return (value, str(item.get("unit") or ""), str(item.get("operator") or ""))


def _fragment_compatible(current: dict[str, Any], incoming: dict[str, Any]) -> bool:
    for name in set(current) & set(incoming):
        if _merge_signature(current[name]) != _merge_signature(incoming[name]):
            return False
    return True


def _merge_fragments(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一牌号+条件下字段互补或一致的记录（跨页/跨表碎片）合并为一条。

    字段重叠且数值冲突时不合并，避免把不同试样/不同规格的真实记录合并掉；
    重叠字段值一致时合并，用于吸收跨页续表产生的重复行。
    """
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    for record in records:
        # 只合并同一张表内的碎片；不同表（成分/拉伸/硬度）同牌号同条件
        # 不是续表，合并会把不同检验项目混进一条记录。
        key = (
            str(record.get("profile") or ""),
            str(record.get("table_id") or ""),
            str(record.get("grade") or ""),
            str(record.get("condition_key") or ""),
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = record
            result.append(record)
            continue
        properties = record.get("properties") or {}
        current = existing.get("properties") or {}
        if not _fragment_compatible(current, properties):
            result.append(record)
            continue
        current.update(properties)
        existing["properties"] = current
        existing["evidence_refs"] = [
            *(existing.get("evidence_refs") or []),
            *(record.get("evidence_refs") or []),
        ]
    return result


def _disambiguate_duplicate_keys(
    records: list[dict[str, Any]], diagnostics: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """同一牌号/条件下仍有多行且数值冲突时，按出现顺序补充记录序号。

    OCR 丢失了区分条件（厚度/品种等）时，不能凭空合并有冲突的行，也不能
    保留重复键；用可追溯的“记录序号”条件保证键唯一，并留下诊断供人工复核。
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            str(record.get("grade") or ""),
            str(record.get("condition_key") or ""),
        )
        groups.setdefault(key, []).append(record)
    adjusted = 0
    for (grade, condition_key), items in groups.items():
        if len(items) < 2:
            continue
        for occurrence, record in enumerate(items[1:], start=2):
            conditions = dict(record.get("conditions") or {})
            conditions["记录序号"] = str(occurrence)
            record["conditions"] = conditions
            record["condition_key"] = _condition_key(conditions)
            adjusted += 1
        diagnostics.append(
            {
                "code": "DUPLICATE_KEY_DISAMBIGUATED",
                "message": (
                    f"{len(items)} rows share grade {grade or '~'} and condition "
                    f"{condition_key or '-'}; occurrence index appended"
                ),
                "severity": "warning",
                "detail": {
                    "grade": grade,
                    "condition_key": condition_key,
                    "record_ids": [str(item.get("record_id") or "") for item in items],
                },
            }
        )
    return records, adjusted


def _drop_orphan_records(
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    table_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """没有 row key 的独立冲击小表不产出记录（带温度条件的除外）。"""
    orphan_ids = {
        str(record.get("record_id") or "")
        for record in records
        if str(record.get("grade") or "").strip() in {"", "~"}
        and set(record.get("properties") or {}).issubset(ORPHAN_MEASURES)
        and not (TEMPERATURE_CONDITIONS & set(record.get("conditions") or {}))
        and record.get("record_id")
    }
    if not orphan_ids or len(orphan_ids) != len(records):
        return records, evidence
    diagnostics.append(
        {
            "code": "ORPHAN_TABLE_SKIPPED",
            "message": f"table {table_id} has no row key; impact-only records skipped",
            "severity": "info",
            "detail": {"table_id": table_id, "records": len(orphan_ids)},
        }
    )
    return [], []


def parse_table(
    table: dict[str, Any],
    manifest: dict[str, Any] | None,
    assignment: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    table_id = str(table.get("table_id") or "unknown")
    page_no = int(table.get("page_no") or 0)
    global _revision_reported
    fingerprint = (
        str(table.get("caption") or ""),
        tuple(tuple(str(cell) for cell in row) for row in (table.get("rows") or [])),
        tuple(
            tuple(str(part) for part in path)
            for path in (table.get("header_paths") or [])
        ),
    )
    if fingerprint in _table_fingerprints:
        diagnostics.append(
            {
                "code": "DUPLICATE_TABLE",
                "message": f"table {table_id} duplicates an earlier table",
                "severity": "info",
                "detail": {"table_id": table_id},
            }
        )
        return [], [], {
            "table_id": table_id,
            "page_no": page_no,
            "profile": str((manifest or {}).get("profile") or table.get("profile") or "unknown"),
            "recipe_id": str(
                (assignment or {}).get("recipe_id") or (manifest or {}).get("recipe_id") or ""
            ),
            "recipe_version": str(
                (assignment or {}).get("version") or (manifest or {}).get("version") or ""
            ),
            "rows": len(table.get("rows") or []),
            "records": 0,
        }
    _table_fingerprints.add(fingerprint)
    if not _revision_reported:
        diagnostics.append(
            {
                "code": "PARSER_BUNDLE",
                "message": f"parser revision {PARSER_REVISION}",
                "severity": "info",
                "detail": {"revision": PARSER_REVISION},
            }
        )
        _revision_reported = True
    recipe_id = str((assignment or {}).get("recipe_id") or (manifest or {}).get("recipe_id") or "")
    recipe_version = str(
        (assignment or {}).get("version") or (manifest or {}).get("version") or ""
    )
    profile = str((manifest or {}).get("profile") or table.get("profile") or "unknown")
    bindings = (manifest or {}).get("bindings") or {}
    binding_units = {
        str(name): str((config or {}).get("unit") or "")
        for name, config in (bindings.get("measures") or {}).items()
        if isinstance(config, dict)
    }
    rules = (manifest or {}).get("rules") or {}
    strip_marks = bool(rules.get("strip_footnote_marks", True))
    units = table.get("units") or []
    try:  # imported as a package (tests)
        from .strategies import nonrecord_reason
    except ImportError:  # flat runtime image (/engine)
        from strategies import nonrecord_reason

    reason = nonrecord_reason(table)
    if reason:
        diagnostics.append(
            {
                "code": "NONRECORD_TABLE",
                "message": f"table {table_id} is not a record table: {reason}",
                "severity": "info",
                "detail": {"table_id": table_id, "reason": reason},
            }
        )
        return [], [], {
            "table_id": table_id,
            "page_no": page_no,
            "profile": profile,
            "recipe_id": recipe_id,
            "recipe_version": recipe_version,
            "rows": len(table.get("rows") or []),
            "records": 0,
        }
    if profile == "heat_treatment":
        heat_records, heat_evidence, heat_summary = _parse_heat_table(
            table,
            table_id=table_id,
            page_no=page_no,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            diagnostics=diagnostics,
        )
        _apply_document_grade(heat_records, diagnostics, table_id)
        return heat_records, heat_evidence, heat_summary
    if rules.get("transposed"):
        element_records, element_evidence, element_summary = _parse_element_table(
            table,
            table_id=table_id,
            page_no=page_no,
            profile=profile,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            strip_marks=strip_marks,
            units=units,
            binding_units=binding_units,
            diagnostics=diagnostics,
        )
        _apply_document_grade(element_records, diagnostics, table_id)
        return element_records, element_evidence, element_summary

    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    record_count = 0
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None

    for block_id, headers, data_rows, meta in _iter_blocks(table):
        meta_units, meta_conditions, _meta_elements = meta
        # W3：表头列级单位先入库，单位行识别到的单位优先覆盖。
        column_units: dict[int, str] = {
            index: unit
            for index, unit in enumerate(meta_units)
            if unit and index < len(headers)
        }
        data_rows = _strip_unit_rows(data_rows, column_units)
        # OCR sometimes keeps the direction sub-header as the first data row
        # (冲击表“纵向 | 横向”): it carries the direction per column.
        direction_map: dict[int, str] = {}
        if data_rows:
            first_row = data_rows[0]
            direction_hits = {
                index: str(cell).strip()
                for index, cell in enumerate(first_row)
                if normalize(cell) in DIRECTION_LABELS
            }
            numeric_hits = sum(
                1
                for cell in first_row
                if DATA_CELL_RE.fullmatch(str(cell).strip())
            )
            if len(direction_hits) >= 2 and numeric_hits == 0:
                direction_map = direction_hits
                data_rows = data_rows[1:]
        used: set[int] = set()
        row_key_tokens = list(
            dict.fromkeys([*(bindings.get("row_key") or []), *DEFAULT_ROW_KEY])
        )
        key_col = _pick_key_column(headers, data_rows, row_key_tokens)
        if key_col is None:
            key_col = _find_column(headers, row_key_tokens, set())
        key_found = key_col is not None
        if key_col is None:
            diagnostics.append(
                {
                    "code": "ROW_KEY_NOT_FOUND",
                    "message": f"table {table_id} has no row-key column",
                    "severity": "warning",
                    "detail": {"table_id": table_id, "headers": headers},
                }
            )
            key_col = 0
        # Tables such as AMS fracture-toughness schedules have no grade column:
        # orientation/thickness/temperature columns are conditions and the
        # grade comes from the document title.
        no_key_conditions: dict[str, list[int]] = {}
        if key_found:
            used.add(key_col)
        else:
            for index, header in enumerate(headers):
                name = _condition_name(header)
                if name:
                    no_key_conditions.setdefault(name, []).append(index)
                    used.add(index)
            # W3：表头没有条件关键词、但列级继承出条件（纵向/≤16/室温）的列。
            for index, name in enumerate(meta_conditions):
                if not name or index >= len(headers) or index in used:
                    continue
                if index < len(_meta_elements) and _meta_elements[index]:
                    continue
                no_key_conditions.setdefault(name, []).append(index)
                used.add(index)
        # 牌号被拆成“钢级/质量等级”两列时（如 Q355 + B），拼成完整牌号。
        class_col: int | None = None
        if key_found and key_col + 1 < len(headers):
            grade_header = normalize(headers[key_col])
            class_header = normalize(headers[key_col + 1])
            if (
                (
                    "牌号" in grade_header
                    or "钢级" in grade_header
                    or "钢号" in grade_header
                    or "grade" in grade_header
                )
                and (
                    "质量等级" in class_header
                    or "等级" in class_header
                    or "class" in class_header
                )
            ):
                class_col = key_col + 1
                used.add(class_col)

        measure_cols: dict[str, int] = {}
        pending: list[str] = []
        bound_measures = {
            _canonical_measure(str(name)) for name in (bindings.get("measures") or {})
        }
        # L2 候选包可通过 bindings.measures[*].aliases 为新版本表头补别名。
        binding_aliases: dict[str, list[str]] = {}
        for name, config in (bindings.get("measures") or {}).items():
            if not isinstance(config, dict):
                continue
            aliases = [str(alias) for alias in (config.get("aliases") or []) if str(alias)]
            if aliases:
                binding_aliases[str(name)] = aliases
        # Pass 1: exact symbols win, so HB never steals HBW (and C never Cr).
        for measure in (bindings.get("measures") or {}):
            col = _find_column(
                headers,
                [str(measure)],
                used,
                skip_group=True,
                measure=str(measure),
                bound_measures=bound_measures,
            )
            if col is None:
                col = _find_column(
                    headers,
                    [str(measure)],
                    used,
                    measure=str(measure),
                    bound_measures=bound_measures,
                )
            if col is None:
                pending.append(str(measure))
                continue
            used.add(col)
            measure_cols[str(measure)] = col
        # Pass 2: alias matching for columns without an explicit symbol.
        for measure in pending:
            col = _find_column(
                headers,
                _binding_measure_aliases(measure, binding_aliases),
                used,
                skip_group=True,
                measure=measure,
                bound_measures=bound_measures,
            )
            if col is None:
                col = _find_column(
                    headers,
                    _binding_measure_aliases(measure, binding_aliases),
                    used,
                    measure=measure,
                    bound_measures=bound_measures,
                )
            if col is None:
                diagnostics.append(
                    {
                        "code": "MEASURE_COLUMN_MISSING",
                        "message": f"measure {measure} not found in table {table_id}",
                        "severity": "warning",
                        "detail": {
                            "table_id": table_id,
                            "measure": str(measure),
                            # 表头是区分"缺列"和"缺绑定"的关键证据。
                            "headers": headers,
                            "bound_measures": sorted(bound_measures or []),
                        },
                    }
                )
                continue
            used.add(col)
            measure_cols[measure] = col

        # Repeated measures under different header groups (room/high temp,
        # direction, specimen size) become additional records, not lost columns.
        extra_groups: dict[str, list[tuple[str, int, str]]] = {}
        primary_labels = {
            _group_label(headers[col]) for col in measure_cols.values() if col < len(headers)
        }
        for measure, primary_col in list(measure_cols.items()):
            probe = set(used)
            probe.add(primary_col)
            while True:
                col = _find_column(
                    headers,
                    [str(measure)],
                    probe,
                    skip_group=True,
                    measure=measure,
                    bound_measures=bound_measures,
                )
                if col is None:
                    col = _find_column(
                        headers,
                        _binding_measure_aliases(measure, binding_aliases),
                        probe,
                        skip_group=True,
                        measure=measure,
                        bound_measures=bound_measures,
                    )
                if col is None:
                    break
                probe.add(col)
                label = _group_label(headers[col])
                direction = direction_map.get(col, "")
                if not label and direction:
                    # Repeated measure columns without a group heading are
                    # distinguished by their direction row.
                    label = f"{headers[col]}|{direction}"
                if label and label not in primary_labels:
                    extra_groups.setdefault(label, []).append(
                        (measure, col, direction)
                    )

        condition_cols: dict[str, int] = {}
        # Longest label wins so "交货状态" is not reduced to "状态".
        condition_tokens = sorted(
            dict.fromkeys([*(bindings.get("conditions") or []), *CONDITION_TOKENS]),
            key=lambda token: -len(str(token)),
        )
        for token in condition_tokens:
            col = _find_column(headers, [str(token)], used)
            if col is not None:
                header = normalize(headers[col])
                if any(
                    marker in header
                    for marker in ("冲击吸收能量", "侧膨胀", "侧向膨胀")
                ):
                    # “3个试样平均冲击吸收能量”里的“试样”不是条件列。
                    continue
                used.add(col)
                condition_cols[str(token)] = col

        # 合并单元格：牌号列纵向合并时，续行的牌号单元格为空，应沿用上一行牌号。
        last_grade_cell = ""
        merged_grade_fills = 0
        # 条件列（状态/厚度/方向）同样可能是纵向合并单元格：续行为空时沿用
        # 上一行条件，否则同一牌号的多行会因条件丢失而变成重复键。
        last_conditions: dict[str, str] = {}
        merged_condition_fills = 0

        for row_index, row in enumerate(data_rows):
            row_total += 1
            if _is_footnote_row(row) or _is_limit_row(row):
                continue
            grade_cell = row[key_col] if key_col < len(row) else ""
            if class_col is not None and class_col < len(row):
                class_cell = strip_footnote(row[class_col])
                if class_cell and class_cell not in grade_cell:
                    grade_cell = f"{grade_cell}{class_cell}"
            raw_grade = strip_footnote(grade_cell) if strip_marks else (grade_cell or "").strip()
            if key_found and not raw_grade and last_grade_cell:
                raw_grade = last_grade_cell
                merged_grade_fills += 1
            if _placeholder_grade(raw_grade):
                diagnostics.append(
                    {
                        "code": "ROW_KEY_PLACEHOLDER",
                        "message": "row skipped: key cell is a block label, not a grade",
                        "severity": "info",
                        "detail": {"table_id": table_id, "row_index": row_index},
                    }
                )
                continue
            dimension_condition = None
            if no_key_conditions:
                grades = ["~"]
            elif not key_found and _is_dimension_header(headers[key_col]):
                # A dimension/size column is a condition, not a grade.  This
                # happens in tables such as AMS 4050 Table 2B where the first
                # column is "Nominal Thickness" and no temper/grade column
                # exists.
                dimension_condition = raw_grade
                grades = ["~"] if dimension_condition else []
            else:
                grades = [
                    item
                    for item in _split_grades(raw_grade)
                    if _grade_valid(item, allow_numeric=key_found)
                ]
            if not grades:
                diagnostics.append(
                    {
                        "code": "ROW_SKIPPED",
                        "message": "row skipped: empty or invalid row key",
                        "severity": "info",
                        "detail": {"table_id": table_id, "row_index": row_index},
                    }
                )
                continue
            if key_found and raw_grade:
                last_grade_cell = raw_grade

            conditions: dict[str, str] = {}
            for name, col in sorted(condition_cols.items()):
                value = strip_footnote(row[col]) if col < len(row) else ""
                # 条件单元格里出现表头原文或“元素”提示语，不是真实条件值。
                # 注意不能用 _nonvalue_label：它会把 H14/H24 这类铝合金状态
                # 误判成元素符号而丢弃，导致同一牌号的行变成重复键。
                if value:
                    if normalize(value) == normalize(headers[col]) or "元素" in value:
                        continue
                    last_conditions[name] = value
                else:
                    value = last_conditions.get(name, "")
                    if not value:
                        continue
                    merged_condition_fills += 1
                conditions[name] = value
            if dimension_condition:
                conditions["规格"] = dimension_condition
            for name, cols in no_key_conditions.items():
                parts = []
                for col in cols:
                    value = strip_footnote(row[col]) if col < len(row) else ""
                    if value and value not in SKIP_CELL_VALUES:
                        parts.append(value)
                # A split thickness column ("Over" | "2.000 to 3.000") must stay
                # one condition, not two competing keys.
                if parts and name not in conditions:
                    conditions[name] = " ".join(dict.fromkeys(parts))
            if direction_map:
                for col in measure_cols.values():
                    if col in direction_map:
                        conditions.setdefault("方向", direction_map[col])
                        break
            properties: dict[str, Any] = {}
            for measure, col in sorted(measure_cols.items()):
                cell = row[col] if col < len(row) else ""
                parsed = _parse_value(cell, strip_marks)
                if parsed is None:
                    continue
                raw_value = str(parsed.get("raw") or "").strip()
                if raw_value in SKIP_CELL_VALUES or _prose_cell(raw_value, parsed):
                    continue
                if (
                    profile == "chemical_composition"
                    and parsed.get("value") is not None
                    and float(parsed["value"]) < 0
                ):
                    # Composition tolerances are not composition values.
                    continue
                parsed["unit"] = (
                    column_units.get(col)
                    or _extract_unit(headers[col], explicit_unit)
                    or binding_units.get(measure, "")
                )
                parsed["column"] = headers[col]
                # Trust the symbol printed in the header (KV2 vs KU2, HBW vs HB).
                measure_key = _detect_measure(headers[col], measure)
                parsed["unit"] = _unit_for_measure(
                    measure_key, headers[col], parsed.get("unit") or ""
                )
                if not _plausible_measure(
                    measure_key, parsed.get("value"), parsed.get("unit") or ""
                ):
                    diagnostics.append(
                        {
                            "code": "VALUE_OUT_OF_RANGE",
                            "message": (
                                f"{measure_key} value {parsed.get('value')} "
                                "outside plausible range"
                            ),
                            "severity": "warning",
                            "detail": {
                                "table_id": table_id,
                                "row_index": row_index,
                                "measure": measure_key,
                                "raw": raw_value,
                            },
                        }
                    )
                    continue
                properties[measure_key] = parsed

            if not properties:
                diagnostics.append(
                    {
                        "code": "EMPTY_RECORD_SKIPPED",
                        "message": "row produced no bound measures",
                        "severity": "info",
                        "detail": {"table_id": table_id, "row_index": row_index},
                    }
                )
                continue

            condition_key = _condition_key(conditions)
            if len(grades) > 1:
                diagnostics.append(
                    {
                        "code": "GRADE_SPLIT",
                        "message": f"merged grade split into {len(grades)} records",
                        "severity": "info",
                        "detail": {
                            "table_id": table_id,
                            "row_index": row_index,
                            "raw": raw_grade,
                        },
                    }
                )
            for grade_index, split_grade in enumerate(grades):
                record_count += 1
                record_id = f"{table_id}-R{row_index + 1}"
                if len(grades) > 1:
                    record_id = f"{record_id}-G{grade_index + 1}"
                record = {
                    "record_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "profile": profile,
                    "grade": split_grade,
                    "grade_raw": raw_grade if len(grades) > 1 else None,
                    "conditions": conditions,
                    "condition_key": condition_key,
                    "properties": properties,
                    "evidence_refs": [record_id],
                    "source": {
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                    },
                }
                records.append(record)
                evidence.append(
                    {
                        "evidence_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "raw_row": list(row),
                        "cells": {
                            headers[idx]: row[idx]
                            for idx in range(min(len(headers), len(row)))
                            if row[idx]
                        },
                    }
                )

            for extra_index, (label, columns) in enumerate(extra_groups.items(), start=1):
                extra_properties: dict[str, Any] = {}
                for measure, col, _ in columns:
                    cell = row[col] if col < len(row) else ""
                    parsed = _parse_value(cell, strip_marks)
                    if parsed is None:
                        continue
                    raw_value = str(parsed.get("raw") or "").strip()
                    if raw_value in SKIP_CELL_VALUES:
                        continue
                    if _prose_cell(raw_value, parsed):
                        continue
                    if (
                        profile == "chemical_composition"
                        and parsed.get("value") is not None
                        and float(parsed["value"]) < 0
                    ):
                        continue
                    parsed["unit"] = (
                        column_units.get(col)
                        or _extract_unit(headers[col], explicit_unit)
                        or binding_units.get(measure, "")
                    )
                    parsed["column"] = headers[col]
                    measure_key = _detect_measure(headers[col], measure)
                    parsed["unit"] = _unit_for_measure(
                        measure_key, headers[col], parsed.get("unit") or ""
                    )
                    if not _plausible_measure(
                        measure_key, parsed.get("value"), parsed.get("unit") or ""
                    ):
                        diagnostics.append(
                            {
                                "code": "VALUE_OUT_OF_RANGE",
                                "message": (
                                    f"{measure_key} value {parsed.get('value')} "
                                    "outside plausible range"
                                ),
                                "severity": "warning",
                                "detail": {
                                    "table_id": table_id,
                                    "row_index": row_index,
                                    "measure": measure_key,
                                    "raw": raw_value,
                                },
                            }
                        )
                        continue
                    extra_properties[measure_key] = parsed
                if not extra_properties:
                    continue
                extra_conditions = dict(conditions)
                directions = {direction for _, _, direction in columns if direction}
                if directions:
                    extra_conditions["方向"] = "、".join(sorted(directions))
                display_label = label.split("|", 1)[0]
                # Room-temperature duplicates belong to the primary record; no
                # extra condition keeps both values under the same field key.
                room_only = ("室温" in display_label or "常温" in display_label) and not re.search(
                    r"\d", re.sub(r"室温|常温", "", display_label)
                )
                if "|" not in label and not room_only:
                    if "冲击吸收能量" in display_label:
                        # “3个试样平均 / 单个试样” is carried by the measure
                        # column itself; it is not a test condition.
                        pass
                    elif "℃" in display_label or "温度" in display_label:
                        extra_conditions["温度"] = display_label
                    elif "mm" in display_label or "厚" in display_label or "尺寸" in display_label:
                        extra_conditions["规格"] = display_label
                    else:
                        extra_conditions["状态"] = display_label
                extra_id = f"{table_id}-R{row_index + 1}-X{extra_index}"
                records.append(
                    {
                        "record_id": extra_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "recipe_id": recipe_id,
                        "recipe_version": recipe_version,
                        "profile": profile,
                        "grade": grades[0],
                        "grade_raw": raw_grade if len(grades) > 1 else None,
                        "conditions": extra_conditions,
                        "condition_key": _condition_key(extra_conditions),
                        "properties": extra_properties,
                        "evidence_refs": [extra_id],
                        "source": {
                            "table_id": table_id,
                            "block_id": block_id,
                            "page_no": page_no,
                            "row_index": row_index,
                        },
                    }
                )
                evidence.append(
                    {
                        "evidence_id": extra_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "raw_row": list(row),
                        "cells": {
                            headers[col]: row[col]
                            for _, col, _ in columns
                            if col < len(row) and row[col]
                        },
                    }
                )

        if merged_grade_fills or merged_condition_fills:
            diagnostics.append(
                {
                    "code": "MERGED_GRADE_FILLED",
                    "message": (
                        f"table {table_id} filled {merged_grade_fills} merged grade "
                        f"cells and {merged_condition_fills} condition cells"
                    ),
                    "severity": "info",
                    "detail": {
                        "table_id": table_id,
                        "filled": merged_grade_fills,
                        "condition_filled": merged_condition_fills,
                    },
                }
            )

    if not records and profile == "chemical_composition":
        # Composition tables often have no grade column (single specification).
        return _parse_chemical_columns(
            table,
            table_id=table_id,
            page_no=page_no,
            profile=profile,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            strip_marks=strip_marks,
            units=units,
            binding_units=binding_units,
            diagnostics=diagnostics,
        )

    if not records:
        # Column bindings did not match this table: fall back to the matrix
        # strategy chain (property / grade-property / property rows / hardness).
        strategy_chain = (manifest or {}).get("strategy_chain") or rules.get(
            "strategy_chain"
        )
        try:  # imported as a package (tests)
            from .strategies import run_strategy_chain
        except ImportError:  # flat runtime image (/engine)
            from strategies import run_strategy_chain

        result = run_strategy_chain(
            table,
            {
                "recipe_id": recipe_id,
                "recipe_version": recipe_version,
                "profile": profile,
                "measures": list((bindings.get("measures") or {}).keys()),
            },
            diagnostics,
            strategy_chain,
        )
        if result is not None:
            records, evidence = result

    # 无主表：没有牌号列、也没有条件列的独立冲击小表（如单独的 KV2 表），
    # 牌号隐含在上一张主表里，不能产出 grade="~" 的无主记录。
    # 文档级牌号兜底应先于无主表丢弃：AMS/ASTM 的牌号只在标题里。
    _apply_document_grade(records, diagnostics, table_id)
    records.extend(_derive_heat_records(records, diagnostics, table_id))
    records, evidence = _drop_orphan_records(
        records, evidence, diagnostics, table_id
    )

    if not records:
        diagnostics.append(
            {
                "code": "NO_RECORDS",
                "message": f"table {table_id} produced no records",
                "severity": "warning",
                "detail": {"table_id": table_id},
            }
        )

    summary = {
        "table_id": table_id,
        "page_no": page_no,
        "profile": profile,
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "rows": row_total,
        "records": len(records),
    }
    return records, evidence, summary
