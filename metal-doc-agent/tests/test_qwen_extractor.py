"""Tests for Qwen header mapping + deterministic row assembly."""

from __future__ import annotations

import unittest

from metal_doc_agent.contracts import DocumentMeta
from metal_doc_agent.extraction.qwen import (
    QwenExtractor,
    _clean_grade,
    _element_tokens,
    _implausible_property,
    _is_header_like_row,
    _row_has_misplaced_condition,
)
from metal_doc_agent.settings import Settings
from metal_doc_agent.tablegrid.parser import parse_table

MECH_HTML = (
    "<table>"
    "<tr><td>牌号</td><td>热处理状态</td><td>取样方向</td>"
    "<td>抗拉强度Rm/MPa(不小于)</td><td>断后伸长率A/%(不小于)</td></tr>"
    "<tr><td>2A14</td><td>T6</td><td>切向</td><td>430</td><td>10</td></tr>"
    "</table>"
)

CHEM_HTML = (
    "<table>"
    "<tr><td>牌号</td><td>化学成分(质量分数)/%</td><td>化学成分(质量分数)/%</td></tr>"
    "<tr><td></td><td>C</td><td>Si</td></tr>"
    "<tr><td>2A14</td><td>0.015~0.060</td><td>0.35</td></tr>"
    "</table>"
)


class FakeQwen:
    def __init__(self, response: str | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self.error:
            raise self.error
        return self.response or ""


def make_settings() -> Settings:
    return Settings(
        project_root=__import__("pathlib").Path("."),
        data_dir=__import__("pathlib").Path("."),
        ocr_backend="mock",
        extractor_backend="qwen",
        glm_ocr_base_url=None,
        glm_ocr_model="GLM-OCR",
        qwen_base_url="http://test/v1",
        qwen_model="Qwen3.5-9B",
        api_key=None,
        request_timeout=10.0,
        layout_service_url=None,
    )


def doc() -> DocumentMeta:
    return DocumentMeta(
        doc_id="test-doc", source_path="test.md", file_name="test.md"
    )


class QwenExtractorTests(unittest.TestCase):
    def test_qwen_mapping_and_row_assembly(self) -> None:
        mapping = (
            '{"columns":['
            '{"index":0,"role":"grade"},'
            '{"index":1,"role":"condition"},'
            '{"index":2,"role":"condition"},'
            '{"index":3,"role":"property","property":"Rm","unit":"MPa"},'
            '{"index":4,"role":"property","property":"A","unit":"%"}'
            "]}"
        )
        client = FakeQwen(response=mapping)
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能")
        output = extractor.extract(table, doc())

        self.assertEqual(len(client.calls), 1)
        self.assertTrue(client.calls[0]["json_mode"])
        self.assertEqual(len(output.records), 1)
        record = output.records[0]
        self.assertEqual(record.grade, "2A14")
        self.assertEqual(record.condition, "T6 / 切向")
        self.assertEqual(record.properties["Rm"].value, 430.0)
        self.assertEqual(record.properties["Rm"].comparator, "min")
        self.assertEqual(record.properties["Rm"].unit, "MPa")
        self.assertEqual(record.properties["A"].value, 10.0)
        self.assertEqual(record.properties["A"].unit, "%")
        self.assertTrue(record.properties["Rm"].evidence_id)
        self.assertEqual(len(output.evidence), 2)
        self.assertEqual(output.evidence[0].page_no, 5)
        self.assertEqual(output.evidence[0].row, 1)

    def test_rule_bound_columns_ignore_shifted_model_mapping(self) -> None:
        mapping = (
            '{"columns":['
            '{"index":0,"role":"grade"},'
            '{"index":1,"role":"condition"},'
            '{"index":2,"role":"condition"},'
            '{"index":4,"role":"property","property":"Rm","unit":"MPa"}'
            "]}"
        )
        client = FakeQwen(response=mapping)
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能")
        block = table.blocks[0]
        resolved = extractor._map_columns(table, block, "mechanical_properties")
        self.assertEqual(resolved.property_cols, {3: "Rm", 4: "A"})
        output = extractor.extract(table, doc())
        record = output.records[0]
        self.assertEqual(record.properties["Rm"].value, 430.0)
        self.assertEqual(record.properties["A"].value, 10.0)

    def test_model_cannot_rebind_property_owned_by_rules(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td>Rm/MPa</td><td>A/%</td><td>硬度</td></tr>"
            "<tr><td>2A14</td><td>430</td><td>10</td><td>250</td></tr>"
            "</table>"
        )
        mapping = (
            '{"columns":['
            '{"index":0,"role":"grade"},'
            '{"index":1,"role":"property","property":"Rm","unit":"MPa"},'
            '{"index":2,"role":"property","property":"A","unit":"%"},'
            '{"index":3,"role":"property","property":"A","unit":"%"}'
            "]}"
        )
        client = FakeQwen(response=mapping)
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(html, "T1", 5, caption="表1 力学性能")
        block = table.blocks[0]
        resolved = extractor._map_columns(table, block, "mechanical_properties")
        # 硬度 is now a rule-owned property (bare 硬度 defaults to Brinell);
        # the model still cannot rebind it to A.
        self.assertEqual(resolved.property_cols, {1: "Rm", 2: "A", 3: "HB"})
        output = extractor.extract(table, doc())
        self.assertEqual(output.records[0].properties["A"].value, 10.0)
        self.assertEqual(output.records[0].properties["HB"].value, 250.0)

    def test_invalid_mapping_falls_back_to_rules(self) -> None:
        client = FakeQwen(response="not json")
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能")
        output = extractor.extract(table, doc())
        self.assertEqual(len(output.records), 1)
        self.assertEqual(output.records[0].grade, "2A14")
        self.assertEqual(output.records[0].properties["Rm"].value, 430.0)
        self.assertTrue(extractor.last_errors)
        self.assertEqual(extractor.last_mapping_source[table.blocks[0].block_id], "rules")

    def test_service_error_falls_back_to_rules(self) -> None:
        client = FakeQwen(error=RuntimeError("down"))
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能")
        output = extractor.extract(table, doc())
        self.assertEqual(len(output.records), 1)
        self.assertTrue(extractor.last_errors)

    def test_shorthand_grade_expansion(self) -> None:
        self.assertEqual(_clean_grade("Q355B、C、D"), "Q355B、Q355C、Q355D")
        self.assertEqual(_clean_grade("Q420B、C"), "Q420B、Q420C")
        self.assertEqual(_clean_grade("Q355B、Q355C"), "Q355B、Q355C")

    def test_element_token_handles_als_and_rejects_pcm(self) -> None:
        self.assertEqual(
            _element_tokens("化学成分(质量分数)/% Als不小于"), ("Al",)
        )
        self.assertEqual(_element_tokens("Als不小于"), ("Al",))
        self.assertEqual(_element_tokens("Pcm不大于"), ())

    def test_chemical_mapping(self) -> None:
        mapping = (
            '{"columns":['
            '{"index":0,"role":"grade"},'
            '{"index":1,"role":"property","property":"C","unit":"%"},'
            '{"index":2,"role":"property","property":"Si","unit":"%"}'
            "]}"
        )
        client = FakeQwen(response=mapping)
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(CHEM_HTML, "T1", 1, caption="表1 化学成分")
        output = extractor.extract(table, doc())
        self.assertEqual(len(output.records), 1)
        record = output.records[0]
        self.assertEqual(record.grade, "2A14")
        self.assertEqual(record.properties["C"].lower, 0.015)
        self.assertEqual(record.properties["C"].upper, 0.06)
        self.assertEqual(record.properties["C"].unit, "%")
        self.assertEqual(record.properties["Si"].value, 0.35)

    def test_remark_column_splits_rows_and_footnote_marker_is_dropped(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td>抗拉强度Rm/MPa</td>"
            "<td>规定非比例延伸强度Rp0.2/MPa</td><td>断后伸长率A/%</td>"
            "<td>断面收缩率Z/%</td><td>备注</td></tr>"
            "<tr><td>TB2</td><td>≤980</td><td>820</td><td>18</td><td>40</td>"
            "<td>淬火性能</td></tr>"
            "<tr><td>TB2</td><td>1370</td><td>1100</td><td>7</td><td>10</td>"
            "<td>时效性能</td></tr>"
            "<tr><td>TC6a</td><td>980</td><td>840</td><td>10</td><td>25</td><td></td></tr>"
            '<tr><td colspan="6">aTC6棒材测定普通退火状态的性能。当需方要求并在'
            "合同中注明时,方测定等温退火状态的性能。</td></tr>"
            "</table>"
        )
        mapping = (
            '{"columns":[' 
            '{"index":0,"role":"grade"},'
            '{"index":1,"role":"property","property":"Rm","unit":"MPa"},'
            '{"index":2,"role":"property","property":"Rp0.2","unit":"MPa"},'
            '{"index":3,"role":"property","property":"A","unit":"%"},'
            '{"index":4,"role":"property","property":"Z","unit":"%"},'
            '{"index":5,"role":"ignore"}'
            "]}"
        )
        client = FakeQwen(response=mapping)
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(html, "T1", 4, caption="表2 室温力学性能")
        output = extractor.extract(table, doc())

        grades = [record.grade for record in output.records]
        self.assertEqual(grades, ["TB2", "TB2", "TC6"])
        tb2 = [r for r in output.records if r.grade == "TB2"]
        self.assertEqual({r.condition for r in tb2}, {"淬火性能", "时效性能"})
        self.assertEqual(tb2[0].properties["Rm"].value, 980)
        self.assertEqual(tb2[0].properties["Rm"].comparator, "max")
        self.assertEqual(tb2[1].properties["Rm"].value, 1370)

    def test_duplicate_property_columns_keep_the_first_value(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td>热处理状态</td><td>取样方向</td>"
            "<td>抗拉强度Rm/MPa</td><td>抗拉强度Rm/MPa</td>"
            "<td>断后伸长率A/%</td></tr>"
            "<tr><td>2A14</td><td>T6</td><td>纵向</td>"
            "<td>430</td><td>355</td><td>10</td></tr>"
            "</table>"
        )
        client = FakeQwen(response="not json")
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(html, "T1", 5, caption="表1 力学性能")
        output = extractor.extract(table, doc())

        record = output.records[0]
        self.assertEqual(record.properties["Rm"].value, 430.0)
        self.assertEqual(record.properties["A"].value, 10.0)

    def test_mixed_header_row_is_skipped(self) -> None:
        paths = [
            ["序号"],
            ["材料牌号"],
            ["供应状态"],
            ["锻件种类"],
            ["力学性能", "纵向", "抗拉强度RmMPa"],
            ["力学性能", "纵向", "断后伸长率A%"],
            ["布氏硬度HBW"],
        ]
        row = [
            "序号", "材料牌号", "供应状态", "锻件种类", "T6", "模锻件",
            "430", "抗拉强度RmMPa", "断后伸长率A%", "布氏硬度HBW",
        ]
        self.assertTrue(_is_header_like_row(row, paths))

        data_row = ["2A14", "T6", "纵向", "430", "10", "95"]
        self.assertFalse(_is_header_like_row(data_row, paths))

    def test_header_text_in_numeric_column_is_rejected(self) -> None:
        self.assertTrue(_implausible_property("Rm", "抗拉强度RmMPa"))
        self.assertTrue(_implausible_property("A", "断后伸长率A%"))
        self.assertFalse(_implausible_property("Rm", "≥960"))
        self.assertFalse(_implausible_property("Rm", "实测"))
        self.assertTrue(_implausible_property("Rm", "T6"))

    def test_condition_leak_into_property_column_is_detected(self) -> None:
        columns = {4: "Rm", 5: "Rp0.2", 6: "A"}
        shifted = ["17", "6A02", "O", "模锻件", "T6", "295", "215"]
        self.assertTrue(_row_has_misplaced_condition(shifted, columns))
        aligned = ["17", "6A02", "O", "模锻件", "295", "215", "20"]
        self.assertFalse(_row_has_misplaced_condition(aligned, columns))

    def test_caption_supplies_missing_grade(self) -> None:
        from metal_doc_agent.extraction.qwen import _caption_grade

        self.assertEqual(_caption_grade("表1 GH4169高温合金母合金化学成分（wt%）"), "GH4169")
        self.assertEqual(_caption_grade("表2 GH4202力学性能指标要求"), "GH4202")
        self.assertEqual(_caption_grade("表1 S-07母合金化学成分（wt%）"), "S-07")
        self.assertEqual(_caption_grade("表1 304NG饼形锻件化学成分"), "304NG")
        self.assertIsNone(_caption_grade("表3 检验项目"))

    def test_dash_new_grade_falls_back_to_old_grade(self) -> None:
        html = (
            "<table>"
            "<tr><td>新牌号</td><td>旧牌号</td><td>抗拉强度Rm/MPa</td></tr>"
            "<tr><td>-</td><td>1Cr18Ni9Ti</td><td>540</td></tr>"
            "</table>"
        )
        client = FakeQwen(response="not json")
        extractor = QwenExtractor(make_settings(), client=client)
        table = parse_table(html, "T1", 3, caption="表1 化学成分")
        output = extractor.extract(table, doc())

        self.assertEqual(output.records[0].grade, "1Cr18Ni9Ti")


if __name__ == "__main__":
    unittest.main()
