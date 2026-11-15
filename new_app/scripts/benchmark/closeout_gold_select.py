#!/usr/bin/env python3
"""Select legacy ``result.json`` documents that are well grounded in the source PDF.

The legacy system is not treated as ground truth by default.  Every legacy
record is checked against the original PDF text; only documents whose grades
and values can be found near the recorded page are eligible as gold samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymupdf

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OLD_RUNS = REPO_ROOT / "data" / "validation-2026-11-06" / "runs" / "full9"
DEFAULT_PDF_MANIFEST = REPO_ROOT / "data" / "validation-2026-11-06" / "pdf_manifest.json"
DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "gold-standards.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "gold-standards.md"
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = (
        text.replace("（", "(")
        .replace("）", ")")
        .replace("≤", "<=")
        .replace("≥", ">=")
        .replace("～", "~")
        .replace("－", "-")
    )
    return re.sub(r"\s+", "", text)


def page_index(pdf_path: Path) -> list[str]:
    document = pymupdf.open(pdf_path)
    try:
        return [norm(page.get_text("text")) for page in document]
    finally:
        document.close()


def load_pdf_map(path: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    if not path.exists():
        return mapping
    for item in json.loads(path.read_text(encoding="utf-8")):
        markdown = Path(str(item.get("path") or ""))
        pdf = Path(str(item.get("source_pdf") or ""))
        if markdown.name and pdf.exists():
            mapping[markdown.name] = pdf
    return mapping


def norm_key(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def build_pdf_index(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in root.rglob("*.pdf"):
        if "node_modules" in path.parts or ".venv" in path.parts:
            continue
        index.setdefault(norm_key(path.stem), path)
    return index


def resolve_pdf(
    document: dict[str, Any], pdf_map: dict[str, Path], pdf_index: dict[str, Path]
) -> Path | None:
    source = str(document.get("source_path") or "")
    if source.lower().endswith(".pdf") and Path(source).exists():
        return Path(source)
    path = Path(source) if source else None
    if path is not None and path.suffix.lower() == ".md" and path.exists():
        head = path.read_text(encoding="utf-8", errors="ignore")[:2048]
        match = re.search(r"<!--\s*source:\s*(.+?)\s*-->", head)
        if match:
            candidate = Path(match.group(1))
            if candidate.exists():
                return candidate
    name = path.name if path is not None else ""
    if name and name in pdf_map:
        return pdf_map[name]
    title_key = norm_key(document.get("title"))
    if title_key and title_key in pdf_index:
        return pdf_index[title_key]
    if title_key and len(title_key) >= 8:
        for key, candidate in pdf_index.items():
            if (title_key in key or key in title_key) and min(len(title_key), len(key)) >= 8:
                return candidate
    return None


def audit_result(
    data: dict[str, Any], pdf_path: Path, *, page_window: int = 1
) -> dict[str, Any]:
    texts = page_index(pdf_path)
    full_text = "".join(texts)
    table_pages = {
        str(table.get("table_id")): int(table.get("page_no") or 1)
        for table in data.get("tables") or []
    }
    records = [item for item in data.get("records") or [] if isinstance(item, dict)]
    grade_checked = grade_grounded = value_grounded = fields = empty_records = 0
    key_counts: Counter[tuple[str, str, str]] = Counter()
    for record in records:
        page_no = table_pages.get(str(record.get("source_table_id") or ""), 1)
        lower = max(1, page_no - page_window)
        upper = min(len(texts), page_no + page_window)
        nearby = "".join(texts[index - 1] for index in range(lower, upper + 1))
        grade = str(record.get("grade") or "").strip()
        if grade and grade != "~":
            grade_checked += 1
            grade_grounded += int(norm(grade) in nearby or norm(grade) in full_text)
        properties = record.get("properties") or {}
        if not isinstance(properties, dict) or not properties:
            empty_records += 1
            continue
        condition = str(record.get("condition") or "")
        for measure, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            fields += 1
            key_counts[(grade, str(measure), condition)] += 1
            raw = norm(prop.get("raw"))
            value = prop.get("value")
            grounded = bool(raw) and (raw in nearby or raw in full_text)
            if not grounded and value is not None:
                grounded = str(value) in set(NUMBER_RE.findall(nearby + full_text))
            value_grounded += int(grounded)
    grade_rate = grade_grounded / max(1, grade_checked)
    value_rate = value_grounded / max(1, fields)
    return {
        "pages": len(texts),
        "records": len(records),
        "fields": fields,
        "grade_checked": grade_checked,
        "grade_grounded": grade_grounded,
        "grade_rate": round(grade_rate, 4),
        "value_grounded": value_grounded,
        "value_rate": round(value_rate, 4),
        "empty_records": empty_records,
        "empty_record_rate": round(empty_records / max(1, len(records)), 4),
        "duplicate_keys": sum(1 for count in key_counts.values() if count > 1),
        "pdf": str(pdf_path),
        "pdf_hash": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-runs", type=Path, default=DEFAULT_OLD_RUNS)
    parser.add_argument("--pdf-manifest", type=Path, default=DEFAULT_PDF_MANIFEST)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-records", type=int, default=5)
    parser.add_argument("--min-fields", type=int, default=10)
    parser.add_argument("--min-grade-rate", type=float, default=0.95)
    parser.add_argument("--min-value-rate", type=float, default=0.95)
    parser.add_argument("--max-empty-rate", type=float, default=0.02)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    pdf_map = load_pdf_map(args.pdf_manifest)
    pdf_index = build_pdf_index(REPO_ROOT)
    candidates: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for result_path in sorted(args.old_runs.rglob("result.json")):
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            skipped["invalid_json"] += 1
            continue
        document = data.get("document") or {}
        pdf_path = resolve_pdf(document, pdf_map, pdf_index)
        if pdf_path is None:
            skipped["no_source_pdf"] += 1
            continue
        metrics = audit_result(data, pdf_path)
        item = {
            "doc_id": result_path.parent.parent.name,
            "title": document.get("title") or result_path.parent.parent.name,
            "standard_no": document.get("standard_no"),
            "run_dir": str(result_path.parent.parent),
            **metrics,
        }
        eligible = (
            item["records"] >= args.min_records
            and item["fields"] >= args.min_fields
            and item["grade_rate"] >= args.min_grade_rate
            and item["value_rate"] >= args.min_value_rate
            and item["empty_record_rate"] <= args.max_empty_rate
        )
        item["eligible"] = eligible
        if not eligible:
            skipped["below_threshold"] += 1
        candidates.append(item)

    ranked = sorted(
        (item for item in candidates if item["eligible"]),
        key=lambda row: (-row["value_rate"], -row["grade_rate"], -row["fields"], row["title"]),
    )
    selected: list[dict[str, Any]] = []
    seen_pdf: set[str] = set()
    for item in ranked:
        key = str(item.get("pdf_hash") or Path(item["pdf"]).resolve())
        if key in seen_pdf:
            continue
        seen_pdf.add(key)
        selected.append(item)
        if len(selected) >= args.limit:
            break
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "old_runs": str(args.old_runs),
        "thresholds": {
            "min_records": args.min_records,
            "min_fields": args.min_fields,
            "min_grade_rate": args.min_grade_rate,
            "min_value_rate": args.min_value_rate,
            "max_empty_rate": args.max_empty_rate,
        },
        "scanned": len(candidates) + sum(skipped.values()),
        "with_source_pdf": len(candidates),
        "eligible": sum(1 for item in candidates if item["eligible"]),
        "selected": len(selected),
        "duplicate_runs": sum(1 for item in candidates if item["eligible"]) - len(selected),
        "skipped": dict(skipped),
        "documents": selected,
        "rejected": [
            item for item in candidates if not item["eligible"]
        ][:50],
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 旧项目金标筛选结果",
        "",
        f"> 生成时间：{payload['generated_at']}",
        f"> 旧运行目录：`{args.old_runs}`",
        "",
        "## 1. 汇总",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 扫描结果文件 | {payload['scanned']} |",
        f"| 可关联原文 PDF | {payload['with_source_pdf']} |",
        f"| 达到金标阈值 | {payload['eligible']} |",
        f"| 去重后入选 | {payload['selected']} |",
        f"| 重复运行已合并 | {payload['duplicate_runs']} |",
        f"| 跳过原因 | {json.dumps(payload['skipped'], ensure_ascii=False)} |",
        "",
        "阈值：记录数 ≥ {min_records}，字段数 ≥ {min_fields}，"
        "牌号命中 ≥ {min_grade_rate:.0%}，值命中 ≥ {min_value_rate:.0%}，"
        "空记录率 ≤ {max_empty_rate:.0%}".format(**payload["thresholds"]),
        "",
        "## 2. 金标文档",
        "",
        "| 文档 | 页 | 记录 | 字段 | 牌号命中 | 值命中 | 空记录 | 重复键 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in selected:
        lines.append(
            f"| {item['title'][:44]} | {item['pages']} | {item['records']} | {item['fields']} | "
            f"{item['grade_rate']:.0%} | {item['value_rate']:.0%} | "
            f"{item['empty_record_rate']:.0%} | {item['duplicate_keys']} |"
        )
    lines.extend(
        [
            "",
            "## 3. 使用说明",
            "",
            "- 仅代表“旧结果与原文一致”，不代表字段口径完整或业务上最优。",
            "- 入选文档可用于新系统回归基线；未入选文档不作为金标，避免把旧系统错误当成正确结果。",
            "- 原文核对优先使用记录所在页 ±1 页，未命中时回退到全文命中；"
            "数值按归一化 token 比对。",
            "- 同一原文 PDF 的多个旧运行只保留指标最好的一次；"
            "当前语料中多数 PDF 为无文本层扫描件，无法做原文核对，未纳入金标。",
        ]
    )
    args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: payload[key]
                for key in ("scanned", "with_source_pdf", "eligible", "selected", "skipped")
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
