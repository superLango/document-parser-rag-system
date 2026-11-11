import unittest

from metal_doc_agent.tablegrid.parser import parse_table


class TableGridTests(unittest.TestCase):
    def test_footnote_markers_are_stripped_from_cells(self) -> None:
        html = (
            "<table>"
            "<tr><td>牌号</td><td>C$^{a}$</td><td>$S^{c}$</td>"
            "<td>Ca</td><td>Ca$^{b}$</td><td>≤40$^{b}$</td></tr>"
            "<tr><td>Q420$^{g}$</td><td>0.20</td><td>0.035</td>"
            "<td>0.01</td><td>0.02</td><td>0.20</td></tr>"
            "</table>"
        )
        table = parse_table(html, table_id="T1", page_no=1, caption="表1 化学成分")
        self.assertEqual(table.header_paths[1][-1], "C")
        self.assertEqual(table.header_paths[2][-1], "S")
        self.assertEqual(table.header_paths[3][-1], "Ca")
        self.assertEqual(table.header_paths[4][-1], "Ca")
        self.assertEqual(table.header_paths[5][-1], "≤40")
        self.assertEqual(table.rows[1][0], "Q420")

    def test_rowspan_colspan_header_paths(self):
        html = """
        <table border="1">
          <tr><td rowspan="2">牌号</td><td colspan="3">室温力学性能</td></tr>
          <tr><td>Rm/MPa</td><td>Rp0.2/MPa</td><td>A/%</td></tr>
          <tr><td>2A14</td><td>430</td><td>350</td><td>10</td></tr>
        </table>
        """
        table = parse_table(html, table_id="T1", page_no=4, caption="表1 力学性能")
        self.assertEqual(table.n_rows, 3)
        self.assertEqual(table.n_cols, 4)
        self.assertEqual(table.header_rows, 2)
        self.assertEqual(table.rows[2], ["2A14", "430", "350", "10"])
        self.assertEqual(table.header_paths[0], ["牌号"])
        self.assertEqual(table.header_paths[1], ["室温力学性能", "Rm/MPa"])
        self.assertEqual(table.profile, "mechanical_properties")
        self.assertGreaterEqual(len(table.merges), 5)

    def test_multi_block_detection(self):
        html = """
        <table border="1">
          <tr><td rowspan="2">级别</td><td colspan="3">化学成分(质量分数)/%</td></tr>
          <tr><td>C</td><td>Cr</td><td>Ni</td></tr>
          <tr><td>普通级</td><td>0.015~0.060</td><td>17.00~21.00</td><td>50.00~55.00</td></tr>
          <tr><td>级别</td><td colspan="3">化学成分(质量分数)/%</td></tr>
          <tr><td>C</td><td>Cr</td><td>Ni</td></tr>
          <tr><td>高纯级</td><td>0.012~0.036</td><td>17.00~19.00</td><td>52.00~55.00</td></tr>
        </table>
        """
        table = parse_table(html, table_id="T2", page_no=8, caption="表2 化学成分")
        self.assertEqual(table.profile, "chemical_composition")
        self.assertEqual(len(table.blocks), 2)
        self.assertEqual(table.blocks[0].rows[2][0], "普通级")
        self.assertEqual(table.blocks[1].rows[2][0], "高纯级")

    def test_property_aliases_cover_common_standard_headers(self) -> None:
        from metal_doc_agent.tablegrid.normalize import canonical_property

        self.assertEqual(
            canonical_property("规定塑性延伸强度Rp1/MPa"), "Rp0.2"
        )
        self.assertEqual(
            canonical_property("规定非比例延伸强度Rm1/2MPa"), "Rp0.2"
        )
        self.assertEqual(
            canonical_property("规定非比例延伸强度Rpo2MPa"), "Rp0.2"
        )
        self.assertEqual(canonical_property("下屈服强度ReL"), "ReL")
        self.assertEqual(canonical_property("冲击吸收能量KU2/J"), "KU2")
        self.assertEqual(canonical_property("侧向膨胀值mm"), "LE")
        self.assertEqual(canonical_property("蠕变断裂时间tm/h"), "持久时间")

    def test_grade_patterns_cover_mixed_case_and_new_stainless(self) -> None:
        from metal_doc_agent.tablegrid.normalize import looks_like_grade

        for grade in ("H62", "HMn58-2", "HFe59-1-1", "QA110-3-1.5", "022Cr19Ni10"):
            self.assertTrue(looks_like_grade(grade), grade)
        for grade in ("Cr12MoV", "Y25Cr13Ni2", "40Cr10Si2Mo", "304", "316L", "410"):
            self.assertTrue(looks_like_grade(grade), grade)
        self.assertFalse(looks_like_grade("490"))
        self.assertFalse(looks_like_grade("T6"))

    def test_default_comparator_restores_missing_symbols(self) -> None:
        from metal_doc_agent.tablegrid.normalize import (
            apply_default_comparator,
            normalize_value,
        )

        self.assertEqual(
            apply_default_comparator(
                normalize_value("1035"), property_key="Rm"
            )["comparator"],
            "min",
        )
        self.assertEqual(
            apply_default_comparator(
                normalize_value("0.0001"), property_key="Ti", chemical=True
            )["comparator"],
            "max",
        )
        self.assertEqual(
            apply_default_comparator(
                normalize_value("0.006"),
                property_key="B",
                header_path=["化学成分", "B", "不大于"],
            )["comparator"],
            "max",
        )


if __name__ == "__main__":
    unittest.main()
