"""S1 演示/评估：把 20 份 v2 产物做归一化，输出统计报告。

不修改 v2 代码；仅作为 app_v3 S1 归一化层的能力验证。
用法（仓库根目录）：
  python app_v3/scripts/s1_demo.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.normalize.aliases import extract_document_aliases  # noqa: E402
from app_v3.normalize.pipeline import normalize_records, summarize  # noqa: E402
from app_v3.normalize.report import write_report  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
EVAL = ROOT / "app_v3" / "eval"
DOCS = ROOT / "app_v3" / "docs"


def main() -> int:
    EVAL.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    all_records: list[dict] = []
    per_doc: list[dict] = []
    grade_rejected_examples: list[dict] = []
    item_examples: list[dict] = []
    for doc_dir in sorted(BASE.iterdir()):
        if not doc_dir.is_dir():
            continue
        report = doc_dir / "extract" / "assembled" / "assembly-report.json"
        if not report.exists():
            continue
        ocr = doc_dir / "ocr" / "ocr.json"
        aliases = {}
        if ocr.exists():
            payload = json.loads(ocr.read_text(encoding="utf-8"))
            aliases = extract_document_aliases(
                [str(page.get("markdown") or "") for page in payload.get("pages") or []]
            )
        raw_records = json.loads(report.read_text(encoding="utf-8")).get("records") or []
        normalized = normalize_records(raw_records, aliases)
        all_records.extend(normalized)
        summary = summarize(normalized)
        per_doc.append({"doc": doc_dir.name, **summary})
        for raw, norm in zip(raw_records, normalized):
            for diagnostic in norm.get("diagnostics") or []:
                if diagnostic.get("code") == "grade_rejected" and len(grade_rejected_examples) < 20:
                    grade_rejected_examples.append({
                        "doc": doc_dir.name,
                        "raw_grade": diagnostic.get("raw"),
                        "item": norm.get("item"),
                        "requirement": norm.get("requirement"),
                    })
            if len(item_examples) < 20:
                raw_item = str(raw.get("item") or "")
                if raw_item and raw_item != norm.get("item"):
                    item_examples.append({"doc": doc_dir.name, "raw": raw_item, "normalized": norm.get("item")})

    summary = summarize(all_records)
    summary["documents"] = len(per_doc)
    summary["grade_rejected_examples"] = grade_rejected_examples
    summary["item_normalized_examples"] = item_examples
    summary["per_document"] = per_doc
    (EVAL / "s1-normalization-report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_report(summary, DOCS / "S1-normalization-report.md")
    print(f"[s1] documents={len(per_doc)} records={summary['total']} status={summary['status']} "
          f"grade_resolved={summary['grade_resolved']} ({summary['grade_resolved_rate']})")
    print(f"[s1] diagnostics={summary['diagnostics']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
