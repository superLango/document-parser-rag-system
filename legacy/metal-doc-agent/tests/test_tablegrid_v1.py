"""TableGrid v1 tests: cross-page caption, continuation merge, headers, orientation."""

from __future__ import annotations

import unittest

from metal_doc_agent.contracts import Page
from metal_doc_agent.tablegrid.parser import extract_tables, find_caption, parse_table


def simple_table(header: str, row: str) -> str:
    return f"<table><tr><td>{header}</td><td>Rm</td></tr><tr><td>{row}</td><td>430</td></tr></table>"


class TableGridV1Tests(unittest.TestCase):
    def test_caption_from_previous_page(self) -> None:
        pages = [
            Page(page_no=1, markdown="## 4.5 力学性能\n表2 轧制锻件室温力学性能\n"),
            Page(page_no=2, markdown=simple_table("牌号", "2A14")),
        ]
        tables = extract_tables(pages)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].page_no, 2)
        self.assertIn("表2", tables[0].caption or "")

    def test_caption_after_table(self) -> None:
        pages = [
            Page(
                page_no=3,
                markdown=simple_table("牌号", "2A14") + "\n表7 尺寸偏差\n",
            )
        ]
        tables = extract_tables(pages)
        self.assertIn("表7", tables[0].caption or "")

    def test_continuation_merge(self) -> None:
        pages = [
            Page(page_no=1, markdown="表1 化学成分\n" + simple_table("牌号", "A")),
            Page(
                page_no=2,
                markdown="表1 化学成分（续）\n" + simple_table("牌号", "B"),
            ),
        ]
        tables = extract_tables(pages)
        self.assertEqual(len(tables), 1)
        table = tables[0]
        self.assertEqual(table.n_rows, 3)
        self.assertEqual(table.merged_pages, [1, 2])
        self.assertEqual(table.continuation_of, table.table_id)
        self.assertIn("A", table.rows[1][0])
        self.assertIn("B", table.rows[2][0])

    def test_no_merge_for_different_table(self) -> None:
        pages = [
            Page(page_no=1, markdown="表1 化学成分\n" + simple_table("牌号", "A")),
            Page(page_no=2, markdown="表2 力学性能\n" + simple_table("牌号", "B")),
        ]
        tables = extract_tables(pages)
        self.assertEqual(len(tables), 2)

    def test_multi_row_header(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td>质量等级</td><td>C</td><td>Si</td></tr>"
            "<tr><td>钢级</td><td>质量等级</td><td>以下公称厚度</td><td>不大于</td></tr>"
            "<tr><td></td><td></td><td>≤40</td><td>>40</td></tr>"
            "<tr><td></td><td></td><td>不大于</td><td>不大于</td></tr>"
            "<tr><td>Q355</td><td>B</td><td>0.24</td><td>0.55</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1, caption="表1 化学成分")
        self.assertEqual(table.header_rows, 4)
        self.assertIn("≤40", table.header_paths[2])
        self.assertEqual(table.profile, "chemical_composition")

    def test_header_rowspan_does_not_leak_into_data(self) -> None:
        html = (
            "<table>"
            '<tr><td colspan="2">牌号</td><td colspan="14">化学成分</td></tr>'
            '<tr><td rowspan="4">钢级</td><td rowspan="4">质量等级</td>'
            '<td colspan="2">C</td><td>Si</td><td>Mn</td><td>P</td><td>S</td>'
            '<td>Nb</td><td>V</td><td>Ti</td><td>Cr</td><td>Ni</td><td>Cu</td>'
            '<td>Mo</td><td>N</td><td>B</td></tr>'
            '<tr><td colspan="2">以下公称厚度或直径/mm</td>'
            '<td rowspan="5" colspan="13">不大于</td></tr>'
            '<tr><td colspan="2">≤40h</td><td>>40</td></tr>'
            '<tr><td colspan="2">不大于</td></tr>'
            '<tr><td rowspan="3">Q390</td><td>B</td><td rowspan="3">0.20</td>'
            '<td rowspan="3">0.55</td><td rowspan="3">1.70</td><td>0.035</td>'
            '<td>0.035</td><td rowspan="3">0.05</td><td rowspan="3">0.13</td>'
            '<td rowspan="3">0.05</td><td rowspan="3">0.30</td><td rowspan="3">0.50</td>'
            '<td rowspan="3">0.40</td><td rowspan="3">0.10</td>'
            '<td rowspan="3">0.015</td><td rowspan="2">-</td></tr>'
            "<tr><td>C</td><td>0.030</td><td>0.030</td></tr>"
            "<tr><td>D</td><td>0.025</td><td>0.025</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1, caption="表1 化学成分")
        self.assertEqual(table.n_cols, 17)
        self.assertIn(">40", table.header_paths[3])
        self.assertEqual(table.rows[5][2], "0.20")
        self.assertEqual(table.rows[5][3], "0.20")
        self.assertEqual(table.rows[5][4], "0.55")
        self.assertEqual(table.rows[6][6], "0.030")

    def test_digit_prefixed_grades_are_data_not_range_headers(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td colspan=\"2\">化学成分</td></tr>"
            "<tr><td></td><td>C</td><td>Si</td></tr>"
            "<tr><td>30Si2MnCrMoVE</td><td>0.27~0.32</td><td>1.40~1.70</td></tr>"
            "<tr><td>30Cr3SiNiMoVA</td><td>0.28~0.34</td><td>0.90~1.20</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1, caption="表1 牌号及化学成分")
        self.assertEqual(table.header_rows, 2)
        self.assertEqual(table.rows[2][0], "30Si2MnCrMoVE")

    def test_transposed_orientation(self) -> None:
        html = (
            "<table>"
            "<tr><td>元素</td><td>2A14</td><td>2B14</td><td>2C14</td></tr>"
            "<tr><td>C</td><td>0.1</td><td>0.2</td><td>0.3</td></tr>"
            "<tr><td>Si</td><td>0.5</td><td>0.6</td><td>0.7</td></tr>"
            "<tr><td>Fe</td><td>0.2</td><td>0.2</td><td>0.2</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1, caption="表1 化学成分")
        self.assertEqual(table.orientation, "element_rows")
        self.assertEqual(table.profile, "chemical_composition")

    def test_footnote_after_table(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=simple_table("牌号", "A") + "\n注：a 为实测值。\n",
            )
        ]
        tables = extract_tables(pages)
        self.assertTrue(any("注：a" in note for note in tables[0].footnotes))

    def test_inspection_profile_wins_over_mechanical_items(self) -> None:
        html = (
            "<table>"
            "<tr><td>检验项目</td><td>取样数量</td><td>试验方法</td></tr>"
            "<tr><td>硬度</td><td>逐件</td><td>GB/T 231.1</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1, caption="表3 检验项目")
        self.assertEqual(table.profile, "inspection")

    def test_mechanical_header_wins_over_chemical_caption(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td>抗拉强度Rm/(N/mm²)</td>"
            "<td>断后伸长率A/%</td><td>硬度</td></tr>"
            "<tr><td>12Cr17Mn6Ni5N</td><td>520</td><td>40</td><td>241</td></tr>"
            "</table>"
        )
        table = parse_table(
            html, "T1", 12, caption="表5 沉淀硬化型不锈钢的化学成分"
        )
        self.assertEqual(table.profile, "mechanical_properties")

    def test_mechanical_with_sample_state_column(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td>供货状态</td><td>试样状态</td>"
            "<td>直径/mm</td><td>抗拉强度Rm/MPa</td>"
            "<td>规定非比例延伸强度Rp0.2/MPa</td><td>断后伸长率A/%</td></tr>"
            "<tr><td>6061</td><td>T6</td><td>时效</td><td>20</td>"
            "<td>260</td><td>240</td><td>8</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 9, caption="表7")
        self.assertEqual(table.profile, "mechanical_properties")

    def test_inspection_table_listing_chemistry_item(self) -> None:
        html = (
            "<table>"
            "<tr><td>检验项目</td><td>取样规定</td>"
            "<td>要求的章条号</td><td>试验方法的章条号</td></tr>"
            "<tr><td>化学成分</td><td>按 GB/T 17432</td><td>3.2</td><td>4.1</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 17, caption="表11")
        self.assertEqual(table.profile, "inspection")

    def test_carbon_equivalent_is_chemistry(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td>碳当量CEV(质量分数)/%不大于</td>"
            "<td>焊接裂纹敏感性指数Pcm/%不大于</td></tr>"
            "<tr><td>Q355</td><td>0.40</td><td>0.25</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T8", 26, caption="表4")
        self.assertEqual(table.profile, "chemical_composition")

    def test_process_parameter_table_is_inspection(self) -> None:
        html = (
            "<table>"
            "<tr><td>序号</td><td>工艺参数偏差/%</td><td>轧制锻件1</td><td>备注</td></tr>"
            "<tr><td>1</td><td>±0.5</td><td>合格</td><td>-</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T5", 9, caption="表5")
        self.assertEqual(table.profile, "inspection")

    def test_conductivity_with_mechanical_reference_column(self) -> None:
        html = (
            "<table>"
            "<tr><td>合金牌号</td><td>供应状态</td><td>电导率指标MS/m</td>"
            "<td>力学性能</td><td>合格判定</td></tr>"
            "<tr><td>6061</td><td>T6</td><td>≥25</td><td>见表6</td><td>合格</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 19, caption="表7 电导率")
        self.assertEqual(table.profile, "inspection")

    def test_rowspan_grade_header_not_shifted(self) -> None:
        html = (
            "<table>"
            "<tr><td rowspan='3'>牌号</td><td colspan='3'>化学成分(质量分数)/%</td></tr>"
            "<tr><td>Si</td><td>Fe</td><td>Cu</td></tr>"
            "<tr><td>Si</td><td>Fe</td><td>Cu</td></tr>"
            "<tr><td>5051A</td><td>≤0.30</td><td>≤0.45</td><td>≤0.05</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 5)
        self.assertEqual(table.header_rows, 3)
        self.assertEqual(table.header_paths[0], ["牌号"])
        self.assertEqual(table.header_paths[1][-1], "Si")
        self.assertEqual(table.header_paths[2][-1], "Fe")
        self.assertEqual(table.rows[3][0], "5051A")

    def test_caption_fills_unknown_header(self) -> None:
        html = (
            "<table>"
            "<tr><td>项目</td><td>指标</td><td>方法</td></tr>"
            "<tr><td>屈服强度</td><td>205</td><td>GB/T 228.1</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1, caption="表6 力学性能")
        self.assertEqual(table.profile, "mechanical_properties")

    def test_short_subheader_keeps_header_rowspan(self) -> None:
        # OCR dropped one colspan: the group cell spans 6 columns but the
        # sub-header has 8 cells, so the first row is one cell short of the
        # previous width. The 牌号 rowspan must not be cleared.
        html = (
            "<table>"
            '<tr><td rowspan="2">牌号</td><td>主要成分</td>'
            '<td colspan="6">杂质元素，不大于</td></tr>'
            "<tr><td>Ti</td><td>Fe</td><td>C</td><td>N</td><td>H</td><td>O</td>"
            "<td>其余单个杂质</td><td>其余杂质总和</td></tr>"
            "<tr><td>TA1</td><td>余量</td><td>0.25</td><td>0.10</td><td>0.03</td>"
            "<td>0.015</td><td>0.20</td><td>0.1</td><td>0.4</td></tr>"
            "</table>"
        )
        table = parse_table(html, "T1", 1)
        self.assertEqual(table.n_cols, 9)
        self.assertEqual(table.header_paths[0], ["牌号"])
        self.assertEqual(table.header_paths[1][-1], "Ti")
        self.assertEqual(table.header_paths[2][-1], "Fe")
        self.assertEqual(table.rows[2][0], "TA1")
        self.assertEqual(table.rows[2][2], "0.25")

    def test_italic_caption_without_heading(self) -> None:
        self.assertEqual(find_caption("*表4 力学性能*"), "表4 力学性能")


if __name__ == "__main__":
    unittest.main()
