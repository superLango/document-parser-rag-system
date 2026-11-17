#!/usr/bin/env python3
"""用金标 PDF 的文本层回放正文条款，核对定性/正文类项目覆盖。

金标 30 份的 ``source_tables`` 只覆盖表格；尺寸/外观/低倍/晶粒度/夹杂/
超声/晶间腐蚀等要求写在正文里。本脚本用 PyMuPDF 直接读取源 PDF 文本，
交给 clause/inventory/projection 链路，按 feature 与
``supplements/prose_items.json`` 对照。

用法（容器内）：
  python replay_prose_gold.py --only gbt-3280-2015,gjb-5040-2001 --out /out/prose.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RUNTIME_DIR = Path(os.environ.get("REPLAY_RUNTIME_DIR", "/app/services/sandbox/runtime"))
sys.path.insert(0, str(RUNTIME_DIR))

import builtin  # noqa: E402
import projection as projection_module  # noqa: E402


TEXT_ONLY_FEATURES = {
    "尺寸",
    "外观",
    "晶间腐蚀",
    "非金属夹杂",
    "低倍",
    "断口",
    "晶粒度",
    "超声波检测",
    "涡流检测",
    "高倍组织",
    "铁素体",
    "表面粗糙度",
    "脱脂",
    "相变温度",
}


def pdf_pages(path: Path) -> list[str]:
    import fitz  # PyMuPDF

    pages: list[str] = []
    with fitz.open(path) as document:
        for page in document:
            pages.append(page.get_text("text"))
    return pages


def replay(path: Path) -> dict:
    pages = pdf_pages(path)
    markdown = "\n".join(pages)
    builtin._table_fingerprints.clear()
    builtin._DOCUMENT_TEXT_CACHE = markdown
    records: list[dict] = []
    evidence: list[dict] = []
    diagnostics: list[dict] = []
    ocr = {
        "schema_version": "prose-replay/1",
        "markdown": markdown,
        "pages": [
            {"page_no": index, "markdown": text}
            for index, text in enumerate(pages, start=1)
        ],
        "tables": [],
        "layout": [],
        "backend": "prose-replay",
    }
    payload = projection_module.apply_document_intelligence(
        records, evidence, ocr, diagnostics
    )
    heat_records, _ = builtin.document_heat_records(ocr)
    heat_features = len(heat_records)
    feature_records: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if str(record.get("profile") or "") != "qualitative":
            continue
        for feature, prop in (record.get("properties") or {}).items():
            if isinstance(prop, dict):
                feature_records[str(feature)].append(
                    {
                        "raw": prop.get("raw"),
                        "clause": (prop.get("source") or {}).get("clause_id"),
                        "unit": prop.get("unit"),
                        "comparator": prop.get("comparator"),
                    }
                )
    clauses = payload.get("clauses") or {}
    stats = (payload.get("intelligence") or {}).get("stats") or {}
    return {
        "features": {name: len(items) for name, items in feature_records.items()},
        "heat_records": heat_features,
        "feature_records": dict(feature_records),
        "stats": stats,
        "clauses": (clauses.get("stats") or {}).get("clauses", 0),
        "clause_kinds": (clauses.get("stats") or {}).get("kinds", {}),
        "diagnostics": [
            {"code": item.get("code"), "message": item.get("message")}
            for item in diagnostics
            if item.get("severity") != "info"
        ][:40],
    }


def gold_prose(root: Path, doc_id: str) -> dict[str, list[str]]:
    path = root / "supplements" / "prose_items.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    document = (payload.get("documents") or {}).get(doc_id) or {}
    out: dict[str, list[str]] = {}
    for category in document.get("categories") or []:
        feature = str(category.get("feature") or "")
        names = [
            str(record.get("项目名称") or "")
            for record in category.get("records") or []
            if str(record.get("项目名称") or "")
        ]
        if names:
            out[feature] = list(dict.fromkeys(names))
    return out


def resolve_pdf(raw: str) -> Path:
    path = Path(str(raw or ""))
    if path.exists():
        return path
    # 金标 index.json 记录的是 Windows 绝对路径；容器内工作区挂在 /data。
    text = str(raw or "").replace("\\", "/")
    marker = "/hanson_doc_parse/"
    if marker in text:
        return Path("/data") / text.split(marker, 1)[1]
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/data/gold_standard_30")
    parser.add_argument("--only", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    root = Path(args.root)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    wanted = {item for item in args.only.split(",") if item}
    results = []
    for item in index["documents"]:
        doc_id = str(item["doc_id"])
        if wanted and doc_id not in wanted:
            continue
        pdf_path = resolve_pdf(str(item.get("source_pdf") or ""))
        if not pdf_path.exists():
            print(f"{doc_id}: pdf missing ({pdf_path})")
            continue
        replay_payload = replay(pdf_path)
        gold = gold_prose(root, doc_id)
        missing = {
            feature: names
            for feature, names in gold.items()
            if feature in TEXT_ONLY_FEATURES
            and not replay_payload["features"].get(feature)
        }
        partial = {
            feature: {
                "gold": len(names),
                "ours": replay_payload["features"].get(feature, 0),
            }
            for feature, names in gold.items()
            if feature in TEXT_ONLY_FEATURES and replay_payload["features"].get(feature)
        }
        result = {
            "doc_id": doc_id,
            "clauses": replay_payload["clauses"],
            "clause_kinds": replay_payload["clause_kinds"],
            "features": replay_payload["features"],
            "heat_records": replay_payload["heat_records"],
            "gold_text_features": {
                feature: len(names) for feature, names in gold.items()
            },
            "missing_text_features": missing,
            "partial_text_features": partial,
            "sample_records": {
                feature: records[:3]
                for feature, records in replay_payload["feature_records"].items()
                if feature in TEXT_ONLY_FEATURES
            },
            "diagnostics": replay_payload["diagnostics"],
        }
        results.append(result)
        print(
            f"{doc_id[:34]:<34} clauses={replay_payload['clauses']:<4d} "
            f"heat={replay_payload['heat_records']:<4d} "
            f"ours={json.dumps(replay_payload['features'], ensure_ascii=False)[:110]} "
            f"missing={json.dumps(sorted(missing), ensure_ascii=False)}"
        )
    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
