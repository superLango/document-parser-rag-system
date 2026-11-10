"""Schema v0, golden set and evaluation tests."""

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
from metal_doc_agent.goldset import (
    AnnotationMeta,
    GoldDocument,
    GoldEvidence,
    GoldRecord,
    GoldTable,
    GoldValue,
    load_manifest,
    validate_manifest,
)
from metal_doc_agent.schema_export import export_schemas

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDSET_DIR = PROJECT_ROOT / "goldset" / "v0"


class SchemaV0Tests(unittest.TestCase):
    def test_schema_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            written = export_schemas(tmp)
            self.assertIn("DocumentResult", written)
            self.assertIn("Record", written)
            self.assertIn("GoldDocument", written)
            index = json.loads((Path(tmp) / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], "0.1.0")
            record_schema = json.loads(
                (Path(tmp) / "Record.schema.json").read_text(encoding="utf-8")
            )
            self.assertIn("source_table_id", record_schema["properties"])
            self.assertIn("facets", record_schema["properties"])


class GoldsetTests(unittest.TestCase):
    def test_manifest_and_annotations_validate(self) -> None:
        manifest = load_manifest(GOLDSET_DIR / "manifest.json")
        self.assertEqual(len(manifest.documents), 20)
        self.assertEqual(sum(1 for d in manifest.documents if d.annotation_file), 20)
        self.assertGreaterEqual(len({d.doc_type for d in manifest.documents}), 4)
        profiles = {p for d in manifest.documents for p in d.profiles}
        for required in ("chemical_composition", "mechanical_properties", "inspection"):
            self.assertIn(required, profiles)
        issues = validate_manifest(manifest, GOLDSET_DIR)
        self.assertEqual(issues, [], "\n".join(issues))

    def test_mini_goldset_counts(self) -> None:
        expected = {
            "qdu302_2015": (3, 3, 7),
            "gbt40303_2021": (3, 3, 16),
            "gjb2057a_2018": (3, 7, 11),
        }
        for doc_id, (tables, records, inspection) in expected.items():
            gold = GoldDocument.model_validate(
                json.loads(
                    (GOLDSET_DIR / "docs" / f"{doc_id}.json").read_text(encoding="utf-8")
                )
            )
            self.assertEqual(len(gold.tables), tables, doc_id)
            self.assertEqual(
                sum(len(table.records) for table in gold.tables), records, doc_id
            )
            self.assertEqual(
                sum(len(table.inspection_items) for table in gold.tables),
                inspection,
                doc_id,
            )


def _gold_document() -> GoldDocument:
    evidence = GoldEvidence(page_no=5, table_id="T1", row=0, col=1, quote="430")
    return GoldDocument(
        doc_id="unit-test",
        standard_no="TEST 1-2026",
        annotation=AnnotationMeta(status="draft"),
        tables=[
            GoldTable(
                table_id="T1",
                page_no=5,
                profile="mechanical_properties",
                scope="full",
                records=[
                    GoldRecord(
                        record_id="rec-test",
                        grade="2A14",
                        condition="T6 / 切向",
                        properties={
                            "Rm": GoldValue(
                                raw="430",
                                value=430.0,
                                unit="MPa",
                                comparator="min",
                                evidence=evidence,
                            )
                        },
                    )
                ],
            )
        ],
    )


def _result(comparator: str = "min") -> DocumentResult:
    return DocumentResult(
        document=DocumentMeta(
            doc_id="unit-test", source_path="unit.md", file_name="unit.md"
        ),
        records=[
            Record(
                record_id="pred-test",
                source_table_id="T1",
                grade="2A14",
                condition="T6 / 切向",
                properties={
                    "Rm": ExtractedValue(
                        raw="430",
                        value=430.0,
                        unit="MPa",
                        comparator=comparator,
                        evidence_id="ev:unit-test:T1:r0:c1",
                    )
                },
            )
        ],
    )


class EvalMetricTests(unittest.TestCase):
    def test_perfect_match(self) -> None:
        metrics = evaluate_document(
            _gold_document(), _result(), {"ev:unit-test:T1:r0:c1"}
        ).to_dict()
        self.assertEqual(metrics["record_f1"], 1.0)
        self.assertEqual(metrics["field_f1"], 1.0)
        self.assertEqual(metrics["value_accuracy"], 1.0)
        self.assertEqual(metrics["evidence_rate"], 1.0)

    def test_missing_prediction(self) -> None:
        empty = DocumentResult(
            document=DocumentMeta(
                doc_id="unit-test", source_path="unit.md", file_name="unit.md"
            )
        )
        metrics = evaluate_document(_gold_document(), empty, set()).to_dict()
        self.assertEqual(metrics["record_f1"], 0.0)
        self.assertEqual(metrics["field_f1"], 0.0)
        self.assertEqual(metrics["evidence_rate"], 0.0)
        self.assertEqual(metrics["errors"][0]["type"], "missing_record")

    def test_comparator_mismatch_is_field_error(self) -> None:
        metrics = evaluate_document(
            _gold_document(), _result("eq"), {"ev:unit-test:T1:r0:c1"}
        ).to_dict()
        self.assertEqual(metrics["field_f1"], 0.0)
        self.assertEqual(metrics["value_accuracy"], 1.0)
        self.assertEqual(metrics["comparator_mismatch"], 1)
        self.assertEqual(metrics["errors"][0]["type"], "comparator_mismatch")


if __name__ == "__main__":
    unittest.main()
