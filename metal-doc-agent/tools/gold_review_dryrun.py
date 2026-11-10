"""AI independent review dry-run for the WS1 A/B packet.

B is generated from runs/m1_qwen_s8 (chemical/mechanical records only) and is
explicitly a dry-run draft, not a human annotation. The script also audits the
A annotation against TableGrid headers and evidence locators.

Run from the repository root:
    python tools/gold_review_dryrun.py \
      --gold goldset/v0/docs \
      --runs runs/m1_qwen_s8 \
      --out goldset/v0/review/dryrun
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import DocumentResult, Evidence  # noqa: E402
from metal_doc_agent.eval.metrics import close, property_key  # noqa: E402
from metal_doc_agent.goldset import (  # noqa: E402
    AnnotationMeta,
    GoldEvidence,
    GoldRecord,
    GoldValue,
    load_gold_document,
)
from metal_doc_agent.goldset_review import review_annotations  # noqa: E402
from metal_doc_agent.tablegrid.normalize import clean_text, normalize_value  # noqa: E402

SCORED = {"chemical_composition", "mechanical_properties"}


def load_evidence(path: Path) -> dict[str, Evidence]:
    evidence: dict[str, Evidence] = {}
    if not path.exists():
        return evidence
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = Evidence.model_validate_json(line)
        evidence[item.evidence_id] = item
    return evidence


def build_b(a, result: DocumentResult, evidence: dict[str, Evidence]):
    b = a.model_copy(deep=True)
    b.annotation = AnnotationMeta(
        status="draft",
        annotator="agent-B-dryrun",
        reviewers=[],
        updated_at="2026-10-26",
        notes=[
            "AI dry-run B：由 runs/m1_qwen_s8 生成，仅覆盖 chemical/mechanical 记录；"
            "inspection/classification/clause 不在本次范围；不得作为 verified 依据。"
        ],
    )
    b.notes = ["AI dry-run B"]
    b.clauses = []
    tables = []
    for table in a.tables:
        b_table = table.model_copy(deep=True)
        b_table.records = []
        b_table.inspection_items = []
        b_table.classification_items = []
        b_table.note = "AI dry-run B"
        if table.profile in SCORED:
            for record in result.records:
                if record.source_table_id != table.table_id:
                    continue
                properties: dict[str, GoldValue] = {}
                for name, value in record.properties.items():
                    item = evidence.get(value.evidence_id)
                    if item is None:
                        continue
                    properties[name] = GoldValue(
                        raw=value.raw,
                        value=value.value,
                        text=value.text,
                        unit=value.unit,
                        comparator=value.comparator,
                        lower=value.lower,
                        upper=value.upper,
                        condition=value.condition,
                        evidence=GoldEvidence(
                            page_no=item.page_no,
                            table_id=item.table_id,
                            row=item.row,
                            col=item.col,
                            clause_id=getattr(item, "clause_id", None),
                            quote=item.quote,
                        ),
                    )
                if properties:
                    b_table.records.append(
                        GoldRecord(
                            record_id=record.record_id,
                            grade=record.grade,
                            grade_level=record.grade_level,
                            condition=record.condition,
                            facets=record.facets,
                            properties=properties,
                            note=None,
                        )
                    )
        tables.append(b_table)
    b.tables = tables
    return b


def expected_comparator(header: str) -> str | None:
    text = clean_text(header)
    if "不小于" in text:
        return "min"
    if "不大于" in text:
        return "max"
    if any(marker in text for marker in ("≤", "<=", "最高", "最大")):
        return "max"
    if any(marker in text for marker in ("≥", ">=", "最低", "最小")):
        return "min"
    return None


def value_parse_issue(value: GoldValue) -> str | None:
    if value.comparator in {"eq", "min", "max"}:
        parsed = normalize_value(value.raw, value.unit)
        if parsed.get("comparator") in {"eq", "min", "max"}:
            parsed_value = parsed.get("value")
            if (
                parsed_value is None
                or value.value is None
                or not close(value.value, parsed_value)
            ):
                return "value_parse_mismatch"
    elif value.comparator == "range":
        parsed = normalize_value(value.raw, value.unit)
        if parsed.get("comparator") == "range":
            pairs = {parsed.get("lower"), parsed.get("upper")}
            expected = {value.lower, value.upper}
            if None in pairs or pairs != expected:
                return "value_parse_mismatch"
    return None


def audit_a(a, grid_dir: Path) -> list[dict]:
    issues: list[dict] = []
    for table in a.tables:
        if table.profile not in SCORED:
            continue
        grid_path = grid_dir / f"{table.table_id}.json"
        if not grid_path.exists():
            continue
        grid = json.loads(grid_path.read_text(encoding="utf-8"))
        rows = grid.get("rows", [])
        headers = grid.get("header_paths", [])
        for record in table.records:
            for name, value in record.properties.items():
                evidence = value.evidence
                if (
                    evidence.table_id == table.table_id
                    and evidence.row is not None
                    and evidence.col is not None
                    and evidence.row < len(rows)
                    and evidence.col < len(rows[evidence.row])
                ):
                    cell = clean_text(rows[evidence.row][evidence.col])
                    quote = clean_text(evidence.quote)
                    if cell != quote and quote not in cell:
                        issues.append(
                            {
                                "table_id": table.table_id,
                                "record_id": record.record_id,
                                "field": name,
                                "reason": "evidence_quote_mismatch",
                                "a": {"raw": value.raw, "quote": evidence.quote, "cell": cell},
                            }
                        )
                if evidence.col is not None and evidence.col < len(headers):
                    header = " ".join(headers[evidence.col])
                    expected = expected_comparator(header)
                    raw = clean_text(value.raw)
                    raw_has_symbol = any(
                        marker in raw for marker in ("≤", "≥", "<", ">", "不大于", "不小于")
                    )
                    if (
                        expected
                        and not raw_has_symbol
                        and value.comparator not in {expected, "range", "na", "text"}
                    ):
                        issues.append(
                            {
                                "table_id": table.table_id,
                                "record_id": record.record_id,
                                "field": name,
                                "reason": "comparator_header_mismatch",
                                "a": {
                                    "comparator": value.comparator,
                                    "expected": expected,
                                    "header": header,
                                },
                            }
                        )
                parse_issue = value_parse_issue(value)
                if parse_issue:
                    issues.append(
                        {
                            "table_id": table.table_id,
                            "record_id": record.record_id,
                            "field": name,
                            "reason": parse_issue,
                            "a": {
                                "raw": value.raw,
                                "value": value.value,
                                "lower": value.lower,
                                "upper": value.upper,
                                "comparator": value.comparator,
                            },
                        }
                    )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI dry-run A/B review")
    parser.add_argument("--gold", default="goldset/v0/docs")
    parser.add_argument("--runs", default="runs/m1_qwen_s8")
    parser.add_argument("--out", default="goldset/v0/review/dryrun")
    args = parser.parse_args(argv)

    gold_dir = ROOT / args.gold
    runs_dir = ROOT / args.runs
    out_dir = ROOT / args.out
    b_dir = out_dir / "b"
    report_dir = out_dir / "reports"
    b_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    all_issues: dict[str, list[dict]] = {}
    for a_path in sorted(gold_dir.glob("*.json")):
        doc_id = a_path.stem
        run_dir = runs_dir / doc_id
        result_path = run_dir / "result.json"
        if not result_path.exists():
            summary_rows.append({"doc_id": doc_id, "status": "missing_run"})
            continue
        a = load_gold_document(a_path)
        result = DocumentResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        evidence = load_evidence(run_dir / "evidence.jsonl")
        b = build_b(a, result, evidence)
        b_path = b_dir / a_path.name
        b_path.write_text(
            json.dumps(b.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        review = review_annotations(a_path, b_path)
        (report_dir / f"{doc_id}.review.json").write_text(
            json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        issues = audit_a(a, run_dir / "tablegrid")
        all_issues[doc_id] = issues
        summary_rows.append(
            {
                "doc_id": doc_id,
                "status": "ok",
                **review.metrics,
                "record_keys_a": review.counts["record_keys_total"],
                "record_keys_match": review.counts["record_keys_match"],
                "cells_total": review.counts["cells_total"],
                "cells_value_match": review.counts["cells_value_match"],
                "cells_strict_match": review.counts["cells_strict_match"],
                "a_audit_issues": len(issues),
            }
        )

    lines = [
        "# AI 独立复核 dry-run 汇总",
        "",
        "> B 由 `runs/m1_qwen_s8` 生成，仅覆盖 chemical/mechanical 记录；inspection/classification/clause 不在本次范围。",
        "> 本报告仅用于差异排查，不作为 verified 依据，不移除 owner-override。",
        "",
        "| 文档 | 记录键 | 值 | 严格值 | A 审计问题 |",
        "|---|---|---|---|---|",
    ]
    for row in summary_rows:
        if row["status"] != "ok":
            lines.append(f"| {row['doc_id']} | {row['status']} | - | - | - |")
        else:
            lines.append(
                f"| {row['doc_id']} | {row['record_key_agreement']:.4f} | "
                f"{row['cell_value_agreement']:.4f} | {row['comparator_unit_agreement']:.4f} | "
                f"{row['a_audit_issues']} |"
            )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(summary_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    audit_lines = [
        "# A 标注独立审计（dry-run）",
        "",
        "> 依据 TableGrid 表头 comparator、原始值与证据 locator 对 A 做规则审计；不修改 A。",
        "",
        "| 文档 | 表 | 记录 | 字段 | 原因 | A 值/evidence |",
        "|---|---|---|---|---|---|",
    ]
    reason_counts: Counter[str] = Counter()
    for doc_id, issues in all_issues.items():
        for issue in issues:
            reason_counts[issue["reason"]] += 1
            detail = json.dumps(issue.get("a", {}), ensure_ascii=False)
            audit_lines.append(
                f"| {doc_id} | {issue['table_id']} | {issue['record_id']} | "
                f"{issue['field']} | {issue['reason']} | {detail} |"
            )
    audit_lines.extend(
        [
            "",
            "## 原因统计",
            "",
            "| 原因 | 数量 |",
            "|---|---|",
        ]
    )
    for reason, count in reason_counts.most_common():
        audit_lines.append(f"| {reason} | {count} |")
    (out_dir / "a_audit.md").write_text("\n".join(audit_lines) + "\n", encoding="utf-8")

    print(f"documents={len(summary_rows)} a_audit_issues={sum(reason_counts.values())}")
    for reason, count in reason_counts.most_common():
        print(f"  {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
