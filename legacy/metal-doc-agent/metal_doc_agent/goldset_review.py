"""A/B annotation review for the golden set.

Two annotators must independently transcribe the same document. This module
compares their files at the record/field/clause level and applies the gates from
``docs/annotation.md``. It never invents labels; it only reports disagreement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .eval.metrics import close, norm_text, record_key
from .goldset import GoldDocument, GoldValue, load_gold_document

DEFAULT_THRESHOLDS = {
    "record_key_agreement": 0.99,
    "cell_value_agreement": 0.98,
    "comparator_unit_agreement": 0.99,
    "clause_field_agreement": 0.95,
}
MAX_DIFFS = 200


@dataclass
class AnnotationReview:
    doc_id: str
    counts: dict[str, int]
    metrics: dict[str, float]
    thresholds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    record_keys_only_a: list[list[str]] = field(default_factory=list)
    record_keys_only_b: list[list[str]] = field(default_factory=list)
    value_diffs: list[dict[str, Any]] = field(default_factory=list)
    clause_field_diffs: list[dict[str, Any]] = field(default_factory=list)
    table_diffs: list[dict[str, Any]] = field(default_factory=list)
    annotation_status: tuple[str, str] = ("draft", "draft")

    @property
    def passed(self) -> bool:
        return all(
            self.metrics[name] >= threshold
            for name, threshold in self.thresholds.items()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "passed": self.passed,
            "annotation_status": list(self.annotation_status),
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "counts": self.counts,
            "record_keys_only_a": self.record_keys_only_a,
            "record_keys_only_b": self.record_keys_only_b,
            "value_diffs": self.value_diffs,
            "clause_field_diffs": self.clause_field_diffs,
            "table_diffs": self.table_diffs,
        }


def review_annotations(path_a: str | Path, path_b: str | Path) -> AnnotationReview:
    a = load_gold_document(path_a)
    b = load_gold_document(path_b)
    if a.doc_id != b.doc_id:
        raise ValueError(f"doc_id mismatch: {a.doc_id} != {b.doc_id}")

    counts = {
        "record_keys_total": 0,
        "record_keys_match": 0,
        "cells_total": 0,
        "cells_value_match": 0,
        "cells_strict_match": 0,
        "clause_fields_total": 0,
        "clause_fields_match": 0,
    }
    review = AnnotationReview(
        doc_id=a.doc_id,
        counts=counts,
        metrics={},
        annotation_status=(a.annotation.status, b.annotation.status),
    )

    _diff_tables(a, b, review)
    records_a = _record_map(a)
    records_b = _record_map(b)
    keys_a, keys_b = set(records_a), set(records_b)
    review.record_keys_only_a = [list(key) for key in sorted(keys_a - keys_b)][:MAX_DIFFS]
    review.record_keys_only_b = [list(key) for key in sorted(keys_b - keys_a)][:MAX_DIFFS]
    counts["record_keys_total"] = len(keys_a | keys_b)
    counts["record_keys_match"] = len(keys_a & keys_b)

    for key in sorted(keys_a & keys_b):
        left, right = records_a[key], records_b[key]
        for name in sorted(set(left.properties) | set(right.properties)):
            counts["cells_total"] += 1
            left_value = left.properties.get(name)
            right_value = right.properties.get(name)
            value_ok = (
                left_value is not None
                and right_value is not None
                and values_equal(left_value, right_value)
            )
            strict_ok = value_ok and strict_values_equal(left_value, right_value)
            if value_ok:
                counts["cells_value_match"] += 1
            if strict_ok:
                counts["cells_strict_match"] += 1
            if not strict_ok and len(review.value_diffs) < MAX_DIFFS:
                review.value_diffs.append(
                    {
                        "table_id": key[0],
                        "record_key": list(key[1:]),
                        "record_id": left.record_id,
                        "field": name,
                        "value_ok": value_ok,
                        "strict_ok": strict_ok,
                        "a": _value_dict(left_value),
                        "b": _value_dict(right_value),
                    }
                )

    clauses_a = {clause.clause_id: clause for clause in a.clauses}
    clauses_b = {clause.clause_id: clause for clause in b.clauses}
    for clause_id in sorted(set(clauses_a) | set(clauses_b)):
        left, right = clauses_a.get(clause_id), clauses_b.get(clause_id)
        fields = set((left.fields if left else {})) | set((right.fields if right else {}))
        for name in sorted(fields):
            counts["clause_fields_total"] += 1
            left_value = left.fields.get(name) if left else None
            right_value = right.fields.get(name) if right else None
            matched = (
                left_value is not None
                and right_value is not None
                and strict_values_equal(left_value, right_value)
            )
            if matched:
                counts["clause_fields_match"] += 1
            elif len(review.clause_field_diffs) < MAX_DIFFS:
                review.clause_field_diffs.append(
                    {
                        "clause_id": clause_id,
                        "field": name,
                        "a": _value_dict(left_value),
                        "b": _value_dict(right_value),
                    }
                )

    review.metrics = {
        "record_key_agreement": _ratio(
            counts["record_keys_match"], counts["record_keys_total"]
        ),
        "cell_value_agreement": _ratio(
            counts["cells_value_match"], counts["cells_total"]
        ),
        "comparator_unit_agreement": _ratio(
            counts["cells_strict_match"], counts["cells_total"]
        ),
        "clause_field_agreement": _ratio(
            counts["clause_fields_match"], counts["clause_fields_total"]
        ),
    }
    return review


def values_equal(left: GoldValue, right: GoldValue) -> bool:
    if left.comparator == "range" or right.comparator == "range":
        return close(left.lower, right.lower) and close(left.upper, right.upper)
    if left.comparator == "text" or right.comparator == "text":
        return norm_text(left.text or left.raw) == norm_text(right.text or right.raw)
    if left.comparator == "na" or right.comparator == "na":
        return left.comparator == right.comparator
    return close(left.value, right.value)


def strict_values_equal(left: GoldValue | None, right: GoldValue | None) -> bool:
    if left is None or right is None:
        return False
    return (
        values_equal(left, right)
        and norm_text(left.comparator) == norm_text(right.comparator)
        and norm_text(left.unit) == norm_text(right.unit)
    )


def _record_map(doc: GoldDocument) -> dict[tuple[str, ...], Any]:
    records: dict[tuple[str, ...], Any] = {}
    for table in doc.tables:
        for record in table.records:
            key = (
                table.table_id,
                *record_key(record.grade, record.grade_level, record.condition),
            )
            if key in records:
                key = (*key, record.record_id)
            records[key] = record
    return records


def _diff_tables(a: GoldDocument, b: GoldDocument, review: AnnotationReview) -> None:
    tables_a = {table.table_id: table for table in a.tables}
    tables_b = {table.table_id: table for table in b.tables}
    for table_id in sorted(set(tables_a) | set(tables_b)):
        left, right = tables_a.get(table_id), tables_b.get(table_id)
        if left is None or right is None:
            review.table_diffs.append(
                {
                    "table_id": table_id,
                    "issue": "missing_in_a" if left is None else "missing_in_b",
                }
            )
            continue
        if (left.profile, left.scope, left.orientation) != (
            right.profile,
            right.scope,
            right.orientation,
        ):
            review.table_diffs.append(
                {
                    "table_id": table_id,
                    "issue": "metadata",
                    "a": [left.profile, left.scope, left.orientation],
                    "b": [right.profile, right.scope, right.orientation],
                }
            )


def _value_dict(value: GoldValue | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "raw": value.raw,
        "value": value.value,
        "lower": value.lower,
        "upper": value.upper,
        "text": value.text,
        "unit": value.unit,
        "comparator": value.comparator,
        "condition": value.condition,
        "evidence": {
            "page_no": value.evidence.page_no,
            "table_id": value.evidence.table_id,
            "row": value.evidence.row,
            "col": value.evidence.col,
            "clause_id": value.evidence.clause_id,
            "quote": value.evidence.quote,
        },
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def write_review_report(review: AnnotationReview, out_path: str | Path) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_markdown(review) + "\n", encoding="utf-8")


def render_review_markdown(review: AnnotationReview) -> str:
    lines = [
        f"# A/B 标注一致性：{review.doc_id}",
        "",
        f"- 状态：{'通过' if review.passed else '未通过'}",
        f"- 标注状态：A={review.annotation_status[0]} / B={review.annotation_status[1]}",
        "",
        "| 指标 | 值 | 门槛 |",
        "|---|---|---|",
    ]
    for name, threshold in review.thresholds.items():
        lines.append(f"| {name} | {review.metrics[name]} | {threshold} |")
    counts = review.counts
    lines.extend(
        [
            "",
            f"- 记录键：{counts['record_keys_match']}/{counts['record_keys_total']}",
            f"- 单元格值：{counts['cells_value_match']}/{counts['cells_total']}",
            f"- 值+比较符+单位：{counts['cells_strict_match']}/{counts['cells_total']}",
            f"- 条款字段：{counts['clause_fields_match']}/{counts['clause_fields_total']}",
        ]
    )
    if review.record_keys_only_a or review.record_keys_only_b:
        lines.extend(["", "## 记录键差异", ""])
        for key in review.record_keys_only_a:
            lines.append(f"- A only: {' / '.join(key)}")
        for key in review.record_keys_only_b:
            lines.append(f"- B only: {' / '.join(key)}")
    if review.value_diffs:
        lines.extend(["", "## 单元格差异", ""])
        for diff in review.value_diffs[:50]:
            lines.append(
                f"- {diff['table_id']} {' / '.join(diff['record_key'])} / {diff['field']}: "
                f"A={json.dumps(diff['a'], ensure_ascii=False)} "
                f"B={json.dumps(diff['b'], ensure_ascii=False)}"
            )
    if review.clause_field_diffs:
        lines.extend(["", "## 条款字段差异", ""])
        for diff in review.clause_field_diffs[:50]:
            lines.append(
                f"- {diff['clause_id']} / {diff['field']}: "
                f"A={json.dumps(diff['a'], ensure_ascii=False)} "
                f"B={json.dumps(diff['b'], ensure_ascii=False)}"
            )
    return "\n".join(lines)
