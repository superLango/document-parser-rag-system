"""Project a metal-doc-agent run into hansonDoc_RAG's extraction-result schema.

hansonDoc_RAG returns a schema-template-shaped payload:

    {
      "schema_template_id": "...",
      "schema_name": "...",
      "categories": [
        {"feature": "...", "records": [ {field: value, ...} ], "rejected": [],
         "missing_fields": [...], "hit_score": ..., "hit_count": ...}
      ],
      "summary": {...},
      "timing": {"total_sec": ...}
    }

The template used here is ``产品标准抽取模板`` (6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7):
标准信息 (object), 热处理制度 (array), and a term-base expanded 检测项目 category
whose features are 化学成分 / 室温拉伸 / 高温拉伸 / 高温光滑持久 / 布氏硬度 ...

Usage:
    python -m tools.export_hanson_schema --run runs/gbt2965_2007_rag \
        --out ../docs/gbt2965-2007-hansonDoc-schema.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

TEMPLATE_ID = "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7"
TEMPLATE_NAME = "产品标准抽取模板"

STANDARD_FIELDS = ["标准名称", "标准编号"]
HEAT_FIELDS = [
    "材料牌号",
    "工艺名称",
    "保温温度",
    "保温时间",
    "冷却介质",
    "工序名称",
    "介质温度",
    "装炉温度",
    "升温速率",
    "降温速率",
    "出炉温度",
    "项目大类",
]
ITEM_FIELDS = [
    "项目名称",
    "位置",
    "单位",
    "标准要求",
    "方向",
    "尺寸厚度",
    "试样状态",
    "取样数量",
    "取样说明",
    "锻件类型",
    "试验温度",
    "材料牌号",
    "试验方法",
]

PROPERTY_NAMES = {
    "Rm": "抗拉强度",
    "Rp0.2": "规定非比例延伸强度",
    "ReH": "屈服强度",
    "A": "断后伸长率",
    "A50mm": "断后伸长率(A50mm)",
    "Z": "断面收缩率",
    "KV2": "冲击吸收能量",
    "HB": "布氏硬度",
    "HRC": "洛氏硬度",
    "HV": "维氏硬度",
    "E": "弹性模量",
    "KIC": "断裂韧度",
    "σ100h": "持久强度σ100h",
    "σ50h": "持久强度σ50h",
    "σ35h": "持久强度σ35h",
}

ROOM_PROPERTIES = {"Rm", "Rp0.2", "ReH", "A", "A50mm", "Z", "E", "KIC"}
IMPACT_PROPERTIES = {"KV2"}
HARDNESS_FEATURES = {"HB": "布氏硬度", "HRC": "洛氏硬度", "HV": "维氏硬度"}
PERSISTENCE_PROPERTIES = {"σ100h", "σ50h", "σ35h"}
TEMPERATURE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*℃(?:\s*(?:~|-)\s*\d+(?:\.\d+)?\s*℃)?"
    r"(?:\s*±\s*\d+(?:\.\d+)?\s*℃)?"
)
HEAT_TIME_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:h|min)(?:\s*[~-]\s*\d+(?:\.\d+)?\s*(?:h|min))?")
COOLING_RE = re.compile(r"(空冷|水冷|炉冷|油冷)")


def _shown(prop: dict[str, Any]) -> str:
    text = str(prop.get("raw") or "")
    comparator = prop.get("comparator")
    if comparator == "min" and not text.startswith(("≥", ">", "<")):
        return "≥" + text
    if comparator == "max" and not text.startswith(("≤", "<", ">")):
        return "≤" + text
    if comparator == "na":
        return "-"
    return text


def _field_text(fields: dict[str, Any], name: str) -> str:
    value = fields.get(name) or {}
    if isinstance(value, dict):
        return str(value.get("raw") or value.get("text") or "")
    return str(value or "")


def _clause_data(result: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (clause texts joined, method standard per clause id)."""
    texts: list[str] = []
    methods: dict[str, str] = {}
    for clause in result.get("clauses") or []:
        clause_id = str(clause.get("clause_id") or "")
        fields = clause.get("fields") or {}
        for value in fields.values():
            if not isinstance(value, dict):
                continue
            text = str(value.get("raw") or value.get("text") or "")
            if text:
                texts.append(text)
        method = _field_text(fields, "method_standard")
        if method:
            methods[clause_id] = method
    return {"text": " ".join(texts)}, methods


def _document_hints(result: dict[str, Any]) -> dict[str, str]:
    clause_text = _clause_data(result)[0]["text"]
    table_text = " ".join(
        f"{table.get('caption') or ''} {table.get('context') or ''}"
        for table in result.get("tables") or []
    )
    text = f"{clause_text} {table_text}"
    direction = ""
    if "纵向" in text:
        direction = "纵向"
    elif "横向" in text:
        direction = "横向"
    state = "热处理后" if "热处理后的试样" in text else ""
    size = ""
    match = re.search(
        r"横截面积不大于\s*(\d+(?:\.\d+)?)\s*[~]?\s*(cm2|cm²)\s*"
        r".{0,40}?厚度不大于\s*(\d+(?:\.\d+)?)\s*[~]?\s*(m\s*m|mm)",
        text,
    )
    if match:
        size = f"横截面积≤{match.group(1)}cm²且截面厚度≤{match.group(3)}mm"
    return {"direction": direction, "state": state, "size": size}


def _inspection_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Parse the 检验项目 table into item -> sampling/method-clause info."""
    info: dict[str, dict[str, Any]] = {}
    for table in result.get("tables") or []:
        headers = [" ".join(path) for path in table.get("header_paths") or []]
        if not any("检验项目" in header for header in headers):
            continue
        item_col = next((i for i, h in enumerate(headers) if "检验项目" in h), None)
        sampling_col = next((i for i, h in enumerate(headers) if "取样" in h), None)
        method_col = next(
            (i for i, h in enumerate(headers) if "试验方法" in h or "检验方法" in h),
            None,
        )
        if item_col is None:
            continue
        notes: list[str] = []
        for row in (table.get("rows") or [])[int(table.get("header_rows") or 0) :]:
            cells = [str(cell) for cell in row if cell]
            if not cells:
                continue
            if len(set(cells)) == 1:
                notes.append(cells[0])
                continue
            item = _clean_item_name(str(row[item_col]))
            if not item:
                continue
            sampling = str(row[sampling_col]).strip() if sampling_col is not None and sampling_col < len(row) else ""
            method_text = str(row[method_col]).strip() if method_col is not None and method_col < len(row) else ""
            clauses = re.findall(r"\d+(?:\.\d+)+", method_text)
            info[item] = {
                "sampling": sampling,
                "method_clauses": clauses,
                "quantity": _quantity(sampling),
            }
        if notes:
            cleaned = re.sub(r"(^|[。；])[a-z](?=[\u4e00-\u9fff])", r"\1", "；".join(notes))
            info.setdefault("_notes", {})["text"] = cleaned
    return info


def _clean_item_name(text: str) -> str:
    text = re.sub(r"\^?\{?[a-z]\}?$", "", text.strip())
    return text.strip()


def _quantity(text: str) -> int | None:
    match = re.search(r"每批(?:取)?\s*(\d+)\s*(?:根|份|个)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"每炉\s*(\d+)\s*份", text)
    if match:
        return int(match.group(1))
    return None


def _records_for(result: dict[str, Any], profile: str) -> list[dict]:
    table_ids = {
        table["table_id"]
        for table in result.get("tables") or []
        if table.get("profile") == profile
    }
    return [r for r in result.get("records") or [] if r.get("source_table_id") in table_ids]


def _detect_feature(prop: str, condition: str | None) -> str:
    text = condition or ""
    hot = "℃" in text or "°C" in text or "高温" in text
    if prop in PERSISTENCE_PROPERTIES:
        return "高温光滑持久" if hot else "室温持久"
    if prop in IMPACT_PROPERTIES:
        return "夏比冲击"
    if prop in HARDNESS_FEATURES:
        return HARDNESS_FEATURES[prop]
    return "高温拉伸" if hot else "室温拉伸"


def _temperature(condition: str | None) -> str:
    text = (condition or "").replace("°C", "℃")
    match = TEMPERATURE_RE.search(text)
    return match.group(0).replace(" ", "") if match else ""


def _item_records(result: dict[str, Any]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    tables = {table["table_id"]: table for table in result.get("tables") or []}
    hints = _document_hints(result)
    inspection = _inspection_map(result)
    _, methods = _clause_data(result)

    mech_info = inspection.get("力学性能") or {}
    chem_info = inspection.get("化学成分") or {}
    mech_methods = [methods.get(cid, "") for cid in mech_info.get("method_clauses") or []]
    mech_methods = [m for m in mech_methods if m]
    chem_method = methods.get((chem_info.get("method_clauses") or [""])[0], "")

    def is_appendix(table_id: str) -> bool:
        caption = (tables.get(table_id) or {}).get("caption") or ""
        return bool(re.match(r"^表\s*[A-Za-z]", caption))

    def common(table_id: str, feature: str) -> dict[str, Any]:
        appendix = is_appendix(table_id)
        method = ""
        if feature == "化学成分":
            method = chem_method
        elif feature in {"室温拉伸"}:
            method = mech_methods[0] if len(mech_methods) > 0 else ""
        elif feature in {"高温拉伸"}:
            method = mech_methods[1] if len(mech_methods) > 1 else ""
        elif feature in {"高温光滑持久", "室温持久"}:
            method = mech_methods[2] if len(mech_methods) > 2 else ""
        sampling_info = chem_info if feature == "化学成分" else mech_info
        sampling_note = sampling_info.get("sampling") or ""
        notes = (inspection.get("_notes") or {}).get("text") or ""
        if feature == "化学成分" and notes:
            sampling_note = f"{sampling_note}；{notes}" if sampling_note else notes
        return {
            "位置": "棒材",
            "方向": "" if appendix else hints["direction"],
            "尺寸厚度": "" if appendix else hints["size"],
            "试样状态": "" if appendix else hints["state"],
            "取样数量": sampling_info.get("quantity"),
            "取样说明": sampling_note,
            "锻件类型": "棒材",
            "试验方法": method,
        }

    for record in _records_for(result, "chemical_composition"):
        table_id = record.get("source_table_id") or ""
        condition = record.get("condition")
        for prop, value in (record.get("properties") or {}).items():
            if value.get("comparator") == "na":
                continue
            item = {
                "项目名称": PROPERTY_NAMES.get(prop, prop),
                "材料牌号": record.get("grade") or record.get("grade_level") or "",
                "标准要求": _shown(value),
                "单位": value.get("unit") or "%",
                "试验温度": "",
            }
            item.update(common(table_id, "化学成分"))
            groups.setdefault("化学成分", []).append(item)

    for record in _records_for(result, "mechanical_properties"):
        table_id = record.get("source_table_id") or ""
        condition = record.get("condition")
        appendix = is_appendix(table_id)
        for prop, value in (record.get("properties") or {}).items():
            if value.get("comparator") == "na":
                continue
            feature = _detect_feature(prop, condition)
            temperature = _temperature(condition)
            if feature in {"室温拉伸", "室温持久"} and not temperature:
                temperature = "室温" if feature == "室温拉伸" else ""
            normalized = (condition or "").replace("°C", "℃")
            if condition and "℃" not in normalized and "室温" not in normalized:
                state = condition.replace("性能", "")
            else:
                state = ""
            item = {
                "项目名称": PROPERTY_NAMES.get(prop, prop),
                "材料牌号": record.get("grade") or record.get("grade_level") or "",
                "标准要求": _shown(value),
                "单位": value.get("unit") or "",
                "试验温度": temperature or "",
                "试样状态": state,
            }
            item.update(common(table_id, feature))
            if state:
                item["试样状态"] = state
            elif appendix:
                item["试样状态"] = ""
            groups.setdefault(feature, []).append(item)
    return groups


def _heat_records(result: dict[str, Any]) -> list[dict]:
    records: list[dict] = []
    for table in result.get("tables") or []:
        header_rows = int(table.get("header_rows") or 0)
        rows = (table.get("rows") or [])[header_rows:]
        for row in rows:
            cells = [str(cell) for cell in row if cell]
            if not cells or len(set(cells)) == 1:
                continue
            if len(row) < 2:
                continue
            grade = row[0]
            text = str(row[1]).replace("°C", "℃")
            if not grade or not text:
                continue
            if not TEMPERATURE_RE.search(text):
                continue
            for segment in re.split(r"[。；]", text):
                segment = segment.strip()
                if not segment:
                    continue
                process = ""
                match = re.match(r"^(.{1,12}?)[：:]", segment)
                if match:
                    process = match.group(1).strip()
                    segment = segment[match.end() :]
                elif "退火" in segment:
                    process = "退火"
                temperature = TEMPERATURE_RE.search(segment)
                duration = HEAT_TIME_RE.search(segment)
                cooling = COOLING_RE.findall(segment)
                cooling_text = "/".join(dict.fromkeys(cooling))
                records.append(
                    {
                        "材料牌号": grade,
                        "工艺名称": process,
                        "保温温度": temperature.group(0).replace("°C", "℃") if temperature else "",
                        "保温时间": duration.group(0) if duration else "",
                        "冷却介质": cooling_text,
                        "工序名称": process,
                        "介质温度": "",
                        "装炉温度": "",
                        "升温速率": "",
                        "降温速率": "",
                        "出炉温度": "",
                        "项目大类": "热处理制度",
                    }
                )
    return records


def _missing_fields(fields: list[str], records: list[dict]) -> list[str]:
    missing = []
    for name in fields:
        if not any(record.get(name) not in (None, "", []) for record in records):
            missing.append(name)
    return missing


def _category(feature: str, records: list[dict], fields: list[str]) -> dict:
    return {
        "feature": feature,
        "records": records,
        "rejected": [],
        "missing_fields": _missing_fields(fields, records),
        "hit_score": None,
        "hit_count": len(records),
    }


def build_payload(
    result: dict[str, Any],
    timing_seconds: float,
    template_id: str = TEMPLATE_ID,
    template_name: str = TEMPLATE_NAME,
    job_dir: str | Path | None = None,
    dictionary_path: str | Path | None = None,
) -> dict:
    if job_dir is not None:
        try:
            from metal_doc_agent.schema_projection import (
                load_dictionary_index_path,
                load_template,
                project_hanson_schema,
            )

            template_path = (
                Path(__file__).resolve().parents[1]
                / "configs"
                / "schema_templates"
                / "product_standard.json"
            )
            payload = project_hanson_schema(
                job_dir,
                load_template(template_path),
                index=load_dictionary_index_path(dictionary_path),
                timing_seconds=timing_seconds,
                records=result.get("records"),
            )
            for category in payload.get("categories") or []:
                category.pop("fields", None)
            payload["schema_template_id"] = template_id
            payload["schema_name"] = template_name
            return payload
        except FileNotFoundError:
            pass

    document = result.get("document") or {}
    standard = [
        {
            "标准名称": document.get("title") or "",
            "标准编号": document.get("standard_no") or "",
        }
    ]
    heat = _heat_records(result)
    items = _item_records(result)

    categories = [
        _category("标准信息", standard, STANDARD_FIELDS),
        _category("热处理制度", heat, HEAT_FIELDS),
    ]
    order = [
        "化学成分",
        "室温拉伸",
        "高温拉伸",
        "高温光滑持久",
        "室温持久",
        "夏比冲击",
        "布氏硬度",
        "洛氏硬度",
        "维氏硬度",
    ]
    feature_order = order + sorted(set(items) - set(order))
    categories.extend(
        _category(feature, items[feature], ITEM_FIELDS)
        for feature in feature_order
        if items.get(feature)
    )

    total = sum(len(category["records"]) for category in categories)
    summary = {
        "total_records": total,
        "kept_categories": len(categories),
        "categories_attempted": len(categories),
        "skipped": [],
        "recall": {
            "mode": "loose",
            "participated": len(categories),
            "kept": len(categories),
            "skipped_count": 0,
            "score_bands": {
                "0-0.3": 0,
                "0.3-0.5": 0,
                "0.5-0.7": 0,
                "0.7-0.9": 0,
                "0.9-1.0": 0,
            },
        },
    }
    return {
        "schema_template_id": template_id,
        "schema_name": template_name,
        "categories": categories,
        "summary": summary,
        "timing": {"total_sec": round(float(timing_seconds), 2)},
    }


def _category_fields(feature: str) -> list[str]:
    if feature == "标准信息":
        return STANDARD_FIELDS
    if feature == "热处理制度":
        return HEAT_FIELDS
    return ITEM_FIELDS


def _is_filled(value: Any) -> bool:
    return value not in (None, "", "未规定", "未注明")


def build_field_audit(payload: dict) -> str:
    lines = [
        "# 字段抽取完整性审计",
        "",
        f"> 模板：{payload.get('schema_name')}（`{payload.get('schema_template_id')}`）  ",
        f"> 类别 {len(payload.get('categories') or [])} 个，记录 {payload.get('summary', {}).get('total_records')} 条。",
        "",
        "## 1. 类别概览",
        "",
        "| category | 记录数 | 字段数 | 字段单元 | 已填 | 空 | 填充率 |",
        "|---|---|---|---|---|---|---|",
    ]
    total_cells = total_filled = total_empty = 0
    detail_rows: list[list[str]] = []
    for category in payload.get("categories") or []:
        fields = _category_fields(category["feature"])
        records = category.get("records") or []
        cells = len(fields) * len(records)
        filled = empty = 0
        for name in fields:
            field_filled = sum(1 for record in records if _is_filled(record.get(name)))
            field_empty = sum(1 for record in records if record.get(name) in (None, ""))
            filled += field_filled
            empty += field_empty
            sample = next(
                (
                    record.get(name)
                    for record in records
                    if record.get(name) not in (None, "")
                ),
                "",
            )
            detail_rows.append(
                [
                    category["feature"],
                    name,
                    str(field_filled),
                    str(field_empty),
                    str(sample)[:60],
                ]
            )
        rate = f"{filled / cells:.1%}" if cells else "—"
        lines.append(
            f"| {category['feature']} | {len(records)} | {len(fields)} | {cells} | "
            f"{filled} | {empty} | {rate} |"
        )
        total_cells += cells
        total_filled += filled
        total_empty += empty
    rate = f"{total_filled / total_cells:.1%}" if total_cells else "—"
    lines.append(
        f"| **合计** | **{payload.get('summary', {}).get('total_records')}** | — | **{total_cells}** | "
        f"**{total_filled}** | **{total_empty}** | **{rate}** |"
    )
    lines.extend(
        [
            "",
            "> `已填` = 有原文值或可溯源派生值；`空` = 原文未给出或当前无法推导（空字符串/null）。",
            "",
            "## 2. 字段明细",
            "",
            "| category | 字段 | 已填 | 空 | 示例 |",
            "|---|---|---|---|---|",
        ]
    )
    for row in detail_rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def _total_ms(trace: dict[str, Any]) -> float:
    return sum(float(step.get("ms") or 0.0) for step in trace.get("steps") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="run directory with result.json")
    parser.add_argument("--out", required=True, help="output JSON path")
    parser.add_argument("--audit-out", default=None, help="optional field-audit markdown path")
    parser.add_argument("--template-id", default=TEMPLATE_ID)
    parser.add_argument("--template-name", default=TEMPLATE_NAME)
    args = parser.parse_args()

    run_dir = Path(args.run)
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    trace_path = run_dir / "trace.json"
    total_ms = _total_ms(json.loads(trace_path.read_text(encoding="utf-8"))) if trace_path.exists() else 0.0

    payload = build_payload(
        result,
        total_ms / 1000.0,
        template_id=args.template_id,
        template_name=args.template_name,
        job_dir=run_dir,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.audit_out:
        audit = Path(args.audit_out)
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit.write_text(build_field_audit(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                "categories": len(payload["categories"]),
                "records": payload["summary"]["total_records"],
                "features": [c["feature"] for c in payload["categories"]],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
