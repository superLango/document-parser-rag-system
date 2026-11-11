"""L0–L2 validation tests and normalization edge cases."""

from __future__ import annotations

import unittest

from metal_doc_agent.contracts import (
    CoveragePlan,
    DocumentMeta,
    Evidence,
    ExtractedValue,
    Page,
    Record,
    TableGrid,
)
from metal_doc_agent.ingest import (
    apply_page_identity,
    parse_heading_title,
    parse_standard_no,
)
from metal_doc_agent.tablegrid.normalize import (
    clean_text,
    normalize_value,
    parse_unit,
)
from metal_doc_agent.validation.checks import validate


def document() -> DocumentMeta:
    return DocumentMeta(
        doc_id="doc",
        source_path="doc.md",
        file_name="doc.md",
        standard_no="GB/T 1-2020",
    )


def table(field: str = "Rm", cell: str = "430") -> TableGrid:
    return TableGrid(
        table_id="T1",
        page_no=1,
        n_rows=2,
        n_cols=2,
        rows=[["牌号", field], ["2A14", cell]],
        header_paths=[["牌号"], [field]],
    )


def record(value: ExtractedValue) -> Record:
    return Record(
        record_id="rec-1",
        source_table_id="T1",
        grade="2A14",
        properties={"Rm": value},
    )


def evidence(quote: str = "430", table_id: str = "T1") -> Evidence:
    return Evidence(
        evidence_id=f"ev:doc:{table_id}:r1:c1",
        page_no=1,
        table_id=table_id,
        row=1,
        col=1,
        quote=quote,
    )


def value(**kwargs) -> ExtractedValue:
    defaults = dict(
        raw="430",
        value=430.0,
        unit="MPa",
        comparator="min",
        evidence_id="ev:doc:T1:r1:c1",
    )
    defaults.update(kwargs)
    return ExtractedValue(**defaults)


class ValidationTests(unittest.TestCase):
    def test_valid_record_passes(self) -> None:
        audit = validate(
            document(),
            [record(value())],
            [evidence()],
            CoveragePlan(),
            tables=[table()],
        )
        self.assertEqual(audit.status, "pass")
        self.assertEqual(audit.issues, [])

    def test_quote_mismatch_is_error(self) -> None:
        audit = validate(
            document(),
            [record(value())],
            [evidence("431")],
            CoveragePlan(),
            tables=[table()],
        )
        self.assertEqual(audit.status, "fail")
        self.assertIn("EVIDENCE_QUOTE_MISMATCH", {issue.code for issue in audit.issues})

    def test_missing_table_is_error(self) -> None:
        audit = validate(
            document(),
            [record(value(evidence_id="ev:doc:T2:r1:c1"))],
            [evidence(table_id="T2")],
            CoveragePlan(),
            tables=[table()],
        )
        self.assertEqual(audit.status, "fail")
        self.assertIn("EVIDENCE_TABLE_NOT_FOUND", {issue.code for issue in audit.issues})

    def test_comparator_value_missing_is_l0_error(self) -> None:
        item = value(raw="", value=None)
        audit = validate(
            document(),
            [record(item)],
            [evidence("")],
            CoveragePlan(),
            tables=[table(cell="")],
        )
        codes = {issue.code for issue in audit.issues}
        self.assertIn("MISSING_RAW", codes)
        self.assertIn("COMPARATOR_VALUE_MISSING", codes)
        self.assertEqual(audit.status, "fail")

    def test_chemical_range_out_of_range(self) -> None:
        item = value(
            raw="0~150",
            value=None,
            comparator="range",
            lower=0.0,
            upper=150.0,
            unit="%",
        )
        audit = validate(
            document(),
            [
                Record(
                    record_id="rec-1",
                    source_table_id="T1",
                    grade="2A14",
                    properties={"C": item},
                )
            ],
            [evidence("0~150")],
            CoveragePlan(),
            tables=[table(field="C", cell="0~150")],
        )
        self.assertEqual(audit.status, "fail")
        self.assertIn("CHEMICAL_RANGE_OUT_OF_RANGE", {issue.code for issue in audit.issues})

    def test_unit_mismatch_is_warning(self) -> None:
        audit = validate(
            document(),
            [record(value(unit="Pa"))],
            [evidence()],
            CoveragePlan(),
            tables=[table()],
        )
        self.assertEqual(audit.status, "review")
        self.assertIn("UNIT_MISMATCH", {issue.code for issue in audit.issues})

    def test_text_value_missing_is_l0_error(self) -> None:
        item = value(raw="", value=None, comparator="text", text=None, unit=None)
        audit = validate(
            document(),
            [record(item)],
            [evidence("")],
            CoveragePlan(),
            tables=[table(cell="")],
        )
        self.assertIn("TEXT_VALUE_MISSING", {issue.code for issue in audit.issues})


class NormalizationEdgeTests(unittest.TestCase):
    def test_fullwidth_digits(self) -> None:
        self.assertEqual(clean_text("０.０３"), "0.03")
        parsed = normalize_value("０.０３")
        self.assertEqual(parsed["value"], 0.03)

    def test_fullwidth_hyphen_range(self) -> None:
        parsed = normalize_value("０.２０－０.８０")
        self.assertEqual(parsed["comparator"], "range")
        self.assertEqual(parsed["lower"], 0.20)
        self.assertEqual(parsed["upper"], 0.80)

    def test_less_equal_max(self) -> None:
        parsed = normalize_value("≤０.０１")
        self.assertEqual(parsed["comparator"], "max")
        self.assertEqual(parsed["value"], 0.01)

    def test_unit_not_taken_from_property_token(self) -> None:
        self.assertEqual(parse_unit("抗拉强度Rm/MPa"), "MPa")
        self.assertEqual(parse_unit("断后伸长率A/%"), "%")

    def test_standard_no_variants(self) -> None:
        self.assertEqual(parse_standard_no("Q-Du 302-2015.md"), "Q/Du 302-2015")
        self.assertEqual(parse_standard_no("Q／S10-0351-2004.md"), "Q/S 10-0351-2004")
        self.assertEqual(parse_standard_no("GB-T1220-2007.md"), "GB/T 1220-2007")

    def test_foreign_standard_numbers(self) -> None:
        cases = {
            "ISO 5832-3-2021.pdf": "ISO 5832-3-2021",
            "GB 24627-2009过期.pdf": "GB 24627-2009",
            "ASTM B348_B348M-25--.pdf": "ASTM B348/B348M-25",
            "ASME SB338-2025.pdf": "ASME SB338-2025",
            "AMS4901V.pdf": "AMS 4901V",
            "AWS A5.16-A5.16M-2023.pdf": "AWS A5.16-A5.16M-2023",
            "HB 20079-2012 航空用钢.pdf": "HB 20079-2012",
            "NB-T 47019.8-2011 锅炉用管.pdf": "NB/T 47019.8-2011",
            "YST 1077-2015.pdf": "YS/T 1077-2015",
            "YYT 0345.1-2020.pdf": "YY/T 0345.1-2020",
            "AS4076.pdf": "AS 4076",
        }
        for name, expected in cases.items():
            self.assertEqual(parse_standard_no(name), expected, name)

    def test_cover_boilerplate_is_not_title(self) -> None:
        text = (
            "## 中华人民共和国国家标准\n\nGB/T3077—2015\n\n"
            "## 合金结构钢\n\n## Alloystructuresteels\n"
        )
        self.assertEqual(parse_heading_title(text), "合金结构钢")
        astm = (
            "## Standard Speciﬁcation for\n"
            "Titanium and Titanium Alloy Bars and Billets1\n\n"
            "## 1. Scope*\n"
        )
        self.assertEqual(
            parse_heading_title(astm),
            "Standard Speciﬁcation for Titanium and Titanium Alloy Bars and Billets",
        )
        ams = (
            "<table><tr><td colspan=\"3\">Superseding AMS4901U</td></tr>"
            "<tr><td colspan=\"3\">Titanium Sheet, Strip, and Plate</td></tr>"
            "</table>\n\n## RATIONALE\n\n## Copyright © 2025 SAE International\n"
        )
        self.assertEqual(parse_heading_title(ams), "Titanium Sheet, Strip, and Plate")

    def test_technical_agreement_uses_file_number_as_standard_no(self) -> None:
        digest = "c8f1e134282d41dcc40b5243f4e9a98d"
        document = DocumentMeta(
            doc_id="doc",
            source_path=f"{digest}.pdf",
            file_name=f"{digest}.pdf",
            title=digest,
        )
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 优质IN718 合金棒材技术要求\n\n"
                    "文件编号：LSAM-JD01-0006-2021\n"
                ),
            )
        ]
        updated = apply_page_identity(document, pages)
        self.assertEqual(updated.standard_no, "LSAM-JD01-0006-2021")
        self.assertEqual(updated.title, "优质IN718 合金棒材技术要求")
        self.assertEqual(updated.version, "2021")

    def test_real_standard_number_is_not_overwritten(self) -> None:
        document = DocumentMeta(
            doc_id="doc",
            source_path="GB-T1220-2007.pdf",
            file_name="GB-T1220-2007.pdf",
            standard_no="GB/T 1220-2007",
            title="不锈钢棒",
        )
        pages = [Page(page_no=1, markdown="文件编号：LSAM-JD01-0006-2021")]
        updated = apply_page_identity(document, pages)
        self.assertEqual(updated.standard_no, "GB/T 1220-2007")
        self.assertEqual(updated.title, "不锈钢棒")


if __name__ == "__main__":
    unittest.main()
