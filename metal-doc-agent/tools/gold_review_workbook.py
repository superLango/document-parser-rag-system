"""Build the WS1 annotation assignment sheet and arbitration workbook.

Run from the repository root:
    python tools/gold_review_workbook.py \
      --gold goldset/v0/docs \
      --runs runs/m1_qwen_s8 \
      --dryrun goldset/v0/review/dryrun \
      --out goldset/v0/review
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gold_review_dryrun import audit_a  # noqa: E402
from metal_doc_agent.goldset import load_gold_document  # noqa: E402

MAX_ROWS = 1500
TYPE_ORDER = {
    "strict_diff": 0,
    "value_diff": 1,
    "a_audit": 2,
    "record_only_a": 3,
    "record_only_b": 4,
}


def _fmt(value: dict | None) -> tuple[str, str, str, str, str]:
    if not value:
        return "", "", "", "", ""
    evidence = value.get("evidence") or {}
    location = ""
    if evidence.get("table_id") or evidence.get("row") is not None:
        location = f"{evidence.get('table_id') or ''} r{evidence.get('row')} c{evidence.get('col')}"
    return (
        str(value.get("raw") or ""),
        "" if value.get("value") is None else str(value.get("value")),
        str(value.get("comparator") or ""),
        str(value.get("unit") or ""),
        location,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default="goldset/v0/docs")
    parser.add_argument("--runs", default="runs/m1_qwen_s8")
    parser.add_argument("--dryrun", default="goldset/v0/review/dryrun")
    parser.add_argument("--out", default="goldset/v0/review")
    args = parser.parse_args(argv)

    gold_dir = ROOT / args.gold
    runs_dir = ROOT / args.runs
    dryrun_dir = ROOT / args.dryrun
    out_dir = ROOT / args.out
    arbitration_dir = out_dir / "arbitration"
    arbitration_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    assignments: list[dict[str, str]] = []
    status_rows: list[dict[str, object]] = []

    for a_path in sorted(gold_dir.glob("*.json")):
        doc_id = a_path.stem
        a = load_gold_document(a_path)
        review_path = dryrun_dir / "reports" / f"{doc_id}.review.json"
        review = (
            json.loads(review_path.read_text(encoding="utf-8"))
            if review_path.exists()
            else {}
        )
        issues = audit_a(a, runs_dir / doc_id / "tablegrid")
        doc_rows: list[dict[str, str]] = []

        for diff in review.get("value_diffs", []):
            left = diff.get("a")
            right = diff.get("b")
            a_raw, a_value, a_comp, a_unit, a_loc = _fmt(left)
            b_raw, b_value, b_comp, b_unit, b_loc = _fmt(right)
            issue_type = "value_diff" if not diff.get("value_ok") else "strict_diff"
            doc_rows.append(
                {
                    "doc_id": doc_id,
                    "table_id": str(diff.get("table_id") or ""),
                    "record_id": str(diff.get("record_id") or ""),
                    "record_key": "|".join(str(x) for x in diff.get("record_key", [])),
                    "field": str(diff.get("field") or ""),
                    "issue_type": issue_type,
                    "a_raw": a_raw,
                    "a_value": a_value,
                    "a_comparator": a_comp,
                    "a_unit": a_unit,
                    "a_evidence": a_loc,
                    "b_raw": b_raw,
                    "b_value": b_value,
                    "b_comparator": b_comp,
                    "b_unit": b_unit,
                    "b_evidence": b_loc,
                    "decision": "",
                    "expert_note": "",
                    "status": "open",
                }
            )

        for issue in issues:
            detail = issue.get("a") or {}
            doc_rows.append(
                {
                    "doc_id": doc_id,
                    "table_id": str(issue.get("table_id") or ""),
                    "record_id": str(issue.get("record_id") or ""),
                    "record_key": "",
                    "field": str(issue.get("field") or ""),
                    "issue_type": "a_audit",
                    "a_raw": str(detail.get("raw") or detail.get("comparator") or detail.get("unit") or ""),
                    "a_value": str(detail.get("value") or ""),
                    "a_comparator": str(detail.get("comparator") or ""),
                    "a_unit": str(detail.get("unit") or ""),
                    "a_evidence": str(detail.get("header") or detail.get("quote") or ""),
                    "b_raw": "",
                    "b_value": "",
                    "b_comparator": "",
                    "b_unit": "",
                    "b_evidence": "",
                    "decision": "",
                    "expert_note": f"{issue.get('reason')}: {json.dumps(detail, ensure_ascii=False)}",
                    "status": "open",
                }
            )

        for key in review.get("record_keys_only_a", []):
            doc_rows.append(
                {
                    "doc_id": doc_id,
                    "table_id": str(key[0]) if key else "",
                    "record_id": "",
                    "record_key": "|".join(str(x) for x in key[1:]),
                    "field": "",
                    "issue_type": "record_only_a",
                    "a_raw": "",
                    "a_value": "",
                    "a_comparator": "",
                    "a_unit": "",
                    "a_evidence": "",
                    "b_raw": "",
                    "b_value": "",
                    "b_comparator": "",
                    "b_unit": "",
                    "b_evidence": "",
                    "decision": "",
                    "expert_note": "A 有、B 无；可能为 A partial scope 或 B 抽取缺口",
                    "status": "open",
                }
            )
        for key in review.get("record_keys_only_b", []):
            doc_rows.append(
                {
                    "doc_id": doc_id,
                    "table_id": str(key[0]) if key else "",
                    "record_id": "",
                    "record_key": "|".join(str(x) for x in key[1:]),
                    "field": "",
                    "issue_type": "record_only_b",
                    "a_raw": "",
                    "a_value": "",
                    "a_comparator": "",
                    "a_unit": "",
                    "a_evidence": "",
                    "b_raw": "",
                    "b_value": "",
                    "b_comparator": "",
                    "b_unit": "",
                    "b_evidence": "",
                    "decision": "",
                    "expert_note": "B 有、A 无；可能为 A partial scope",
                    "status": "open",
                }
            )

        doc_rows.sort(key=lambda row: (TYPE_ORDER.get(row["issue_type"], 9), row["table_id"], row["record_id"]))
        rows.extend(doc_rows)
        assignments.append(
            {
                "doc_id": doc_id,
                "a_file": f"a/{a_path.name}",
                "b_file": f"b/{a_path.name}",
                "a_annotator": "agent-draft-s7 (verified baseline)",
                "b_annotator": "TBD",
                "reviewer": "TBD",
                "status": "pending_human_b",
            }
        )
        status_rows.append(
            {
                "doc_id": doc_id,
                "a_status": a.annotation.status,
                "b_status": "pending",
                "dryrun_rows": len(doc_rows),
                "strict_diffs": sum(1 for row in doc_rows if row["issue_type"] == "strict_diff"),
                "value_diffs": sum(1 for row in doc_rows if row["issue_type"] == "value_diff"),
                "a_audit": sum(1 for row in doc_rows if row["issue_type"] == "a_audit"),
            }
        )

    fieldnames = [
        "doc_id",
        "table_id",
        "record_id",
        "record_key",
        "field",
        "issue_type",
        "a_raw",
        "a_value",
        "a_comparator",
        "a_unit",
        "a_evidence",
        "b_raw",
        "b_value",
        "b_comparator",
        "b_unit",
        "b_evidence",
        "decision",
        "expert_note",
        "status",
    ]
    workbook = arbitration_dir / "workbook.csv"
    with workbook.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows[:MAX_ROWS])

    (out_dir / "assignments.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-10-26",
                "documents": assignments,
                "note": "B 标注员与仲裁人待指定；owner-override 保留到人工 A/B 完成。",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    status_lines = [
        "# WS1 标注治理状态看板",
        "",
        "| 文档 | A 状态 | B 状态 | dry-run 行 | 严格差异 | 值差异 | A 审计 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in status_rows:
        status_lines.append(
            f"| {row['doc_id']} | {row['a_status']} | {row['b_status']} | {row['dryrun_rows']} | "
            f"{row['strict_diffs']} | {row['value_diffs']} | {row['a_audit']} |"
        )
    status_lines.extend(
        [
            "",
            f"- workbook：`goldset/v0/review/arbitration/workbook.csv`（{min(len(rows), MAX_ROWS)} 行，最多 {MAX_ROWS} 行）",
            "- B 标注员：TBD；仲裁人：TBD。",
            "- `owner-override` 保留，人工 A/B 完成前不做 verified 变更。",
        ]
    )
    (out_dir / "status.md").write_text("\n".join(status_lines) + "\n", encoding="utf-8")

    print(f"documents={len(assignments)} workbook_rows={min(len(rows), MAX_ROWS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
