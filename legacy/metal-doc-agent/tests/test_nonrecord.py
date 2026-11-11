import unittest

from metal_doc_agent.contracts import (
    ClauseRecord,
    DocumentMeta,
    ExtractedValue,
    InspectionItem,
    TableGrid,
)
from metal_doc_agent.extraction.nonrecord import (
    attach_nh_rule,
    extract_nonrecord,
    extract_nh_rule,
    inspections_from_clauses,
    resolve_table_references,
)
from metal_doc_agent.tablegrid.parser import parse_table


def doc() -> DocumentMeta:
    return DocumentMeta(doc_id="test-doc", source_path="x.md", file_name="x.md")


class NonRecordTests(unittest.TestCase):
    def test_inspection_items_and_method_split(self) -> None:
        table = TableGrid(
            table_id="T1",
            page_no=1,
            profile="inspection",
            header_rows=2,
            header_paths=[
                ["检验项目"],
                ["检验项目及数量", "Ⅰ类"],
                ["检验项目及数量", "Ⅱ类"],
                ["检验项目及数量", "Ⅲ类"],
                ["取样部位"],
                ["要求的章节号"],
                ["检验方法的章节号"],
            ],
            rows=[
                ["检验项目", "检验项目及数量", "", "", "取样部位", "要求的章节号", "检验方法的章节号"],
                ["", "Ⅰ类", "Ⅱ类", "Ⅲ类", "", "", ""],
                ["力学性能", "逐件", "每批抽2件", "-", "钢材的一端，见8.3", "7.4", ""],
                ["硬度", "逐件", "逐件", "逐件", "-", "7.5", "8.4"],
            ],
        )
        output = extract_nonrecord(table, doc())
        items = {item.item: item for item in output.inspection_items}
        self.assertIn("力学性能", items)
        first = items["力学性能"]
        self.assertEqual(
            first.quantities, {"Ⅰ类": "逐件", "Ⅱ类": "每批抽2件", "Ⅲ类": "-"}
        )
        self.assertEqual(first.sample_location, "钢材的一端")
        self.assertEqual(first.method_clause, "见8.3")
        self.assertEqual(first.requirement_clause, "7.4")
        second = items["硬度"]
        self.assertIsNone(second.sample_location)
        self.assertEqual(second.method_clause, "8.4")

    def test_classification_items(self) -> None:
        table = TableGrid(
            table_id="T1",
            page_no=1,
            profile="classification",
            header_rows=2,
            header_paths=[
                ["牌号", "新代号"],
                ["牌号", "旧代号"],
                ["热处理状态", "新代号"],
                ["热处理状态", "旧代号"],
                ["热处理状态", "代号含义"],
            ],
            rows=[
                ["牌号", "", "热处理状态", "", ""],
                ["新代号", "旧代号", "新代号", "旧代号", "代号含义"],
                ["2A14", "LD10", "T6", "CS", "固溶处理加工时效"],
            ],
        )
        output = extract_nonrecord(table, doc())
        self.assertEqual(len(output.classification_items), 1)
        item = output.classification_items[0]
        self.assertEqual(item.grade, "2A14")
        self.assertEqual(item.old_grade, "LD10")
        self.assertEqual(item.state, "T6")
        self.assertEqual(item.old_state, "CS")
        self.assertEqual(item.meaning, "固溶处理加工时效")

    def test_profile_fallback_from_headers(self) -> None:
        html = (
            "<table>"
            "<tr><td>检验项目</td><td>取样数量</td><td>试验方法</td></tr>"
            "<tr><td>化学成分</td><td>1个/炉</td><td>GB/T 223</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1, caption="表1 化学成分")
        # The header is a strong signal; the caption belongs to the next table.
        self.assertEqual(table.profile, "inspection")
        output = extract_nonrecord(table, doc())
        self.assertEqual(len(output.inspection_items), 1)
        self.assertEqual(output.inspection_items[0].item, "化学成分")
        self.assertEqual(output.inspection_items[0].method_standard, "GB/T 223")

    def test_sampling_rule_column_is_quantity(self) -> None:
        table = TableGrid(
            table_id="T6",
            page_no=1,
            profile="inspection",
            header_rows=1,
            header_paths=[
                ["检验项目"],
                ["取样规定"],
                ["要求的章条号"],
                ["试验方法的章条号"],
            ],
            rows=[
                ["检验项目", "取样规定", "要求的章条号", "试验方法的章条号"],
                ["化学成分", "每批1份", "3.2", "4.1"],
                ["力学性能", "每批取2根，各取1个试样", "3.3", "4.2"],
            ],
        )
        output = extract_nonrecord(table, doc())
        items = {item.item: item for item in output.inspection_items}
        self.assertEqual(items["化学成分"].quantities, {"取样规定": "每批1份"})
        self.assertEqual(
            items["力学性能"].quantities, {"取样规定": "每批取2根，各取1个试样"}
        )
        self.assertEqual(items["化学成分"].method_clause, "4.1")

    def test_rounding_appendix_is_not_an_inspection_table(self) -> None:
        table = TableGrid(
            table_id="T493",
            page_no=1,
            profile="inspection",
            header_rows=1,
            header_paths=[["试验项目"], ["试验数据范围"], ["圆整值"]],
            rows=[
                ["试验项目", "试验数据范围", "圆整值"],
                ["屈服点", "<50000lb/in.", "100psi"],
                ["抗拉强度", "<500MPa", "1MPa"],
            ],
        )
        output = extract_nonrecord(table, doc())
        self.assertEqual(output.inspection_items, [])

    def test_inspection_uses_test_item_column(self) -> None:
        table = TableGrid(
            table_id="T3",
            page_no=1,
            profile="inspection",
            header_rows=1,
            header_paths=[["试验项目"], ["适用品种"], ["复验数量"]],
            rows=[
                ["试验项目", "适用品种", "复验数量"],
                ["成品分析", "所有紧固件", "1个/批"],
                ["冲击试验", "除螺母以外的紧固件", "表3，C(组)，每组3个试样"],
                ["硬度试验", "所有紧固件", "表3，B"],
            ],
        )
        output = extract_nonrecord(table, doc())
        self.assertEqual(
            [item.item for item in output.inspection_items],
            ["成品分析", "冲击试验", "硬度试验"],
        )
        self.assertEqual(
            output.inspection_items[1].quantities["复验数量"],
            "表3，C(组)，每组3个试样",
        )

    def test_table_reference_resolves_variable_lookup(self) -> None:
        reference = TableGrid(
            table_id="T4",
            page_no=1,
            caption="表3 复验抽样规则",
            header_rows=2,
            header_paths=[
                ["批量(件)"],
                ["每批抽样数量", "B"],
                ["每批抽样数量", "C"],
            ],
            rows=[
                ["批量(件)", "每批抽样数量", "每批抽样数量"],
                ["批量(件)", "B", "C"],
                ["1~2", "1", "1"],
                ["51~90", "5", "2"],
                ["3201~35000", "15", "4"],
            ],
        )
        item = InspectionItem(item="拉伸", quantities={"复验数量": "表3，C"})
        resolved = resolve_table_references([item], [reference])[0]
        self.assertEqual(resolved.quantities["复验数量"], "表3，C")
        self.assertIn("1~2→1", resolved.note or "")
        self.assertIn("3201~35000→4", resolved.note or "")

    def test_table_reference_resolves_constant_lookup(self) -> None:
        reference = TableGrid(
            table_id="T4",
            page_no=1,
            caption="表3 复验抽样规则",
            header_rows=2,
            header_paths=[["批量(件)"], ["每批抽样数量", "B"]],
            rows=[
                ["批量(件)", "每批抽样数量"],
                ["批量(件)", "B"],
                ["1~2", "1"],
                ["51~90", "1"],
            ],
        )
        item = InspectionItem(item="硬度", quantities={"复验数量": "表3，B"})
        resolved = resolve_table_references([item], [reference])[0]
        self.assertEqual(resolved.quantities["复验数量"], "1")
        self.assertIn("表3，B→1", resolved.note or "")

    def test_duplicate_hardness_rows_are_merged(self) -> None:
        table = TableGrid(
            table_id="T8",
            page_no=1,
            profile="inspection",
            header_rows=2,
            header_paths=[
                ["检验项目"],
                ["取样部位和数量", "I类环形件"],
                ["取样部位和数量", "II类环形件"],
                ["取样部位和数量", "III类环形件"],
                ["取样部位和数量", "IV类环形件"],
                ["要求的章节号"],
                ["检验方法的章节号"],
            ],
            rows=[
                ["检验项目", "取样部位和数量", "", "", "", "要求的章节号", "检验方法的章节号"],
                ["", "I类环形件", "II类环形件", "III类环形件", "IV类环形件", "", ""],
                ["硬度", "逐件试验环，2个", "环形件或试验环，2个", "-", "-", "3.5", "4.3.6"],
                ["硬度", "环形件，逐件", "环形件，逐件", "环形件，逐件", "环形件10%，且不少于3件", "3.5", "4.3.6"],
            ],
        )
        output = extract_nonrecord(table, doc())
        hardness = [item for item in output.inspection_items if item.item == "硬度"]
        self.assertEqual(len(hardness), 1)
        merged = hardness[0]
        self.assertEqual(
            merged.quantities["I类环形件"], "逐件试验环，2个；环形件，逐件"
        )
        self.assertEqual(
            merged.quantities["IV类环形件"], "环形件10%，且不少于3件"
        )
        self.assertIsNone(merged.sample_location)

    def test_multi_axis_inspection_table_uses_class_axes(self) -> None:
        table = TableGrid(
            table_id="T9",
            page_no=1,
            profile="inspection",
            header_rows=3,
            header_paths=[
                ["序号"],
                ["锻件类别 检验项目"],
                ["锻件类别 检验项目"],
                ["I类锻件", "供方检验项目"],
                ["I类锻件", "需方复检项目", "单件"],
                ["I类锻件", "需方复检项目", "批量"],
                ["II类锻件", "供方检验项目", "单件"],
                ["II类锻件", "供方检验项目", "批量"],
                ["II类锻件", "需方复检项目", "单件"],
                ["II类锻件", "需方复检项目", "批量"],
                ["III类锻件", "供方检验项目"],
                ["III类锻件", "需方复检项目"],
                ["备注"],
            ],
            rows=[
                [
                    "序号", "锻件类别 检验项目", "锻件类别 检验项目",
                    "I类锻件", "I类锻件", "I类锻件",
                    "II类锻件", "II类锻件", "II类锻件", "II类锻件",
                    "III类锻件", "III类锻件", "备注",
                ],
                [
                    "序号", "锻件类别 检验项目", "锻件类别 检验项目",
                    "供方检验项目", "需方复检项目", "需方复检项目",
                    "供方检验项目", "供方检验项目", "需方复检项目",
                    "需方复检项目", "供方检验项目", "需方复检项目", "备注",
                ],
                [
                    "序号", "锻件类别 检验项目", "锻件类别 检验项目",
                    "供方检验项目", "单件", "批量", "单件", "批量",
                    "单件", "批量", "供方检验项目", "需方复检项目", "备注",
                ],
                [
                    "2", "力学性能", "拉伸试样",
                    "100%", "100%", "100%",
                    "抽检10%~30%，但不少于2件。", "100%",
                    "抽检10%~30%，但不少于2件。",
                    "多于2件的抽检2件，不大于2件的全检。",
                    "——", "——", "注：每批锻件指相同炉号。",
                ],
                [
                    "4", "硬度检查", "硬度检查",
                    "100%", "100%", "100%", "100%", "100%", "100%",
                    "100%", "100%", "100%", "同上。",
                ],
                ["注：1)每批锻件是指相同炉号、同热处理炉次的锻件。"],
            ],
        )
        output = extract_nonrecord(table, doc())
        items = {item.item: item for item in output.inspection_items}
        self.assertEqual(set(items), {"拉伸试样", "硬度检查"})

        tensile = items["拉伸试样"].quantities
        self.assertEqual(set(tensile), {"I类锻件", "II类锻件"})
        self.assertEqual(tensile["I类锻件"], "100%")
        self.assertIn("供方检验项目 / 单件：抽检10%~30%，但不少于2件。", tensile["II类锻件"])
        self.assertIn("需方复检项目 / 批量：多于2件的抽检2件", tensile["II类锻件"])

        hardness = items["硬度检查"].quantities
        self.assertEqual(
            hardness,
            {"I类锻件": "100%", "II类锻件": "100%", "III类锻件": "100%"},
        )

    def test_multi_axis_frame_aligns_short_item_header(self) -> None:
        table = TableGrid(
            table_id="T10",
            page_no=1,
            profile="inspection",
            header_rows=3,
            header_paths=[
                ["序号"],
                ["锻件类别 检验项目"],
                ["I类锻件", "供方检验项目"],
                ["I类锻件", "需方复检项目", "单件"],
                ["I类锻件", "需方复检项目", "批量"],
                ["II类锻件", "供方检验项目"],
                ["II类锻件", "需方复检项目"],
                ["备注"],
            ],
            rows=[
                [
                    "序号", "锻件类别 检验项目",
                    "I类锻件", "I类锻件", "I类锻件", "II类锻件", "II类锻件", "备注",
                ],
                [
                    "序号", "锻件类别 检验项目",
                    "供方检验项目", "需方复检项目", "需方复检项目",
                    "供方检验项目", "需方复检项目", "备注",
                ],
                [
                    "序号", "锻件类别 检验项目",
                    "供方检验项目", "单件", "批量", "供方检验项目", "需方复检项目", "备注",
                ],
                [
                    "3", "力学性能", "拉伸试样",
                    "100%", "100%", "抽检10%~30%，但不少于2件。", "100%", "同上。",
                ],
                [
                    "1", "化学成分", "每一炉号", "每一炉号", "每一炉号", "每一炉号", "同上。",
                ],
                [
                    "6", "金相检查", "外观质量", "外观质量",
                    "100%", "100%", "100%", "100%", "同上。",
                ],
                [
                    "5", "超声波探伤", "超声波探伤",
                    "-", "-", "-", "-", "同上。",
                ],
            ],
        )
        output = extract_nonrecord(table, doc())
        items = {item.item: item for item in output.inspection_items}
        self.assertEqual(set(items), {"拉伸试样", "化学成分", "外观质量"})
        quantities = items["拉伸试样"].quantities
        self.assertEqual(set(quantities), {"I类锻件", "II类锻件"})
        self.assertIn("需方复检项目 / 批量：抽检10%~30%", quantities["I类锻件"])
        self.assertEqual(quantities["II类锻件"], "100%")
        self.assertEqual(
            items["化学成分"].quantities,
            {"I类锻件": "每一炉号", "II类锻件": "每一炉号"},
        )
        self.assertEqual(
            items["外观质量"].quantities,
            {"I类锻件": "100%", "II类锻件": "100%"},
        )

    def test_default_key_rows_are_not_merged(self) -> None:
        table = TableGrid(
            table_id="T12",
            page_no=1,
            profile="inspection",
            header_rows=1,
            header_paths=[["检验项目"], ["抽样规定"]],
            rows=[
                ["检验项目", "抽样规定"],
                ["硬度", "每批锻件检验5%，但不少于5件"],
                ["硬度", "逐件试验"],
            ],
        )
        output = extract_nonrecord(table, doc())
        self.assertEqual(
            len([item for item in output.inspection_items if item.item == "硬度"]),
            2,
        )

    def test_colspan_footnote_row_is_not_an_item(self) -> None:
        # GLM-OCR emits a trailing colspan note row; the expanded grid repeats
        # the same prose in every column and must not become an inspection item.
        html = (
            "<table>"
            "<tr><td>检验项目</td><td>取样规定</td><td>要求的章条号</td>"
            "<td>试验方法的章条号</td></tr>"
            "<tr><td>化学成分</td><td>每批1份</td><td>3.2</td><td>4.1</td></tr>"
            '<tr><td colspan="4">a氢含量在距离棒材表面4mm~6mm处取样;其他化学成分,'
            "供方以原铸锭的分析结果报出,需方复验在棒材上取样。b供方可按铸锭的"
            "分析结果报出,需方在棒材上取样检验。</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1, caption="表6 检验项目")
        self.assertEqual(table.profile, "inspection")
        output = extract_nonrecord(table, doc())
        self.assertEqual([item.item for item in output.inspection_items], ["化学成分"])

    def test_room_and_high_temperature_tensile_are_distinct(self) -> None:
        from metal_doc_agent.extraction.nonrecord import _matches_label

        self.assertTrue(_matches_label("室温拉伸", "拉伸试样"))
        self.assertFalse(_matches_label("室温拉伸", "高温拉伸"))
        self.assertTrue(_matches_label("高温拉伸", "高温拉伸"))
        self.assertFalse(_matches_label("高温拉伸", "拉伸试样"))

    def test_nh_sampling_rule_is_attached_to_sampled_items(self) -> None:
        rule = (
            "N表示抽检数量，H表示送检数量，1)H≤10，N=H；2)10<H≤100，N=10；"
            "3)100<H<500，N=10%H抽；4)H≥500，N=50"
        )
        table = TableGrid(
            table_id="T1",
            page_no=1,
            profile="inspection",
            header_rows=1,
            header_paths=[
                ["编号"],
                ["检验项目"],
                ["检测频次"],
                ["认可方式"],
                ["检验方法"],
            ],
            rows=[
                ["编号", "检验项目", "检测频次", "认可方式", "检验方法"],
                ["1", "左侧止口直径", "抽检", "查验乙方报告", ""],
                ["2", "化学成分", "每批", "查验乙方报告", "GB/T 223"],
                [
                    f"备注：(1)编号图示位置见附图检验图纸；(2)产品特性："
                    f"G表示关键特性，Z表示重要特性；(3){rule}。"
                ],
            ],
        )
        self.assertEqual(extract_nh_rule([table]), rule)

        output = extract_nonrecord(table, doc())
        attach_nh_rule(output.inspection_items, extract_nh_rule([table]))
        items = {item.item: item for item in output.inspection_items}
        self.assertIn("抽检数量N/H分档", items["左侧止口直径"].note or "")
        self.assertEqual(items["化学成分"].quantities, {"检测频次": "每批"})
        self.assertIsNone(items["化学成分"].note)

    def test_sampling_clause_fills_missing_inspection_items(self) -> None:
        def field(raw: str) -> ExtractedValue:
            return ExtractedValue(raw=raw, text=raw, comparator="text")

        clauses = [
            ClauseRecord(
                clause_id="B.3",
                title="化学成分检查",
                kind="technical_requirement",
                fields={
                    "sample_quantity": field("1件"),
                    "method_standard": field("GB/T 223"),
                },
            ),
            ClauseRecord(
                clause_id="B.4.2",
                title="力学性能试样",
                kind="technical_requirement",
                fields={
                    "sample_location": field("叶片毛坯"),
                    "method_standard": field("GB/T228.1"),
                },
            ),
            ClauseRecord(
                clause_id="6.2",
                title="取样规定",
                kind="sampling",
                fields={"sample_location": field("取样规定")},
            ),
        ]
        existing = [InspectionItem(item="室温拉伸", quantities={"default": "1"})]
        items = inspections_from_clauses(clauses, existing)
        self.assertEqual([item.item for item in items], ["化学成分"])
        self.assertEqual(items[0].quantities, {"取样数量": "1件"})
        self.assertEqual(items[0].requirement_clause, "B.3")
        self.assertEqual(items[0].method_standard, "GB/T 223")


if __name__ == "__main__":
    unittest.main()
