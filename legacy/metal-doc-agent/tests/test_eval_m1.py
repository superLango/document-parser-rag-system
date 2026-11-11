"""M1-S7 annotation review, error taxonomy and regression tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.contracts import (
    DocumentMeta,
    DocumentResult,
    ExtractedValue,
    Record,
)
from metal_doc_agent.eval.metrics import evaluate_document
from metal_doc_agent.eval.regression import build_regression, compare_regression
from metal_doc_agent.goldset import (
    AnnotationMeta,
    GoldDocument,
    GoldEvidence,
    GoldRecord,
    GoldTable,
    GoldValue,
)
from metal_doc_agent.goldset_review import review_annotations


def _gold(unit: str = "MPa", comparator: str = "min") -> GoldDocument:
    return GoldDocument(
        doc_id="review-doc",
        annotation=AnnotationMeta(status="draft", annotator="A"),
        tables=[
            GoldTable(
                table_id="T1",
                page_no=2,
                profile="mechanical_properties",
                records=[
                    GoldRecord(
                        record_id="rec-1",
                        grade="2A14",
                        condition="T6 / 切向",
                        properties={
                            "Rm": GoldValue(
                                raw="430",
                                value=430.0,
                                unit=unit,
                                comparator=comparator,
                                evidence=GoldEvidence(
                                    page_no=2, table_id="T1", row=1, col=2, quote="430"
                                ),
                            )
                        },
                    )
                ],
            )
        ],
    )


def _write(path: Path, doc: GoldDocument) -> None:
    path.write_text(
        json.dumps(doc.model_dump(), ensure_ascii=False), encoding="utf-8"
    )


class AnnotationReviewTests(unittest.TestCase):
    def test_identical_annotations_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            _write(a, _gold())
            _write(b, _gold())
            review = review_annotations(a, b)
            self.assertTrue(review.passed)
            self.assertEqual(review.metrics["record_key_agreement"], 1.0)
            self.assertEqual(review.metrics["cell_value_agreement"], 1.0)
            self.assertEqual(review.metrics["comparator_unit_agreement"], 1.0)

    def test_unit_mismatch_fails_strict_agreement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            _write(a, _gold())
            _write(b, _gold(unit="MPa!"))
            review = review_annotations(a, b)
            self.assertFalse(review.passed)
            self.assertEqual(review.metrics["cell_value_agreement"], 1.0)
            self.assertEqual(review.metrics["comparator_unit_agreement"], 0.0)
            self.assertEqual(review.value_diffs[0]["field"], "Rm")

    def test_missing_record_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            _write(a, _gold())
            empty = _gold()
            empty.tables[0].records = []
            _write(b, empty)
            review = review_annotations(a, b)
            self.assertEqual(review.counts["record_keys_total"], 1)
            self.assertEqual(review.counts["record_keys_match"], 0)
            self.assertFalse(review.passed)


class ErrorTaxonomyTests(unittest.TestCase):
    def _result(self, comparator: str) -> DocumentResult:
        return DocumentResult(
            document=DocumentMeta(
                doc_id="review-doc", source_path="x.md", file_name="x.md"
            ),
            records=[
                Record(
                    record_id="pred-1",
                    source_table_id="T1",
                    grade="2A14",
                    condition="T6 / 切向",
                    properties={
                        "Rm": ExtractedValue(
                            raw="430",
                            value=430.0,
                            unit="MPa",
                            comparator=comparator,
                            evidence_id="ev:review-doc:T1:r1:c2",
                        )
                    },
                )
            ],
        )

    def test_comparator_error_is_semantic_and_profile_is_counted(self) -> None:
        metrics = evaluate_document(
            _gold(), self._result("eq"), {"ev:review-doc:T1:r1:c2"}
        ).to_dict()
        self.assertEqual(metrics["error_categories"], {"semantic": 1})
        self.assertEqual(metrics["profile_counts"]["mechanical_properties"]["field_fn"], 1)
        self.assertEqual(metrics["table_counts"]["T1"]["field_fn"], 1)
        self.assertEqual(metrics["errors"][0]["category"], "semantic")

    def test_perfect_prediction_has_no_errors(self) -> None:
        metrics = evaluate_document(
            _gold(), self._result("min"), {"ev:review-doc:T1:r1:c2"}
        ).to_dict()
        self.assertEqual(metrics["field_f1"], 1.0)
        self.assertEqual(metrics["error_categories"], {})

    def test_condition_subset_is_compatible(self) -> None:
        gold = _gold()
        gold.tables[0].records[0].condition = (
            "固溶:1010~1150°C / 水冷 / 试样毛坯25 / 方向未规定"
        )
        result = self._result("min")
        result.records[0].condition = "试样毛坯25 / 固溶:1010~1150°C / 水冷"
        metrics = evaluate_document(
            gold, result, {"ev:review-doc:T1:r1:c2"}
        ).to_dict()
        self.assertEqual(metrics["record_f1"], 1.0)
        self.assertEqual(metrics["condition_relaxed"], 1)

    def test_impact_and_hardness_aliases_match(self) -> None:
        gold = _gold()
        gold.tables[0].records[0].properties = {
            "KU2": GoldValue(
                raw="98",
                value=98.0,
                unit="J",
                comparator="min",
                evidence=GoldEvidence(
                    page_no=2, table_id="T1", row=1, col=2, quote="98"
                ),
            ),
            "HBW": GoldValue(
                raw="200",
                value=200.0,
                unit="HBW",
                comparator="eq",
                evidence=GoldEvidence(
                    page_no=2, table_id="T1", row=1, col=3, quote="200"
                ),
            ),
        }
        result = self._result("min")
        result.records[0].properties = {
            "KV2": ExtractedValue(
                raw="98",
                value=98.0,
                unit="J",
                comparator="min",
                evidence_id="ev:review-doc:T1:r1:c2",
            ),
            "HB": ExtractedValue(
                raw="200",
                value=200.0,
                unit="HBW",
                comparator="eq",
                evidence_id="ev:review-doc:T1:r1:c3",
            ),
        }
        metrics = evaluate_document(
            gold, result, {"ev:review-doc:T1:r1:c2", "ev:review-doc:T1:r1:c3"}
        ).to_dict()
        self.assertEqual(metrics["field_f1"], 1.0)


class RegressionTests(unittest.TestCase):
    def test_regression_detects_drop_and_improvement(self) -> None:
        baseline = build_regression(
            {
                "schema_version": "0.1.0",
                "goldset_version": "v0",
                "summary": {"record_f1": 0.9, "field_f1": 0.8},
                "documents": [
                    {"doc_id": "a", "record_f1": 0.9, "field_f1": 0.8}
                ],
            },
            label="v1",
        )
        current = {
            "summary": {"record_f1": 0.85, "field_f1": 0.82},
            "documents": [
                {"doc_id": "a", "record_f1": 0.84, "field_f1": 0.82}
            ],
        }
        comparison = compare_regression(current, baseline)
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["regressions"][0]["metric"], "record_f1")
        self.assertEqual(comparison["improvements"][0]["metric"], "field_f1")
        self.assertEqual(comparison["doc_regressions"][0]["doc_id"], "a")


if __name__ == "__main__":
    unittest.main()
