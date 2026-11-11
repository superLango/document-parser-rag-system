"""Golden set evaluation.

The evaluator is intentionally strict: values must carry the right comparator
and unit, and every published value must point at evidence. It also reports a
weaker ``value_accuracy`` that ignores comparator/unit so normalization and
semantic errors can be told apart from missing schema fields.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import DocumentResult, Evidence, ExtractedValue
from ..goldset import GoldDocument, GoldManifest, GoldValue, load_gold_document, load_manifest

MAX_ERRORS = 300
SCORED_RECORD_PROFILES = {"chemical_composition", "mechanical_properties"}
ERROR_CATEGORIES = {
    "missing_record": "ocr",
    "extra_record": "ocr",
    "missing_field": "header",
    "extra_field": "header",
    "missing_inspection": "header",
    "inspection_field_mismatch": "header",
    "missing_classification": "header",
    "classification_field_mismatch": "header",
    "value_mismatch": "normalization",
    "comparator_mismatch": "semantic",
    "unit_mismatch": "semantic",
    "missing_clause": "reference",
    "missing_clause_field": "reference",
    "clause_field_mismatch": "reference",
}
PROPERTY_ALIASES = {"KU1": "KV2", "KU2": "KV2", "KU5": "KV2", "HBW": "HB"}
COUNT_FIELDS = ("record_tp", "record_fp", "record_fn", "field_tp", "field_fp", "field_fn")


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("≤", "<=").replace("≥", ">=")
    text = text.replace("℃", "°C").replace("～", "~")
    text = text.replace("－", "-").replace("—", "-").replace("–", "-")
    text = text.replace("／", "/")
    text = text.replace("*", "")
    text = _strip_latex(text)
    return re.sub(r"\s+", "", text)


def _strip_latex(text: str) -> str:
    text = text.replace("\\%", "%").replace("\\sim", "~")
    text = text.replace("\\leq", "<=").replace("\\geq", ">=")
    text = text.replace("\\times", "x").replace("\\cdot", "·")
    text = text.replace("\\pm", "±").replace("\\mp", "∓")
    text = text.replace("\\ ", "").replace("\\,", "").replace("\\;", "")
    text = re.sub(r"\^\{?\\circ\}?", "°", text)
    text = text.replace("\\circ", "°")
    text = re.sub(r"\\(?:mathrm|text|mathbf|mathit|operatorname)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    return text.replace("{", "").replace("}", "").replace("$", "").replace("^", "")


def condition_key(value: str | None) -> str:
    text = norm_text(value)
    text = (
        text.replace("（", "/")
        .replace("）", "/")
        .replace("(", "/")
        .replace(")", "/")
    )
    parts = [part for part in re.split(r"[/;；、,，]", text) if part]
    normalized: set[str] = set()
    for part in parts:
        part = re.sub(r"mm$", "", part)
        if part in {"0"}:
            part = "O"
        if part:
            normalized.add(part)
    return "|".join(sorted(normalized)) if normalized else ""


def record_key(grade: str | None, grade_level: str | None, condition: str | None) -> tuple[str, str]:
    grade_key = norm_text(grade or grade_level)
    parts = [
        part
        for part in condition_key(condition).split("|")
        if part and part != grade_key
    ]
    return grade_key, "|".join(parts)


def property_key(name: str) -> str:
    return PROPERTY_ALIASES.get(str(name), str(name))


def _normalized_properties(values: dict[str, Any]) -> dict[str, Any]:
    return {property_key(name): value for name, value in values.items()}


def _condition_tokens(key: tuple[str, str]) -> set[str]:
    return {part for part in key[1].split("|") if part}


def condition_match_score(
    gold_key: tuple[str, str], pred_key: tuple[str, str]
) -> int | None:
    """Return overlap size when one condition set contains the other."""
    if gold_key[0] != pred_key[0]:
        return None
    gold_tokens = _condition_tokens(gold_key)
    pred_tokens = _condition_tokens(pred_key)
    if not gold_tokens:
        return 3 if not pred_tokens else 2
    if not pred_tokens:
        return None
    if not (gold_tokens <= pred_tokens or pred_tokens <= gold_tokens):
        return None
    return len(gold_tokens & pred_tokens)


def close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= max(1e-9, abs(float(right)) * 1e-9)


@dataclass
class ValueMatch:
    value_ok: bool
    comparator_ok: bool
    unit_ok: bool

    @property
    def strict(self) -> bool:
        return self.value_ok and self.comparator_ok and self.unit_ok


def compare_value(gold: GoldValue, pred: ExtractedValue) -> ValueMatch:
    if gold.comparator == "text":
        value_ok = norm_text(gold.text or gold.raw) == norm_text(pred.text or pred.raw)
    elif gold.comparator == "range":
        value_ok = close(pred.lower, gold.lower) and close(pred.upper, gold.upper)
    elif gold.comparator == "na":
        value_ok = pred.value is None
    else:
        value_ok = close(pred.value, gold.value)
    comparator_ok = norm_text(pred.comparator) == norm_text(gold.comparator)
    unit_ok = True if not gold.unit else norm_text(pred.unit) == norm_text(gold.unit)
    return ValueMatch(value_ok=value_ok, comparator_ok=comparator_ok, unit_ok=unit_ok)


@dataclass
class DocMetrics:
    doc_id: str
    record_tp: int = 0
    record_fp: int = 0
    record_fn: int = 0
    field_tp: int = 0
    field_fp: int = 0
    field_fn: int = 0
    field_present: int = 0
    value_ok: int = 0
    comparator_mismatch: int = 0
    unit_mismatch: int = 0
    inspection_total: int = 0
    inspection_tp: int = 0
    inspection_field_total: int = 0
    inspection_field_tp: int = 0
    classification_total: int = 0
    classification_tp: int = 0
    classification_field_total: int = 0
    classification_field_tp: int = 0
    clause_total: int = 0
    clause_tp: int = 0
    clause_field_total: int = 0
    clause_field_tp: int = 0
    evidence_total: int = 0
    evidence_missing: int = 0
    coverage_required: int = 0
    coverage_found: int = 0
    predicted_records: int = 0
    condition_relaxed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    error_categories: dict[str, int] = field(default_factory=dict)
    profile_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    table_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    coverage_gaps: list[dict[str, Any]] = field(default_factory=list)

    def add_error(self, **payload: Any) -> None:
        category = payload.get("category") or ERROR_CATEGORIES.get(
            str(payload.get("type")), "other"
        )
        payload["category"] = category
        self.error_categories[category] = self.error_categories.get(category, 0) + 1
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "record_precision": _safe_ratio(self.record_tp, self.record_tp + self.record_fp),
            "record_recall": _safe_ratio(self.record_tp, self.record_tp + self.record_fn),
            "record_f1": _f1(self.record_tp, self.record_fp, self.record_fn),
            "field_precision": _safe_ratio(self.field_tp, self.field_tp + self.field_fp),
            "field_recall": _safe_ratio(self.field_tp, self.field_tp + self.field_fn),
            "field_f1": _f1(self.field_tp, self.field_fp, self.field_fn),
            "value_accuracy": _safe_ratio(self.value_ok, self.field_present),
            "comparator_mismatch": self.comparator_mismatch,
            "unit_mismatch": self.unit_mismatch,
            "inspection_accuracy": _safe_ratio(self.inspection_tp, self.inspection_total),
            "inspection_field_accuracy": _safe_ratio(
                self.inspection_field_tp, self.inspection_field_total
            ),
            "classification_accuracy": _safe_ratio(
                self.classification_tp, self.classification_total
            ),
            "classification_field_accuracy": _safe_ratio(
                self.classification_field_tp, self.classification_field_total
            ),
            "clause_accuracy": _safe_ratio(self.clause_tp, self.clause_total),
            "clause_field_accuracy": _safe_ratio(
                self.clause_field_tp, self.clause_field_total
            ),
            "evidence_rate": (
                _safe_ratio(self.evidence_total - self.evidence_missing, self.evidence_total)
                if self.evidence_total
                else 0.0
            ),
            "hallucination_rate": (
                _safe_ratio(self.evidence_missing, self.evidence_total)
                if self.evidence_total
                else 0.0
            ),
            "coverage_rate": _safe_ratio(self.coverage_found, self.coverage_required),
            "predicted_records": self.predicted_records,
            "condition_relaxed": self.condition_relaxed,
            "counts": {
                "record_tp": self.record_tp,
                "record_fp": self.record_fp,
                "record_fn": self.record_fn,
                "field_tp": self.field_tp,
                "field_fp": self.field_fp,
                "field_fn": self.field_fn,
                "field_present": self.field_present,
                "value_ok": self.value_ok,
                "inspection_total": self.inspection_total,
                "clause_total": self.clause_total,
                "evidence_total": self.evidence_total,
                "evidence_missing": self.evidence_missing,
                "coverage_required": self.coverage_required,
                "coverage_found": self.coverage_found,
                "condition_relaxed": self.condition_relaxed,
            },
            "error_categories": self.error_categories,
            "profile_counts": self.profile_counts,
            "table_counts": self.table_counts,
            "coverage_gaps": self.coverage_gaps,
            "errors": self.errors,
        }


def _safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _count_snapshot(metrics: DocMetrics) -> dict[str, int]:
    return {name: getattr(metrics, name) for name in COUNT_FIELDS}


def _count_delta(before: dict[str, int], metrics: DocMetrics) -> dict[str, int]:
    return {name: getattr(metrics, name) - before[name] for name in COUNT_FIELDS}


def _merge_counts(target: dict[str, int], delta: dict[str, int]) -> None:
    for name, value in delta.items():
        target[name] = target.get(name, 0) + value


def _count_metrics(counts: dict[str, int]) -> dict[str, Any]:
    tp = counts.get("record_tp", 0)
    fp = counts.get("record_fp", 0)
    fn = counts.get("record_fn", 0)
    field_tp = counts.get("field_tp", 0)
    field_fp = counts.get("field_fp", 0)
    field_fn = counts.get("field_fn", 0)
    return {
        "counts": dict(counts),
        "record_f1": _f1(tp, fp, fn),
        "field_f1": _f1(field_tp, field_fp, field_fn),
    }


def _f1(tp: int, fp: int, fn: int) -> float:
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def load_prediction(run_dir: str | Path) -> tuple[DocumentResult, set[str]]:
    base = Path(run_dir)
    result = DocumentResult.model_validate(
        json.loads((base / "result.json").read_text(encoding="utf-8"))
    )
    evidence_ids: set[str] = set()
    evidence_path = base / "evidence.jsonl"
    if evidence_path.exists():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            evidence = Evidence.model_validate(json.loads(line))
            evidence_ids.add(evidence.evidence_id)
    return result, evidence_ids


def evaluate_document(
    gold: GoldDocument,
    result: DocumentResult,
    evidence_ids: set[str],
) -> DocMetrics:
    metrics = DocMetrics(doc_id=gold.doc_id, predicted_records=len(result.records))
    predicted_by_table: dict[str, list[Any]] = {}
    unassigned: list[Any] = []
    for record in result.records:
        if record.source_table_id:
            predicted_by_table.setdefault(record.source_table_id, []).append(record)
        else:
            unassigned.append(record)

    for table in gold.tables:
        if table.profile not in SCORED_RECORD_PROFILES:
            continue
        before = _count_snapshot(metrics)
        candidates = list(predicted_by_table.get(table.table_id, []))
        candidates.extend(unassigned)
        used: set[int] = set()
        gold_keys = set()
        all_gold_keys = {
            record_key(record.grade, record.grade_level, record.condition)
            for record in table.records
        }
        for gold_record in table.records:
            key = record_key(
                gold_record.grade, gold_record.grade_level, gold_record.condition
            )
            gold_keys.add(key)
            match_index = next(
                (
                    index
                    for index, candidate in enumerate(candidates)
                    if index not in used
                    and record_key(
                        candidate.grade, candidate.grade_level, candidate.condition
                    )
                    == key
                ),
                None,
            )
            relaxed = False
            if match_index is None:
                scored: list[tuple[int, int]] = []
                for index, candidate in enumerate(candidates):
                    if index in used:
                        continue
                    candidate_key = record_key(
                        candidate.grade, candidate.grade_level, candidate.condition
                    )
                    if candidate_key in all_gold_keys and candidate_key != key:
                        continue
                    score = condition_match_score(key, candidate_key)
                    if score is not None:
                        scored.append((score, index))
                scored.sort(reverse=True)
                if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                    match_index = scored[0][1]
                    relaxed = True
            if match_index is None:
                metrics.record_fn += 1
                metrics.field_fn += len(gold_record.properties)
                metrics.add_error(
                    type="missing_record",
                    table_id=table.table_id,
                    record_id=gold_record.record_id,
                    key=list(key),
                )
                continue

            used.add(match_index)
            candidate = candidates[match_index]
            metrics.record_tp += 1
            if relaxed:
                metrics.condition_relaxed += 1
            gold_properties = _normalized_properties(gold_record.properties)
            pred_properties = _normalized_properties(candidate.properties)
            for name, gold_value in gold_properties.items():
                pred_value = pred_properties.get(name)
                if pred_value is None:
                    metrics.field_fn += 1
                    metrics.add_error(
                        type="missing_field",
                        table_id=table.table_id,
                        record_id=gold_record.record_id,
                        field=name,
                    )
                    continue
                metrics.field_present += 1
                comparison = compare_value(gold_value, pred_value)
                if comparison.value_ok:
                    metrics.value_ok += 1
                if not comparison.value_ok:
                    metrics.field_fn += 1
                    metrics.add_error(
                        type="value_mismatch",
                        table_id=table.table_id,
                        record_id=gold_record.record_id,
                        field=name,
                        gold={
                            "value": gold_value.value,
                            "lower": gold_value.lower,
                            "upper": gold_value.upper,
                            "text": gold_value.text,
                            "comparator": gold_value.comparator,
                        },
                        pred={
                            "value": pred_value.value,
                            "lower": pred_value.lower,
                            "upper": pred_value.upper,
                            "text": pred_value.text,
                            "comparator": pred_value.comparator,
                        },
                    )
                    continue
                if not comparison.comparator_ok:
                    metrics.comparator_mismatch += 1
                if not comparison.unit_ok:
                    metrics.unit_mismatch += 1
                if comparison.strict:
                    metrics.field_tp += 1
                else:
                    metrics.field_fn += 1
                    metrics.add_error(
                        type=(
                            "unit_mismatch"
                            if not comparison.unit_ok
                            else "comparator_mismatch"
                        ),
                        table_id=table.table_id,
                        record_id=gold_record.record_id,
                        field=name,
                        gold_unit=gold_value.unit,
                        pred_unit=pred_value.unit,
                        gold_comparator=gold_value.comparator,
                        pred_comparator=pred_value.comparator,
                    )

            extra_fields = set(pred_properties) - set(gold_properties)
            if table.scope == "full" and extra_fields:
                metrics.field_fp += len(extra_fields)
                for name in sorted(extra_fields):
                    metrics.add_error(
                        type="extra_field",
                        table_id=table.table_id,
                        record_id=gold_record.record_id,
                        field=name,
                    )

        if table.scope == "full":
            for index, candidate in enumerate(candidates):
                if index in used:
                    continue
                if candidate.source_table_id != table.table_id:
                    continue
                metrics.record_fp += 1
                metrics.field_fp += len(_normalized_properties(candidate.properties))
                metrics.add_error(
                    type="extra_record",
                    table_id=table.table_id,
                    record_id=candidate.record_id,
                )

        delta = _count_delta(before, metrics)
        metrics.table_counts[table.table_id] = delta
        _merge_counts(metrics.profile_counts.setdefault(table.profile, {}), delta)

    _score_inspection(gold, result, metrics)
    _score_classification(gold, result, metrics)
    _score_clauses(gold, result, metrics)
    _score_evidence(result, evidence_ids, metrics)
    _score_coverage(result, metrics)
    return metrics


def _score_inspection(gold: GoldDocument, result: DocumentResult, metrics: DocMetrics) -> None:
    candidates = list(result.inspection_items)
    used: set[int] = set()
    for table in gold.tables:
        for gold_item in table.inspection_items:
            if gold_item.status != "found":
                continue
            metrics.inspection_total += 1
            fields = _inspection_fields(gold_item)
            metrics.inspection_field_total += len(fields)
            matches: list[tuple[int, int]] = []
            for index, candidate in enumerate(candidates):
                if index in used:
                    continue
                if norm_text(candidate.item) != norm_text(gold_item.item):
                    continue
                actual = _inspection_fields(candidate)
                score = sum(
                    1
                    for name, expected in fields.items()
                    if norm_text(actual.get(name)) == norm_text(expected)
                )
                matches.append((score, index))
            if not matches:
                metrics.add_error(
                    type="missing_inspection",
                    table_id=table.table_id,
                    item=gold_item.item,
                )
                continue
            matches.sort(reverse=True)
            match_index = matches[0][1]
            used.add(match_index)
            match = candidates[match_index]
            matched = True
            for name, expected in fields.items():
                actual = _inspection_fields(match).get(name)
                if norm_text(actual) == norm_text(expected):
                    metrics.inspection_field_tp += 1
                else:
                    matched = False
                    metrics.add_error(
                        type="inspection_field_mismatch",
                        item=gold_item.item,
                        field=name,
                        gold=expected,
                        pred=actual,
                    )
            if matched:
                metrics.inspection_tp += 1


def _inspection_fields(item: Any) -> dict[str, str]:
    fields = {
        "sample_location": item.sample_location or "",
        "requirement_clause": item.requirement_clause or "",
        "method_clause": item.method_clause or "",
        "method_standard": item.method_standard or "",
    }
    for key, value in item.quantities.items():
        fields[f"quantity.{key}"] = value
    return fields


def _score_classification(
    gold: GoldDocument, result: DocumentResult, metrics: DocMetrics
) -> None:
    predicted = {
        (norm_text(item.grade), norm_text(item.state)): item
        for item in result.classification_items
    }
    for table in gold.tables:
        for gold_item in table.classification_items:
            if gold_item.status != "found":
                continue
            metrics.classification_total += 1
            key = (norm_text(gold_item.grade), norm_text(gold_item.state))
            match = predicted.get(key)
            fields = {
                "old_grade": gold_item.old_grade or "",
                "old_state": gold_item.old_state or "",
                "meaning": gold_item.meaning or "",
            }
            metrics.classification_field_total += len(fields)
            if match is None:
                metrics.add_error(
                    type="missing_classification",
                    table_id=table.table_id,
                    grade=gold_item.grade,
                    state=gold_item.state,
                )
                continue
            matched = True
            actual_fields = {
                "old_grade": match.old_grade or "",
                "old_state": match.old_state or "",
                "meaning": match.meaning or "",
            }
            for name, expected in fields.items():
                if norm_text(actual_fields[name]) == norm_text(expected):
                    metrics.classification_field_tp += 1
                else:
                    matched = False
                    metrics.add_error(
                        type="classification_field_mismatch",
                        grade=gold_item.grade,
                        field=name,
                        gold=expected,
                        pred=actual_fields[name],
                    )
            if matched:
                metrics.classification_tp += 1


def _score_clauses(gold: GoldDocument, result: DocumentResult, metrics: DocMetrics) -> None:
    predicted = {norm_text(clause.clause_id): clause for clause in result.clauses}
    for clause in gold.clauses:
        if clause.status != "found":
            continue
        metrics.clause_total += 1
        metrics.clause_field_total += len(clause.fields)
        match = predicted.get(norm_text(clause.clause_id))
        if match is None:
            metrics.add_error(type="missing_clause", clause_id=clause.clause_id)
            continue
        matched = True
        for name, gold_value in clause.fields.items():
            pred_value = match.fields.get(name)
            if pred_value is None:
                matched = False
                metrics.add_error(
                    type="missing_clause_field",
                    clause_id=clause.clause_id,
                    field=name,
                )
                continue
            comparison = compare_value(gold_value, pred_value)
            if comparison.strict:
                metrics.clause_field_tp += 1
            else:
                matched = False
                metrics.add_error(
                    type="clause_field_mismatch",
                    clause_id=clause.clause_id,
                    field=name,
                )
        if matched:
            metrics.clause_tp += 1


def _score_evidence(
    result: DocumentResult, evidence_ids: set[str], metrics: DocMetrics
) -> None:
    values: list[ExtractedValue] = []
    for record in result.records:
        values.extend(record.properties.values())
    for clause in result.clauses:
        values.extend(clause.fields.values())
    metrics.evidence_total = len(values)
    metrics.evidence_missing = sum(
        1 for value in values if not value.evidence_id or value.evidence_id not in evidence_ids
    )


def _score_coverage(result: DocumentResult, metrics: DocMetrics) -> None:
    if not result.coverage:
        return
    for item in result.coverage.items:
        if not item.required:
            continue
        metrics.coverage_required += 1
        if item.status in {"found", "not_applicable"}:
            metrics.coverage_found += 1
        else:
            metrics.coverage_gaps.append(
                {
                    "field": item.field,
                    "status": item.status,
                    "reason": item.reason,
                }
            )


def evaluate_goldset(goldset_dir: str | Path, runs_dir: str | Path) -> dict[str, Any]:
    gold_dir = Path(goldset_dir)
    manifest = load_manifest(gold_dir / "manifest.json")
    run_root = Path(runs_dir)
    documents: list[dict[str, Any]] = []
    skipped: list[str] = []
    unannotated_runs: list[str] = []
    for entry in manifest.documents:
        run_dir = run_root / entry.doc_id
        has_run = (run_dir / "result.json").exists()
        if not entry.annotation_file:
            if has_run:
                unannotated_runs.append(entry.doc_id)
            continue
        if not has_run:
            skipped.append(entry.doc_id)
            continue
        gold = load_gold_document(gold_dir / entry.annotation_file)
        result, evidence_ids = load_prediction(run_dir)
        metrics = evaluate_document(gold, result, evidence_ids)
        payload = metrics.to_dict()
        payload.update(
            {
                "source_type": entry.source_type,
                "split": entry.split,
                "doc_type": entry.doc_type,
            }
        )
        documents.append(payload)

    summary = _aggregate(documents)
    return {
        "schema_version": manifest.schema_version,
        "goldset_version": manifest.goldset_version,
        "documents": documents,
        "summary": summary,
        "hard_tables": _hard_table_results(gold_dir, documents),
        "skipped": skipped,
        "unannotated_runs": unannotated_runs,
    }


def _aggregate(documents: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "record_f1",
        "field_f1",
        "value_accuracy",
        "inspection_accuracy",
        "classification_accuracy",
        "clause_accuracy",
        "evidence_rate",
        "coverage_rate",
    )
    summary: dict[str, Any] = {"documents": len(documents)}
    for key in keys:
        values = [doc[key] for doc in documents]
        summary[key] = round(sum(values) / len(values), 4) if values else 0.0
    evidence_total = sum(doc["counts"]["evidence_total"] for doc in documents)
    evidence_missing = sum(doc["counts"]["evidence_missing"] for doc in documents)
    summary["evidence_rate"] = (
        round((evidence_total - evidence_missing) / evidence_total, 4)
        if evidence_total
        else 1.0
    )
    coverage_required = sum(doc["counts"]["coverage_required"] for doc in documents)
    coverage_found = sum(doc["counts"]["coverage_found"] for doc in documents)
    summary["coverage_rate"] = (
        round(coverage_found / coverage_required, 4) if coverage_required else 0.0
    )
    summary["field_fp"] = sum(doc["counts"]["field_fp"] for doc in documents)
    summary["field_fn"] = sum(doc["counts"]["field_fn"] for doc in documents)
    summary["comparator_mismatch"] = sum(
        doc["comparator_mismatch"] for doc in documents
    )
    summary["unit_mismatch"] = sum(doc["unit_mismatch"] for doc in documents)
    summary["condition_relaxed"] = sum(
        doc.get("condition_relaxed", 0) for doc in documents
    )
    summary["error_categories"] = _sum_categories(documents)
    summary["coverage_gaps"] = sum(len(doc.get("coverage_gaps", [])) for doc in documents)
    summary["error_categories"]["coverage"] = summary["coverage_gaps"]
    summary["by_profile"] = _profile_summary(documents)
    for field in ("source_type", "split", "doc_type"):
        summary[f"by_{field}"] = _group_summary(documents, field)
    return summary


def _sum_categories(documents: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for doc in documents:
        for name, value in doc.get("error_categories", {}).items():
            totals[name] = totals.get(name, 0) + value
    return totals


def _profile_summary(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, int]] = {}
    for doc in documents:
        for profile, counts in doc.get("profile_counts", {}).items():
            _merge_counts(merged.setdefault(profile, {}), counts)
    return {profile: _count_metrics(counts) for profile, counts in sorted(merged.items())}


def _group_summary(documents: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for doc in documents:
        groups.setdefault(str(doc.get(field, "unknown")), []).append(doc)
    output: dict[str, dict[str, Any]] = {}
    for name, group in sorted(groups.items()):
        metrics = {
            key: round(sum(doc[key] for doc in group) / len(group), 4)
            for key in (
                "record_f1",
                "field_f1",
                "value_accuracy",
                "evidence_rate",
                "coverage_rate",
            )
        }
        metrics["documents"] = len(group)
        output[name] = metrics
    return output


def _hard_table_results(
    gold_dir: Path, documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    path = gold_dir / "hard_tables.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("tables", payload) if isinstance(payload, dict) else payload
    by_doc = {doc["doc_id"]: doc for doc in documents}
    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or "doc_id" not in entry or "table_id" not in entry:
            continue
        doc = by_doc.get(entry["doc_id"])
        counts = (doc or {}).get("table_counts", {}).get(entry["table_id"], {})
        metrics = _count_metrics(counts)
        results.append(
            {
                "doc_id": entry["doc_id"],
                "table_id": entry["table_id"],
                "reason": entry.get("reason", ""),
                "status": entry.get("status", ""),
                "annotated": bool(doc),
                "record_f1": metrics["record_f1"],
                "field_f1": metrics["field_f1"],
                "counts": counts,
            }
        )
    return results


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# 黄金集评测报告",
        "",
        f"- goldset：{payload['goldset_version']} / schema {payload['schema_version']}",
        f"- 文档数：{summary['documents']}",
        f"- 跳过：{', '.join(payload['skipped']) if payload['skipped'] else '无'}",
        f"- 已跑未标注：{', '.join(payload.get('unannotated_runs', [])) or '无'}",
        "",
        "## 汇总",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| Record F1 | {summary['record_f1']} |",
        f"| Field F1 | {summary['field_f1']} |",
        f"| Value accuracy | {summary['value_accuracy']} |",
        f"| Comparator mismatch | {summary['comparator_mismatch']} |",
        f"| Unit mismatch | {summary['unit_mismatch']} |",
        f"| Condition relaxed | {summary.get('condition_relaxed', 0)} |",
        f"| Inspection accuracy | {summary['inspection_accuracy']} |",
        f"| Classification accuracy | {summary['classification_accuracy']} |",
        f"| Clause accuracy | {summary['clause_accuracy']} |",
        f"| Evidence rate | {summary['evidence_rate']} |",
        f"| Coverage rate | {summary['coverage_rate']} |",
        "",
        "## 分文档",
        "",
        "| 文档 | Record F1 | Field F1 | Value acc | Evidence | Coverage |",
        "|---|---|---|---|---|---|",
    ]
    for doc in payload["documents"]:
        lines.append(
            f"| {doc['doc_id']} | {doc['record_f1']} | {doc['field_f1']} | "
            f"{doc['value_accuracy']} | {doc['evidence_rate']} | {doc['coverage_rate']} |"
        )

    lines.extend(["", "## 分表型", "", "| 表型 | Record F1 | Field F1 | 记录 TP/FP/FN | 字段 TP/FP/FN |", "|---|---|---|---|---|"])
    for profile, data in summary.get("by_profile", {}).items():
        counts = data["counts"]
        lines.append(
            f"| {profile} | {data['record_f1']} | {data['field_f1']} | "
            f"{counts.get('record_tp', 0)}/{counts.get('record_fp', 0)}/{counts.get('record_fn', 0)} | "
            f"{counts.get('field_tp', 0)}/{counts.get('field_fp', 0)}/{counts.get('field_fn', 0)} |"
        )

    for field, title in (
        ("source_type", "分来源类型"),
        ("split", "分拆分"),
        ("doc_type", "分文档类型"),
    ):
        lines.extend(["", f"## {title}", "", "| 分组 | 文档数 | Record F1 | Field F1 | Value acc | Evidence | Coverage |", "|---|---|---|---|---|---|---|"])
        for name, data in summary.get(f"by_{field}", {}).items():
            lines.append(
                f"| {name} | {data['documents']} | {data['record_f1']} | {data['field_f1']} | "
                f"{data['value_accuracy']} | {data['evidence_rate']} | {data['coverage_rate']} |"
            )

    lines.extend(["", "## 错误分类", "", "| 分类 | 数量 |", "|---|---|"])
    categories = summary.get("error_categories", {})
    if categories:
        for name, count in sorted(categories.items()):
            lines.append(f"| {name} | {count} |")
    else:
        lines.append("| 无 | 0 |")

    gaps = [
        (doc["doc_id"], gap)
        for doc in payload["documents"]
        for gap in doc.get("coverage_gaps", [])
    ]
    lines.extend(["", "## 覆盖缺口", "", "| 文档 | 字段 | 状态 | 原因 |", "|---|---|---|---|"])
    if gaps:
        for doc_id, gap in gaps[:100]:
            lines.append(
                f"| {doc_id} | {gap['field']} | {gap['status']} | {gap.get('reason') or ''} |"
            )
    else:
        lines.append("| 无 | | | |")

    lines.extend(["", "## 困难表", "", "| 文档 | 表 | 状态 | Record F1 | Field F1 | 原因 |", "|---|---|---|---|---|---|"])
    hard_tables = payload.get("hard_tables", [])
    if hard_tables:
        for item in hard_tables:
            lines.append(
                f"| {item['doc_id']} | {item['table_id']} | {item['status']} | "
                f"{item['record_f1']} | {item['field_f1']} | {item['reason']} |"
            )
    else:
        lines.append("| 无 | | | | | |")

    regression = payload.get("regression")
    if regression:
        lines.extend(
            [
                "",
                "## 回归对比",
                "",
                f"- 基线：{regression.get('baseline_label') or 'unknown'}",
                f"- 容差：{regression.get('tolerance')}",
                f"- 结论：{'通过' if regression.get('passed') else '存在回退'}",
                "",
                "| 指标 | 基线 | 当前 | 变化 |",
                "|---|---|---|---|",
            ]
        )
        for name, item in regression.get("items", {}).items():
            lines.append(
                f"| {name} | {item['baseline']} | {item['current']} | {item['delta']} |"
            )
        if regression.get("regressions"):
            lines.extend(["", "回退项："])
            for item in regression["regressions"]:
                lines.append(
                    f"- {item['metric']}: {item['baseline']} → {item['current']} ({item['delta']})"
                )

    lines.extend(["", "## 错误样例", ""])
    for doc in payload["documents"]:
        if not doc["errors"]:
            continue
        lines.append(f"### {doc['doc_id']}")
        lines.append("")
        lines.append("| 类型 | 表/条款 | 记录/字段 | 详情 |")
        lines.append("|---|---|---|---|")
        for error in doc["errors"][:20]:
            location = error.get("table_id") or error.get("clause_id") or ""
            record = error.get("record_id") or error.get("item") or ""
            field = error.get("field") or ""
            target = " / ".join(part for part in (record, field) if part)
            detail = {
                key: value
                for key, value in error.items()
                if key not in {"type", "table_id", "clause_id", "record_id", "field", "item"}
            }
            lines.append(
                f"| {error['type']} | {location} | {target} | "
                f"{json.dumps(detail, ensure_ascii=False) if detail else ''} |"
            )
        lines.append("")
    return "\n".join(lines)


def run_evaluation(
    goldset_dir: str | Path,
    runs_dir: str | Path,
    out_dir: str | Path,
    baseline_path: str | Path | None = None,
    save_baseline: str | Path | None = None,
    baseline_label: str = "m1",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = evaluate_goldset(goldset_dir, runs_dir)
    if baseline_path:
        from .regression import compare_regression, load_regression

        payload["regression"] = compare_regression(
            payload, load_regression(baseline_path)
        )
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "eval.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (target / "eval.md").write_text(render_markdown(payload) + "\n", encoding="utf-8")
    if save_baseline:
        from .regression import build_regression, write_regression

        write_regression(
            build_regression(payload, label=baseline_label, metadata=metadata),
            save_baseline,
        )
    return payload
