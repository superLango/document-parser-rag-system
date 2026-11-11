import unittest

from metal_doc_agent.contracts import DocumentMeta, DocumentResult, ExtractedValue, Record
from metal_doc_agent.tablegrid.normalize import (
    canonical_element,
    canonical_property,
    is_footnote_row,
    normalize_value,
    parse_unit,
)


class NormalizeTests(unittest.TestCase):
    def test_repeated_long_row_is_footnote(self):
        note = "公称直径小于16mm的棒材不进行冲击试验;公称直径小于12mm时,可在中间线上切取力学性能试样。"
        self.assertTrue(is_footnote_row([note] * 8))
        self.assertTrue(is_footnote_row(["锻制棒材"] + [note] * 16))
        self.assertFalse(is_footnote_row(["冷拉棒材*", "优质级", "≤30"]))
        self.assertFalse(is_footnote_row([note, note, note]))
        self.assertTrue(is_footnote_row(["注：仅实测报出，不作为判定依据。", "", ""]))

    def test_descending_range_is_sorted(self):
        parsed = normalize_value("341-293HB")
        self.assertEqual(parsed["comparator"], "range")
        self.assertEqual(parsed["lower"], 293.0)
        self.assertEqual(parsed["upper"], 341.0)

    def test_unit_case_and_impact_energy(self):
        self.assertEqual(parse_unit("Rm/Mpa"), "MPa")
        self.assertEqual(parse_unit("KV2/J/cm²"), "J/cm²")
        self.assertEqual(parse_unit("抗拉强度Rm/(N/mm²)"), "MPa")
        self.assertEqual(parse_unit("规定非比例延伸强度Rp0.2b/(N/mm2)"), "MPa")

    def test_ocr_space_in_decimal(self):
        parsed = normalize_value("0.000 03")
        self.assertEqual(parsed["comparator"], "eq")
        self.assertAlmostEqual(parsed["value"], 0.00003)

    def test_chinese_max_comparator(self):
        parsed = normalize_value("不大于 0.035")
        self.assertEqual(parsed["comparator"], "max")
        self.assertAlmostEqual(parsed["value"], 0.035)

    def test_symbol_max_comparator(self):
        parsed = normalize_value("≤0.035")
        self.assertEqual(parsed["comparator"], "max")
        self.assertAlmostEqual(parsed["value"], 0.035)

    def test_range(self):
        parsed = normalize_value("0.015~0.060")
        self.assertEqual(parsed["comparator"], "range")
        self.assertAlmostEqual(parsed["lower"], 0.015)
        self.assertAlmostEqual(parsed["upper"], 0.060)

    def test_remainder_is_text(self):
        parsed = normalize_value("余量")
        self.assertEqual(parsed["comparator"], "text")
        self.assertEqual(parsed["text"], "余量")

    def test_property_aliases(self):
        self.assertEqual(canonical_property(r"$\sigma_{b}$/MPa"), "Rm")
        self.assertEqual(canonical_property(r"$\sigma_{0.2}$/MPa"), "Rp0.2")
        self.assertEqual(canonical_property(r"$\delta_{s}$/%"), "A")
        self.assertEqual(canonical_property("断后伸长率 A50mm"), "A50mm")
        self.assertEqual(canonical_property("上屈服强度 ReH"), "ReH")
        self.assertEqual(canonical_property("断裂韧度 KIC"), "KIC")

    def test_element_alias(self):
        self.assertEqual(canonical_element("Fe^{b}$"), "Fe")
        self.assertEqual(canonical_element("Cr"), "Cr")
        self.assertIsNone(canonical_element("力学性能"))
        # A footnote letter may trail an element; "Pcm" is not phosphorus.
        self.assertEqual(canonical_element("Feb"), "Fe")
        self.assertEqual(canonical_element("Als不小于"), "Al")
        self.assertEqual(canonical_element("Als"), "Al")
        self.assertIsNone(canonical_element("Pcm"))
        self.assertIsNone(canonical_element("Pcm不大于"))
        self.assertIsNone(canonical_element("CEV"))

    def test_combined_element_rows_keep_their_formula(self):
        # "氮+氧(N+O)" is one row, not a multi-element sum limit. The CJK half
        # also contains "+", which used to make the label look like Cr+Cu+Mo+Ni.
        self.assertEqual(canonical_element("氮+氧(N+O)"), "N+O")
        self.assertEqual(canonical_element("氮+氧（N+O）"), "N+O")
        self.assertEqual(canonical_element("氢+氧 (H+O)"), "H+O")
        # Real sum constraints still describe no single element.
        self.assertIsNone(canonical_element("Cr+Cu+Mo+Ni"))
        self.assertIsNone(canonical_element("Cu+6Sn"))

    def test_fracture_toughness_unit(self):
        self.assertEqual(parse_unit("断裂韧度KIC/MPa·M1/2"), "MPa·m^1/2")
        self.assertEqual(parse_unit("断裂韧度KICbMPa·M1/2"), "MPa·m^1/2")


class ContractTests(unittest.TestCase):
    def test_round_trip(self):
        result = DocumentResult(
            document=DocumentMeta(
                doc_id="doc-1",
                source_path="sample.md",
                file_name="sample.md",
                standard_no="GB/T 1591-2018",
            ),
            records=[
                Record(
                    record_id="rec-1",
                    grade="Q355B",
                    properties={
                        "C": ExtractedValue(
                            raw="≤0.20",
                            value=0.20,
                            unit="%",
                            comparator="max",
                            evidence_id="ev-1",
                        )
                    },
                )
            ],
        )
        payload = result.model_dump(mode="json")
        restored = DocumentResult.model_validate(payload)
        self.assertEqual(restored.document.standard_no, "GB/T 1591-2018")
        self.assertEqual(restored.records[0].properties["C"].comparator, "max")


if __name__ == "__main__":
    unittest.main()
