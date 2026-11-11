"""Batch A/B annotation diff for the WS1 review packet.

Run from the repository root:
    python tools/gold_review_batch.py \
      --a goldset/v0/review/a \
      --b goldset/v0/review/b \
      --out goldset/v0/review/reports
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.goldset import load_gold_document  # noqa: E402
from metal_doc_agent.goldset_review import review_annotations  # noqa: E402


def _is_empty_b(path: Path) -> bool:
    doc = load_gold_document(path)
    has_records = any(table.records for table in doc.tables)
    has_items = any(
        table.inspection_items or table.classification_items for table in doc.tables
    )
    return not (has_records or has_items or doc.clauses)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch A/B gold annotation diff")
    parser.add_argument("--a", default="goldset/v0/review/a", help="A annotation directory")
    parser.add_argument("--b", default="goldset/v0/review/b", help="B annotation directory")
    parser.add_argument("--out", default="goldset/v0/review/reports", help="report directory")
    parser.add_argument("--strict", action="store_true", help="exit 1 when a filled doc fails")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    a_dir = ROOT / args.a
    b_dir = ROOT / args.b
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    for a_path in sorted(a_dir.glob("*.json")):
        b_path = b_dir / a_path.name
        if not b_path.exists():
            rows.append({"doc_id": a_path.stem, "status": "missing_b"})
            continue
        if _is_empty_b(b_path):
            rows.append({"doc_id": a_path.stem, "status": "pending"})
            continue
        review = review_annotations(a_path, b_path)
        payload = review.to_dict()
        (out_dir / f"{a_path.stem}.review.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        rows.append(
            {
                "doc_id": a_path.stem,
                "status": "pass" if review.passed else "fail",
                **review.metrics,
                "counts": review.counts,
            }
        )

    lines = [
        "# A/B 标注复核汇总",
        "",
        "| 文档 | 状态 | record_key | cell_value | comparator_unit | clause_field |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row["status"] in {"pending", "missing_b"}:
            lines.append(f"| {row['doc_id']} | {row['status']} | - | - | - | - |")
        else:
            lines.append(
                f"| {row['doc_id']} | {row['status']} | "
                f"{row.get('record_key_agreement', 0):.4f} | "
                f"{row.get('cell_value_agreement', 0):.4f} | "
                f"{row.get('comparator_unit_agreement', 0):.4f} | "
                f"{row.get('clause_field_agreement', 0):.4f} |"
            )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    pending = sum(1 for row in rows if row["status"] == "pending")
    failed = [row["doc_id"] for row in rows if row["status"] == "fail"]
    print(f"documents={len(rows)} pending={pending} failed={len(failed)}")
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if args.strict and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
