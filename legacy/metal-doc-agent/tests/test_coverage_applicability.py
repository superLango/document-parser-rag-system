"""Coverage applicability: not-applicable only when profiles are confident."""

from __future__ import annotations

import unittest

from metal_doc_agent.contracts import DocumentMeta, ExtractedValue, Record, TableGrid
from metal_doc_agent.coverage.plan import build_coverage


def _table(profile: str, table_id: str = "T1") -> TableGrid:
    return TableGrid(
        table_id=table_id,
        page_no=1,
        n_rows=2,
        n_cols=2,
        header_rows=1,
        rows=[["牌号", "Rm"], ["2A14", "430"]],
        header_paths=[["牌号"], ["Rm"]],
        profile=profile,
    )


def _document() -> DocumentMeta:
    return DocumentMeta(doc_id="d1", source_path="x.md", file_name="x.md", standard_no="GB/T 1")


def _records() -> list[Record]:
    return [
        Record(
            record_id="2A14",
            grade="2A14",
            properties={
                "Rm": ExtractedValue(raw="430", value=430.0, unit="MPa", evidence_id="")
            },
        )
    ]


class ApplicabilityTests(unittest.TestCase):
    def test_mechanical_only_document_marks_chemistry_not_applicable(self) -> None:
        plan = build_coverage(_document(), _records(), [_table("mechanical_properties")], [])
        items = {item.field: item for item in plan.items}
        self.assertEqual(items["records.chemical_composition"].status, "not_applicable")
        self.assertEqual(items["records.mechanical_properties"].status, "found")

    def test_unknown_table_keeps_chemistry_missing(self) -> None:
        plan = build_coverage(
            _document(),
            _records(),
            [_table("mechanical_properties"), _table("unknown", "T2")],
            [],
        )
        items = {item.field: item for item in plan.items}
        self.assertEqual(items["records.chemical_composition"].status, "missing")

    def test_no_tables_keeps_missing(self) -> None:
        plan = build_coverage(_document(), _records(), [], [])
        items = {item.field: item for item in plan.items}
        self.assertEqual(items["records.chemical_composition"].status, "missing")


if __name__ == "__main__":
    unittest.main()
