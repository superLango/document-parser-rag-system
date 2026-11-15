#!/usr/bin/env python3
"""Audit parsed standards against their source PDFs.

For each parsed record the script re-reads the original PDF text/tables and
checks whether the grade and every property value can be found near the
record's page. It reports grounded rates and sampled issues for manual review.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx
import pymupdf

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNS = REPO_ROOT / "new_app" / "docs" / "reports" / "closeout-standards-e2e.json"
DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "closeout-standards-audit.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "closeout-standards-audit.md"
API = "http://localhost:18000"
RANGE_MARKS = ("~", "～", "≤", "≥", "<", ">", "-")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def norm(value: Any) -> str:
    # 部分标准 PDF 文本层使用全角数字/字母（如 ０．２４、Ｑ３５５），
    # 先做 NFKC 归一化，避免把可核对的值误判为“未命中”。
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = (
        text.replace("（", "(")
        .replace("）", ")")
        .replace("≤", "<=")
        .replace("≥", ">=")
        .replace("～", "~")
        .replace("－", "-")
    )
    return re.sub(r"\s+", "", text)


def page_index(
    pdf_path: Path,
) -> tuple[list[str], dict[int, list[str]], list[str], dict[int, int], dict[int, float]]:
    """Return page texts, table cells, raw texts, data-row counts and quality."""
    document = pymupdf.open(pdf_path)
    texts: list[str] = []
    raw_texts: list[str] = []
    cells: dict[int, list[str]] = defaultdict(list)
    data_rows: dict[int, int] = defaultdict(int)
    page_quality: dict[int, float] = defaultdict(float)
    try:
        for index, page in enumerate(document, start=1):
            raw = page.get_text("text")
            raw_texts.append(raw)
            texts.append(norm(raw))
            compact = re.sub(r"\s+", "", raw)
            readable = len(re.findall(r"[\u4e00-\u9fffA-Za-z]", raw))
            page_quality[index] = readable / max(1, len(compact))
            try:
                tables = page.find_tables()
            except Exception:
                tables = None
            if tables is not None:
                for table in tables.tables:
                    try:
                        rows = table.extract()
                    except Exception:
                        continue
                    for row in rows:
                        values = [cell for cell in row if cell]
                        for cell in values:
                            cells[index].append(norm(cell))
                        numeric = sum(
                            1
                            for cell in values
                            if re.fullmatch(r"[\d.,~～<>≤≥\- ]+", str(cell).strip())
                        )
                        if len(values) >= 2 and numeric >= 2:
                            data_rows[index] += 1
    finally:
        document.close()
    return texts, cells, raw_texts, data_rows, page_quality



def context_snippet(raw_text: str, needle: str) -> str:
    normalized = norm(raw_text)
    token = norm(needle)
    if not token:
        return ""
    position = normalized.find(token)
    if position < 0:
        numbers = NUMBER_RE.findall(token)
        for number in numbers:
            position = normalized.find(number)
            if position >= 0:
                break
    if position < 0:
        return raw_text[:160].replace("\n", " ")
    return normalized[max(0, position - 80) : position + 140]


def classify_issue(record: dict[str, Any], prop: dict[str, Any], grade_ok: bool) -> str:
    if not grade_ok:
        return "grade_not_found"
    raw = str(prop.get("raw") or "")
    if not raw:
        return "empty_raw"
    if any(mark in raw for mark in RANGE_MARKS):
        return "range_or_limit_format"
    if prop.get("value") is None and raw:
        return "non_numeric_value"
    if not prop.get("unit"):
        return "missing_unit"
    return "ocr_or_normalization"


# 金属材料常见性能值的合理区间，超出即视为疑似错列/错行/单位错误。
PLAUSIBLE = {
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


def audit_document(
    client: httpx.Client,
    item: dict[str, Any],
    records_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    path = Path(item.get("path") or "")
    result: dict[str, Any] = {
        "name": item["name"],
        "category": item.get("category"),
        "status": item.get("status"),
        "path": str(path),
        "pages": 0,
        "source_cells": 0,
        "source_data_rows": 0,
        "table_pages": 0,
        "records": 0,
        "fields": 0,
        "groundable_fields": 0,
        "unverifiable_fields": 0,
        "text_layer": True,
        "grade_grounded": 0,
        "grade_checked": 0,
        "value_grounded": 0,
        "unit_present": 0,
        "implausible_values": 0,
        "duplicate_keys": 0,
        "multi_condition_keys": 0,
        "empty_records": 0,
        "issue_counts": {},
        "issues": [],
    }
    if not path.exists():
        result["error"] = "pdf not found"
        return result
    texts, cells, raw_texts, data_rows, page_quality = page_index(path)
    result["pages"] = len(texts)
    result["source_cells"] = sum(len(value) for value in cells.values())
    result["source_data_rows"] = sum(data_rows.values())
    result["table_pages"] = len(data_rows)
    # 扫描件没有文本层时无法用文本回查，这类文档只统计“不可核对”，
    # 不能算作抽取错误；字体编码损坏的 PDF 文本层会全是乱码，同样不可用。
    combined = "".join(raw_texts)
    compact = re.sub(r"\s+", "", combined)
    readable = len(re.findall(r"[\u4e00-\u9fffA-Za-z]", combined))
    readable_ratio = readable / max(1, len(compact))
    result["text_quality"] = round(readable_ratio, 3)
    result["text_layer"] = (
        sum(len(text) for text in raw_texts) / max(1, len(raw_texts)) >= 100
        and readable_ratio >= 0.35
    )

    if records_override is None and item.get("status") != "STRUCTURED_READY":
        result["error"] = item.get("error_code") or item.get("status")
        return result

    response = None
    if records_override is not None:
        records = records_override
    else:
        response = client.get(f"{API}/v1/runs/{item['run_id']}/records")
        if response.status_code != 200:
            result["error"] = f"records HTTP {response.status_code}"
            return result
        records = response.json().get("records") or []
    result["records"] = len(records)
    if not result["text_layer"]:
        # 扫描件（无文本层）跳过回查，只记录可度量的字段/单位。
        result["fields"] = sum(len(record.get("properties") or {}) for record in records)
        result["unit_present"] = sum(
            1
            for record in records
            for prop in (record.get("properties") or {}).values()
            if isinstance(prop, dict) and prop.get("unit")
        )
        result["empty_records"] = sum(
            1 for record in records if not record.get("properties")
        )
        result["unverifiable_fields"] = result["fields"]
        return result

    key_counts: Counter[tuple[str, str, str]] = Counter()
    condition_keys: dict[tuple[str, str], set[str]] = defaultdict(set)
    issue_counts: Counter[str] = Counter()
    for record in records:
        page_no = int(record.get("page_no") or 1)
        nearby = ""
        nearby_cells: list[str] = []
        for offset in (0, -1, 1):
            index = page_no + offset
            if 1 <= index <= len(texts):
                nearby += texts[index - 1]
                nearby_cells.extend(cells.get(index, []))
        # 只按记录自身页面判断文本层可用性：部分 PDF 的表页是乱码字体编码，
        # 相邻正文页正常并不代表本页可核对，否则会把“无法核对”算成抽取错误。
        page_ok = page_quality.get(page_no, 0.0) >= 0.2
        grade = str(record.get("grade") or "")
        grade_ok = grade in ("", "~") or norm(grade) in nearby
        if grade not in ("", "~") and page_ok:
            result["grade_checked"] += 1
            result["grade_grounded"] += int(grade_ok)
        properties = record.get("properties") or {}
        if not properties:
            result["empty_records"] += 1
        condition_key = str(record.get("condition_key") or "")
        for measure, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            result["fields"] += 1
            key_counts[(grade, str(measure), condition_key)] += 1
            condition_keys[(grade, str(measure))].add(condition_key)
            if not page_ok:
                result["unverifiable_fields"] += 1
                if prop.get("unit"):
                    result["unit_present"] += 1
                continue
            result["groundable_fields"] += 1
            raw = str(prop.get("raw") or "")
            raw_norm = norm(raw)
            value = prop.get("value")
            number_tokens = set(NUMBER_RE.findall(nearby))
            for cell in nearby_cells:
                number_tokens.update(NUMBER_RE.findall(cell))
            grounded = bool(raw_norm) and (
                raw_norm in nearby or any(raw_norm in cell for cell in nearby_cells)
            )
            if not grounded and value is not None:
                grounded = str(value) in number_tokens or f"{float(value):g}" in number_tokens
            if grounded:
                result["value_grounded"] += 1
            else:
                reason = classify_issue(record, prop, grade_ok)
                issue_counts[reason] += 1
                if len(result["issues"]) < 40:
                    result["issues"].append(
                        {
                            "record_id": record.get("record_id"),
                            "page_no": page_no,
                            "grade": grade,
                            "measure": str(measure),
                            "raw": raw,
                            "value": value,
                            "unit": prop.get("unit"),
                            "condition_key": record.get("condition_key"),
                            "reason": reason,
                            "context": context_snippet(
                                raw_texts[page_no - 1]
                                if 1 <= page_no <= len(raw_texts)
                                else "",
                                raw,
                            ),
                        }
                    )
            if prop.get("unit"):
                result["unit_present"] += 1
            bounds = PLAUSIBLE.get(str(measure))
            if bounds and isinstance(value, (int, float)):
                comparable = float(value)
                unit = str(prop.get("unit") or "").strip().lower()
                if unit in {"ksi", "ks"}:
                    comparable *= 6.894757
                elif unit == "gpa":
                    comparable *= 1000.0
                if not (bounds[0] <= comparable <= bounds[1]):
                    result["implausible_values"] += 1
                    issue_counts["value_out_of_range"] += 1
                    if len(result["issues"]) < 40:
                        result["issues"].append(
                            {
                                "record_id": record.get("record_id"),
                                "page_no": page_no,
                                "grade": grade,
                                "measure": str(measure),
                                "raw": raw,
                                "value": value,
                                "unit": prop.get("unit"),
                                "condition_key": record.get("condition_key"),
                                "reason": "value_out_of_range",
                                "context": context_snippet(
                                    raw_texts[page_no - 1]
                                    if 1 <= page_no <= len(raw_texts)
                                    else "",
                                    raw,
                                ),
                            }
                        )
    if not records and result["source_data_rows"] >= 3:
        issue_counts["table_not_parsed"] += 1
        result["table_not_parsed"] = True
        first_table_page = min(data_rows, key=lambda page_no: page_no)
        result["issues"].append(
            {
                "record_id": "",
                "page_no": first_table_page,
                "grade": "",
                "measure": "",
                "raw": "",
                "value": None,
                "unit": "",
                "condition_key": "",
                "reason": "table_not_parsed",
                "context": raw_texts[first_table_page - 1][:200].replace("\n", " "),
            }
        )
    result["duplicate_keys"] = sum(1 for count in key_counts.values() if count > 1)
    result["multi_condition_keys"] = sum(
        1 for values in condition_keys.values() if len(values) > 1
    )
    result["issue_counts"] = dict(issue_counts)
    return result


def summarize(docs: list[dict[str, Any]]) -> dict[str, Any]:
    documents = len(docs)
    records = sum(item["records"] for item in docs)
    fields = sum(item["fields"] for item in docs)
    ready_docs = [item for item in docs if item["status"] == "STRUCTURED_READY"]
    by_category: dict[str, dict[str, Any]] = {}
    for item in docs:
        bucket = by_category.setdefault(
            item.get("category") or "未知",
            {"documents": 0, "records": 0, "fields": 0, "zero": 0, "table_not_parsed": 0},
        )
        bucket["documents"] += 1
        bucket["records"] += item["records"]
        bucket["fields"] += item["fields"]
        bucket["zero"] += int(item["records"] == 0)
        bucket["table_not_parsed"] += int(bool(item.get("table_not_parsed")))
    return {
        "documents": documents,
        "structured_ready": len(ready_docs),
        "documents_with_records": sum(1 for item in docs if item["records"] > 0),
        "status_counts": dict(Counter(str(item.get("status") or "") for item in docs)),
        "records": records,
        "fields": fields,
        "source_data_rows": sum(item.get("source_data_rows", 0) for item in docs),
        "zero_record_documents": sum(1 for item in ready_docs if item["records"] == 0),
        "table_not_parsed_documents": sum(
            1 for item in docs if item.get("table_not_parsed")
        ),
        "text_layer_documents": sum(1 for item in docs if item.get("text_layer")),
        "groundable_fields": sum(item.get("groundable_fields", 0) for item in docs),
        "unverifiable_fields": sum(item.get("unverifiable_fields", 0) for item in docs),
        "grade_grounded_rate": round(
            sum(item["grade_grounded"] for item in docs)
            / max(1, sum(item["grade_checked"] for item in docs)),
            4,
        ),
        "value_grounded_rate": round(
            sum(item["value_grounded"] for item in docs)
            / max(1, sum(item.get("groundable_fields", 0) for item in docs)),
            4,
        ),
        "unit_present_rate": round(
            sum(item["unit_present"] for item in docs) / max(1, fields), 4
        ),
        "implausible_values": sum(item.get("implausible_values", 0) for item in docs),
        "empty_record_rate": round(
            sum(item["empty_records"] for item in docs) / max(1, records), 4
        ),
        "duplicate_keys": sum(item["duplicate_keys"] for item in docs),
        "multi_condition_keys": sum(item["multi_condition_keys"] for item in docs),
        "issue_counts": dict(
            Counter(
                reason
                for item in docs
                for reason, count in item["issue_counts"].items()
                for _ in range(count)
            )
        ),
        "by_category": by_category,
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    metrics = payload["summary"]
    lines = [
        "# 标准文件解析结果与原文核对",
        "",
        f"> 生成时间：{payload['generated_at']}",
        f"> 样本：{metrics['documents']} 份标准文件",
        "",
        "## 1. 汇总",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 结构化成功 | {metrics['structured_ready']}/{metrics['documents']} |",
        f"| 记录数 | {metrics['records']} |",
        f"| 字段数 | {metrics['fields']} |",
        f"| 原文数据行 | {metrics.get('source_data_rows', 0)} |",
        f"| 零记录文档 | {metrics.get('zero_record_documents', 0)} |",
        f"| 有表但零记录 | {metrics.get('table_not_parsed_documents', 0)} |",
        f"| 可文本回查文档 | {metrics.get('text_layer_documents', 0)}/{metrics['documents']} |",
        f"| 不可核对字段 | {metrics.get('unverifiable_fields', 0)} |",
        f"| 牌号在原文命中率 | {metrics['grade_grounded_rate']:.2%} |",
        f"| 字段值在原文命中率 | {metrics['value_grounded_rate']:.2%} |",
        f"| 单位存在率 | {metrics['unit_present_rate']:.2%} |",
        f"| 超合理区间值 | {metrics.get('implausible_values', 0)} |",
        f"| 空记录率 | {metrics['empty_record_rate']:.2%} |",
        f"| 重复键记录 | {metrics['duplicate_keys']} |",
        f"| 同键多条件 | {metrics['multi_condition_keys']} |",
        "",
        "## 1.1 分类别",
        "",
        "| 类别 | 文档 | 记录 | 字段 | 零记录 | 有表未解析 |",
        "|---|---|---|---|---|---|",
    ]
    for category, bucket in metrics.get("by_category", {}).items():
        lines.append(
            f"| {category} | {bucket['documents']} | {bucket['records']} | "
            f"{bucket['fields']} | {bucket['zero']} | {bucket['table_not_parsed']} |"
        )
    lines += [
        "",
        "## 2. 文档明细",
        "",
        "| 文档 | 类别 | 状态 | 页 | 数据行 | 记录 | 字段 | 牌号命中 | 值命中 | 重复键 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in payload["documents"]:
        grade_rate = item["grade_grounded"] / max(1, item["grade_checked"])
        value_rate = item["value_grounded"] / max(1, item["fields"])
        lines.append(
            f"| {item['name'][:44]} | {item.get('category') or '-'} | {item['status']} | "
            f"{item['pages']} | {item.get('source_data_rows', 0)} | {item['records']} | "
            f"{item['fields']} | {grade_rate:.0%} | {value_rate:.0%} | "
            f"{item['duplicate_keys']} |"
        )
    lines.extend(["", "## 3. 问题样本", ""])
    for item in payload["documents"]:
        if not item["issues"]:
            continue
        lines.append(f"### {item['name'][:60]}")
        lines.append("")
        lines.append("| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |")
        lines.append("|---|---|---|---|---|---|")
        for issue in item["issues"][:6]:
            context = issue["context"].replace("|", "/")[:100]
            lines.append(
                f"| {issue['page_no']} | {issue['grade'][:18]} | {issue['measure']} | "
                f"{issue['raw'][:28]} | {issue['reason']} | {context} |"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--registry", type=Path)
    parser.add_argument(
        "--records-dir",
        type=Path,
        help="Read <doc_id>.json record snapshots instead of querying the API.",
    )
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    payload_in = json.loads(args.runs.read_text(encoding="utf-8"))
    documents = payload_in.get("documents")
    items = documents["pdf"] if isinstance(documents, dict) else (documents or [])
    if args.records_dir:
        items = []
        if args.registry:
            registry = json.loads(args.registry.read_text(encoding="utf-8"))
            sources = [
                {
                    "name": doc["doc_id"],
                    "path": doc["pdf"],
                    "category": "gold",
                }
                for doc in registry.get("documents") or []
            ]
        else:
            sources = [
                {"name": path.stem, "path": "", "category": "records"}
                for path in sorted(args.records_dir.glob("*.json"))
                if path.name != "index.json"
            ]
        for source in sources:
            snapshot = args.records_dir / f"{source['name']}.json"
            if not snapshot.exists():
                continue
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            items.append(
                {
                    **source,
                    "status": payload.get("status"),
                    "run_id": payload.get("run_id"),
                    "error_code": "",
                }
            )
    docs: list[dict[str, Any]] = []
    with httpx.Client(timeout=120) as client:
        for index, item in enumerate(items, start=1):
            print(f"[{index}/{len(items)}] {item['name'][:60]}")
            override = None
            if args.records_dir:
                snapshot = args.records_dir / f"{item['name']}.json"
                override = json.loads(snapshot.read_text(encoding="utf-8")).get("records") or []
            docs.append(audit_document(client, item, override))
    payload = {
        "generated_at": payload_in.get("generated_at"),
        "runs": str(args.runs),
        "summary": summarize(docs),
        "documents": docs,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(args.out_md, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
