import unittest

from metal_doc_agent.contracts import DocumentMeta, Page
from metal_doc_agent.extraction.clauses import extract_clauses


def doc() -> DocumentMeta:
    return DocumentMeta(doc_id="test-doc", source_path="x.md", file_name="x.md")


class ClauseTests(unittest.TestCase):
    def test_body_only_clauses_and_spaced_ids(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 4.8 超声波检测\n"
                    "4. 8. 1 轧制锻件的超声波检测应在热处理后进行。\n"
                    "## 4.9 表面质量\n"
                    "4.9.1 轧制锻件应经粗加工后交付。\n"
                    "## 5.2.2 组批\n"
                    "轧制锻件应成批提交验收。\n"
                    "## 5.2.3.2.1 取样数量\n"
                    "1类件应每批逐件取样。\n"
                ),
            )
        ]
        output = extract_clauses(pages, doc())
        clauses = {clause.clause_id: clause for clause in output.clauses}
        self.assertIn("4.8.1", clauses)
        self.assertIn("4.9.1", clauses)
        self.assertIn("5.2.2", clauses)
        self.assertIn("5.2.3.2.1", clauses)
        self.assertNotIn("1", clauses)
        self.assertIn("应在热处理后进行", clauses["4.8.1"].fields["requirement"].raw)
        self.assertIn("应经粗加工", clauses["4.9.1"].fields["requirement"].raw)
        self.assertEqual(clauses["5.2.2"].fields["text"].raw, "轧制锻件应成批提交验收。")

    def test_body_after_next_heading_is_moved_back(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 5.2.6.6 形状和尺寸\n"
                    "## 5.2.6.7 表面质量\n"
                    "应采用专用量具等方法检验轧制锻件形状和尺寸。\n"
                    "轧制锻件经粗加工后观察表面质量。\n"
                ),
            )
        ]
        output = extract_clauses(pages, doc())
        clauses = {clause.clause_id: clause for clause in output.clauses}
        self.assertIn("形状和尺寸", clauses["5.2.6.6"].fields["requirement"].raw)
        self.assertNotIn("形状和尺寸", clauses["5.2.6.7"].fields["text"].raw)
        self.assertIn("观察表面质量", clauses["5.2.6.7"].fields["text"].raw)

    def test_ndt_and_inclusion_clauses_keep_reference_and_table(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 5.3.3.1 非金属夹杂物\n"
                    "锻件的非金属夹杂物按照NB/T 20008.12 第8.3 节的要求。"
                    "按GB/T 10561- 2023 中的A 法检验非金属夹杂物，"
                    "并按GB/T 10561-2023 附录C 中的评级图谱进行评定。"
                    "检验结果满足表5-4 要求：\n"
                    "## 7.2 超声波检验\n"
                    "超声检测的实施方法，按照NB/T 20008.12 第11.2 节的要求执行。"
                    "对直径小于50mm 的棒材也应进行超声波检验。\n"
                ),
            )
        ]
        output = extract_clauses(pages, doc())
        clauses = {clause.clause_id: clause for clause in output.clauses}
        inclusion = clauses["5.3.3.1"].fields["requirement"].raw
        self.assertIn("NB/T 20008.12", inclusion)
        self.assertIn("表5-4", inclusion)
        self.assertIn("NB/T20008.12", clauses["5.3.3.1"].fields["method_standard"].raw)
        ultrasonic = clauses["7.2"].fields["requirement"].raw
        self.assertIn("NB/T 20008.12", ultrasonic)
        self.assertIn("第11.2 节", ultrasonic)
        self.assertIn("NB/T20008.12", clauses["7.2"].fields["method_standard"].raw)

    def test_duplicate_clause_ids_are_merged(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 5.2.1 检验规则\n"
                    "## 5.2.1 检验规则\n"
                    "质量一致性检验项目按表3的规定进行。\n"
                ),
            )
        ]
        output = extract_clauses(pages, doc())
        matches = [clause for clause in output.clauses if clause.clause_id == "5.2.1"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].fields["text"].raw, "质量一致性检验项目按表3的规定进行。")

    def test_numbered_list_line_stays_in_body(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 5.2.3.2.1 取样数量\n"
                    "1 类件应每批逐件在轧制锻件本体上取样，进行力学性能检测。\n"
                ),
            )
        ]
        clauses = {clause.clause_id: clause for clause in extract_clauses(pages, doc()).clauses}
        self.assertNotIn("1", clauses)
        self.assertIn("逐件", clauses["5.2.3.2.1"].fields["sample_quantity"].raw)

    def test_inline_sentence_becomes_body(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "5. 2.3.4.1 在轧制锻件本体的上端面圆周上切取1个试样。\n"
                    "5. 2.3.4.2 I、II类轧制锻件每批随机抽一件检查。\n"
                ),
            )
        ]
        clauses = {clause.clause_id: clause for clause in extract_clauses(pages, doc()).clauses}
        self.assertEqual(
            clauses["5.2.3.4.1"].fields["sample_location"].raw,
            "轧制锻件本体的上端面圆周上",
        )
        self.assertEqual(
            clauses["5.2.3.4.1"].fields["sample_quantity"].raw, "1个"
        )
        self.assertIn("5.2.3.4.2", clauses)

    def test_direction_terms_from_titles(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 3.4.1 室温纵向拉伸力学性能\n"
                    "棒材的室温纵向拉伸力学性能应符合表7的规定。\n"
                    "## 3.5 力学性能取样\n"
                    "从棒材头或尾切取横向（弦向）试样经热处理后测试力学性能。\n"
                    "## 3.4.2 断裂韧度\n"
                    "断裂韧度优先选取开口方向垂直流线方向。\n"
                ),
            )
        ]
        clauses = {clause.clause_id: clause for clause in extract_clauses(pages, doc()).clauses}
        self.assertEqual(clauses["3.4.1"].fields["direction"].raw, "纵向")
        self.assertEqual(clauses["3.5"].fields["direction"].raw, "横向（弦向）")
        self.assertEqual(clauses["3.4.2"].fields["direction"].raw, "垂直流线方向")

    def test_test_temperature_key(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown="## 6.1 试验温度\n试验温度为20℃。\n",
            )
        ]
        clauses = {clause.clause_id: clause for clause in extract_clauses(pages, doc()).clauses}
        self.assertEqual(clauses["6.1"].fields["test_temperature"].raw, "20℃")

    def test_clause_fields_and_normalization(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 7.1.1 热轧钢的牌号及化学成分\n"
                    "热轧钢的牌号及化学成分（熔炼分析）应符合表1的规定。\n"
                    "## 7.4.1.5 拉伸试样方向\n"
                    "对于公称宽度不小于600mm的钢板及钢带，拉伸试验取横向试样；"
                    "其他钢材的拉伸试验取纵向试样。\n"
                    "## 8.3 冲击试验取样位置\n"
                    "当需方无特殊要求时，冲击试验的取样位置按如下规定进行：\n"
                    "a) 对于型钢，按GB/T2975-2018图A.3的规定；\n"
                    "b) 圆钢按图A.5的规定；\n"
                    "c) 方钢按图A.9的规定；\n"
                    "d) 钢板按图A.11的规定。\n"
                    "## 9.3 取样数量\n"
                    "每批钢材的取样部位和取样数量见表13。\n"
                ),
            )
        ]
        output = extract_clauses(pages, doc())
        clauses = {clause.clause_id: clause for clause in output.clauses}
        self.assertEqual(
            clauses["7.1.1"].fields["requirement"].raw,
            "热轧钢的牌号及化学成分（熔炼分析）应符合表1的规定。",
        )
        self.assertEqual(
            clauses["7.4.1.5"].fields["direction"].raw,
            "公称宽度不小于600mm的钢板及钢带取横向；其他钢材取纵向",
        )
        self.assertEqual(
            clauses["8.3"].fields["sample_location"].raw,
            "型钢按GB/T2975-2018图A.3；圆钢按图A.5；方钢按图A.9；钢板按图A.11",
        )
        self.assertEqual(
            clauses["9.3"].fields["sample_quantity"].raw,
            "每批钢材的取样部位和取样数量见表13。",
        )
        self.assertTrue(output.evidence)


if __name__ == "__main__":
    unittest.main()
