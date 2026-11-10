"""M4 review: events, feedback, risk, silent-error audit and metrics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.contracts import (
    DocumentMeta,
    DocumentResult,
    Evidence,
    ExtractedValue,
    Record,
)
from metal_doc_agent.review import (
    FeedbackStore,
    ReviewEvent,
    apply_events,
    audit_document,
    diff_records,
    field_path_for,
    field_risks,
    parse_field_path,
    review_metrics,
    risk_summary,
    summarize_audits,
    summarize_events,
)


def _result() -> DocumentResult:
    records = [
        Record(
            record_id="2A14",
            grade="2A14",
            properties={
                "Rm": ExtractedValue(
                    raw="430",
                    value=430.0,
                    unit="MPa",
                    comparator="min",
                    evidence_id="ev:T1:r1:c1",
                ),
                "A": ExtractedValue(
                    raw="10",
                    value=10.0,
                    unit="%",
                    evidence_id="ev:T1:r1:c2",
                ),
            },
        ),
        Record(
            record_id="5A06",
            grade="5A06",
            properties={
                "Rm": ExtractedValue(
                    raw="250",
                    value=250.0,
                    unit="MPa",
                    evidence_id="",
                )
            },
        ),
    ]
    return DocumentResult(
        document=DocumentMeta(
            doc_id="doc1",
            source_path="x.md",
            file_name="x.md",
        ),
        records=records,
    )


def _evidence() -> list[Evidence]:
    return [
        Evidence(evidence_id="ev:T1:r1:c1", page_no=1, table_id="T1", row=1, col=1, quote="430"),
        Evidence(evidence_id="ev:T1:r1:c2", page_no=1, table_id="T1", row=1, col=2, quote="10"),
    ]


class FieldPathTests(unittest.TestCase):
    def test_parse_both_forms(self) -> None:
        self.assertEqual(parse_field_path(field_path_for("2A14", "Rm")), ("2A14", "Rm"))
        self.assertEqual(parse_field_path("records[0].properties.Rm"), ("0", "Rm"))
        self.assertIsNone(parse_field_path("records.Rm"))


class EventTests(unittest.TestCase):
    def test_edit_requires_value_and_review_events_validate(self) -> None:
        with self.assertRaises(ValueError):
            ReviewEvent(
                doc_id="d",
                field_path="records.2A14.properties.Rm",
                action="edit",
                old_value={"value": 430},
                reviewer="u1",
                reason="单位换算",
            )
        event = ReviewEvent(
            doc_id="d",
            field_path="records.2A14.properties.Rm",
            action="edit",
            old_value={"value": 430},
            new_value={"value": 420, "unit": "MPa"},
            reviewer="u1",
            reason="表头为不小于",
        )
        self.assertEqual(event.action, "edit")

    def test_reject_requires_reason(self) -> None:
        with self.assertRaises(ValueError):
            ReviewEvent(
                doc_id="d",
                field_path="records.2A14.properties.Rm",
                action="reject",
                reviewer="u1",
            )

    def test_feedback_store_only_takes_changes_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FeedbackStore(tmp)
            accept = ReviewEvent(
                doc_id="d",
                field_path="records.2A14.properties.Rm",
                action="accept",
                reviewer="u1",
            )
            edit = ReviewEvent(
                doc_id="d",
                field_path="records.2A14.properties.Rm",
                action="edit",
                old_value={"value": 430},
                new_value={"value": 420},
                reviewer="u1",
                reason="复核",
            )
            self.assertFalse(store.append(accept))
            self.assertTrue(store.append(edit))
            self.assertEqual(len(store.list()), 1)
            self.assertTrue(store.path.exists())


class ApplyAndDiffTests(unittest.TestCase):
    def _events(self) -> list[ReviewEvent]:
        return [
            ReviewEvent(
                doc_id="doc1",
                field_path="records.2A14.properties.Rm",
                action="edit",
                old_value={"value": 430},
                new_value={"value": 420, "unit": "MPa"},
                reviewer="u1",
                reason="原文为不小于 420",
            ),
            ReviewEvent(
                doc_id="doc1",
                field_path="records.5A06.properties.Rm",
                action="reject",
                reviewer="u2",
                reason="OCR 误读",
            ),
        ]

    def test_apply_overlays_edit_and_reject(self) -> None:
        machine = [record.model_dump(mode="json") for record in _result().records]
        applied = apply_events(machine, self._events())
        self.assertEqual(applied[0]["properties"]["Rm"]["value"], 420)
        self.assertEqual(applied[0]["properties"]["Rm"]["reviewed"], "edit")
        self.assertEqual(applied[1]["properties"]["Rm"]["reviewed"], "reject")
        self.assertEqual(applied[1]["properties"]["Rm"]["value"], 250.0)

    def test_diff_keeps_machine_value(self) -> None:
        machine = [record.model_dump(mode="json") for record in _result().records]
        diffs = diff_records(machine, self._events())
        first = next(item for item in diffs if item["property"] == "Rm" and item["record_id"] == "2A14")
        self.assertEqual(first["machine"]["value"], 430)
        self.assertEqual(first["human"]["value"], 420)
        self.assertTrue(first["changed"])
        self.assertEqual(first["reason"], "原文为不小于 420")


class RiskTests(unittest.TestCase):
    def test_missing_evidence_is_high_and_high_risk_property_is_medium(self) -> None:
        risks = field_risks(_result(), _evidence())
        by_path = {item.field_path: item for item in risks}
        self.assertEqual(
            by_path["records.5A06.properties.Rm"].level, "high"
        )
        self.assertIn("missing_evidence_id", by_path["records.5A06.properties.Rm"].reasons)
        self.assertEqual(by_path["records.2A14.properties.Rm"].level, "medium")
        self.assertEqual(by_path["records.2A14.properties.A"].level, "low")
        self.assertEqual(by_path["records.2A14.properties.Rm"].evidence_id, "ev:T1:r1:c1")
        self.assertEqual(by_path["records.2A14.properties.Rm"].page_no, 1)
        summary = risk_summary(_result(), _evidence())
        self.assertEqual(summary["level"], "high")
        self.assertEqual(summary["counts"]["high"], 1)

    def test_routine_element_limit_stays_low(self) -> None:
        result = _result()
        result.records[0].properties["C"] = ExtractedValue(
            raw="≤0.25",
            value=0.25,
            unit="%",
            comparator="max",
            evidence_id="ev:T1:r1:c1",
        )
        result.records[0].properties["HB"] = ExtractedValue(
            raw="≥180",
            value=180.0,
            unit="HBW",
            comparator="min",
            evidence_id="ev:T1:r1:c1",
        )
        risks = field_risks(result, _evidence())
        by_path = {item.field_path: item for item in risks}
        self.assertEqual(by_path["records.2A14.properties.C"].level, "low")
        self.assertEqual(by_path["records.2A14.properties.HB"].level, "medium")
        self.assertEqual(by_path["records.2A14.properties.Rm"].level, "medium")


class SilentErrorTests(unittest.TestCase):
    def test_detects_missing_and_mismatched_evidence(self) -> None:
        result = _result()
        findings = audit_document(result, _evidence()).findings
        codes = {item.code for item in findings}
        self.assertIn("MISSING_EVIDENCE", codes)
        summary = summarize_audits([audit_document(result, _evidence())])
        self.assertEqual(summary["silent_errors"], len(findings))
        self.assertGreaterEqual(summary["documents_with_errors"], 1)

    def test_value_quote_mismatch_is_flagged(self) -> None:
        result = _result()
        result.records[0].properties["Rm"].value = 999.0
        findings = audit_document(result, _evidence()).findings
        self.assertIn("VALUE_QUOTE_MISMATCH", {item.code for item in findings})

    def test_unit_required_for_mechanical_value(self) -> None:
        result = _result()
        result.records[0].properties["Rm"].unit = None
        findings = audit_document(result, _evidence()).findings
        self.assertIn("UNIT_MISSING", {item.code for item in findings})


class MetricTests(unittest.TestCase):
    def test_summary_and_first_pass(self) -> None:
        events = ApplyAndDiffTests()._events()
        summary = summarize_events(events)
        self.assertEqual(summary["actions"], {"accept": 0, "edit": 1, "reject": 1})
        metrics = review_metrics(
            events, documents_confirmed=2, documents_with_changes=1
        )
        self.assertEqual(metrics["first_pass_rate"], 0.5)
        self.assertIsNone(metrics["human_minutes"])


if __name__ == "__main__":
    unittest.main()
