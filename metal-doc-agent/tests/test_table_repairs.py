import unittest
from pathlib import Path

from metal_doc_agent.ingest import ingest
from metal_doc_agent.tablegrid import extract_tables
from metal_doc_agent.tablegrid.repairs import apply_table_repairs

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "标准文件" / "GBT 40303-2021"
DOC = CORPUS / "GBT 40303-2021   GH4169合金棒材通用技术条件.md"
DOC_3191 = (
    ROOT.parent
    / "标准文件"
    / "GBT 3191-1998"
    / "GBT 3191-1998 铝及铝合金挤压棒材.md"
)
DOC_1220 = (
    ROOT.parent
    / "标准文件"
    / "GB-T1220-2007"
    / "GB-T1220-2007 不锈钢棒.md"
)
DOC_JX = (
    ROOT.parent
    / "标准文件"
    / "JX-25-035"
    / "JX-25-035+GH4698高温合金棒材采购技术协议.md"
)
DOC_1591 = (
    ROOT.parent
    / "标准文件"
    / "GBT 1591-2018"
    / "GBT 1591-2018 低合金高强度结构钢.md"
)
CONFIG = ROOT / "configs" / "table_repairs.json"


@unittest.skipUnless(DOC.exists(), "GB/T 40303 corpus file is not present")
class TableRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document, pages = ingest(DOC)
        tables = extract_tables(pages)
        cls.tables = {
            table.table_id: table
            for table in apply_table_repairs(tables, document, CONFIG)
        }

    def test_t4_status_and_diameter_columns(self) -> None:
        table = self.tables["T4"]
        self.assertEqual(table.n_cols, 18)
        self.assertEqual(table.rows[8][0], "热轧棒材")
        self.assertEqual(table.rows[8][1], "普通级优质级")
        self.assertEqual(table.rows[8][2], ">80~125")
        self.assertEqual(table.rows[8][6], "室温")
        self.assertEqual(table.rows[8][7], "32")
        self.assertEqual(table.rows[10][2], ">125~200")

    def test_t4_t6_stay_separate_due_to_different_headers(self) -> None:
        t4 = self.tables["T4"]
        t6 = self.tables["T6"]
        self.assertNotEqual(t4.header_paths[9], t6.header_paths[9])
        self.assertEqual(t4.n_cols, 18)
        self.assertEqual(t6.n_cols, 17)
        self.assertIn("续", t6.caption or "")

    def test_t6_missing_grade_and_diameter(self) -> None:
        table = self.tables["T6"]
        self.assertEqual(table.rows[5][6], "-196")
        self.assertEqual(table.rows[6][0], "锻制棒材")
        self.assertEqual(table.rows[6][1], "高级优质级")
        self.assertEqual(table.rows[6][2], "200~300")
        self.assertEqual(table.rows[6][6], "室温")
        self.assertEqual(table.rows[6][7], "32")
        self.assertEqual(table.rows[7][6], "650")

    def test_t14_header_and_data_row(self) -> None:
        table = self.tables["T14"]
        self.assertEqual(table.n_cols, 11)
        self.assertEqual(table.header_rows, 3)
        self.assertEqual(table.rows[3][0], "A")
        self.assertEqual(table.rows[3][1], "15~400")
        self.assertEqual(table.rows[3][3], "≥1034")
        self.assertIn("不小于", table.header_paths[10])

    def test_t14_t15_merged_and_trailing_column_trimmed(self) -> None:
        self.assertNotIn("T15", self.tables)
        table = self.tables["T14"]
        self.assertEqual(table.n_cols, 11)
        self.assertEqual(table.header_rows, 3)
        self.assertEqual(table.merged_pages, [17, 18])
        self.assertEqual(len(table.rows), 15)
        self.assertEqual(len(table.rows[3]), 11)
        self.assertEqual(table.rows[13][0], "G")
        self.assertIn("不小于", table.header_paths[10])


class Gbt40303PdfRepairTests(unittest.TestCase):
    """The PDF grid (17 columns) shifts forged rows left by one cell."""

    def test_t4_pdf_layout_restores_grade_and_temperature(self) -> None:
        from metal_doc_agent.contracts import DocumentMeta, TableGrid

        headers = [f"h{index}" for index in range(17)]
        rows = [
            headers,
            headers,
            headers,
        ]
        for _ in range(11):
            rows.append([""] * 17)
        rows.append(
            [
                "锻制棒材",
                ">125~200",
                "横向",
                "热处理",
                "固溶+时效",
                "室温",
                "32",
                "≥1240",
                "1035",
                "6",
                "8",
                "-",
                "-",
                "-",
                "-",
                "-",
                "346HEW",
            ]
        )
        rows.append(
            [
                "锻制棒材",
                ">125~200",
                "横向",
                "热处理",
                "固溶+时效",
                "650",
                "-",
                "≥965",
                "860",
                "6",
                "8",
                "690",
                "25",
                "-",
                "-",
                "",
                "346HEW",
            ]
        )
        rows.append(
            [
                "锻制棒材",
                ">125~200",
                "横向",
                "热处理",
                "固溶+时效",
                "-1964",
                "-",
                "≥1470",
                "-",
                "12",
                "20",
                "-",
                "-",
                "-",
                "-",
                "",
                "346HEW",
            ]
        )
        table = TableGrid(
            table_id="T4",
            page_no=1,
            caption="表3 棒材的力学性能",
            n_rows=len(rows),
            n_cols=17,
            header_rows=3,
            rows=rows,
            header_paths=[[header] for header in headers],
        )
        document = DocumentMeta(
            doc_id="pdf-doc",
            source_path="gbt40303_2021.pdf",
            file_name="gbt40303_2021.pdf",
            standard_no="GB/T 40303-2021",
            title="GH4169",
            page_count=1,
        )
        repaired = apply_table_repairs([table], document, CONFIG)[0]
        self.assertEqual(repaired.rows[14][1], "普通级优质级")
        self.assertEqual(repaired.rows[14][6], "室温")
        self.assertEqual(repaired.rows[14][7], "32")
        self.assertEqual(repaired.rows[14][8], "≥1240")
        self.assertEqual(repaired.rows[16][6], "-196")
        self.assertEqual(repaired.rows[16][7], "4")


@unittest.skipUnless(DOC_3191.exists(), "GB/T 3191-1998 corpus file is not present")
class Gbt3191RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document, pages = ingest(DOC_3191)
        tables = extract_tables(pages)
        cls.tables = {
            table.table_id: table
            for table in apply_table_repairs(tables, document, CONFIG)
        }

    def test_2a11_row_keeps_elongation(self) -> None:
        row = self.tables["T6"].rows[18]
        self.assertEqual(row[0], "2A11")
        self.assertEqual(row[3], "≤150")
        self.assertEqual(row[4], "370")
        self.assertEqual(row[5], "215")
        self.assertEqual(row[6], "12")

    def test_2a12_rows_have_distinct_diameters_and_states(self) -> None:
        first = self.tables["T6"].rows[19]
        second = self.tables["T6"].rows[20]
        self.assertEqual(first[3], "≤22")
        self.assertEqual(first[4], "390")
        self.assertEqual(first[6], "12")
        self.assertEqual(second[1], "T4")
        self.assertEqual(second[3], ">22~150")

    def test_6061_rows_are_realigned(self) -> None:
        table = self.tables["T6"]
        self.assertEqual(table.rows[33][4], "260")
        self.assertEqual(table.rows[33][6], "9")
        self.assertEqual(table.rows[34][1], "T4")
        self.assertEqual(table.rows[34][3], "≤150")
        self.assertEqual(table.rows[34][6], "14")


@unittest.skipUnless(DOC_1220.exists(), "GB/T 1220-2007 corpus file is not present")
class Gbt1220RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document, pages = ingest(DOC_1220)
        tables = extract_tables(pages)
        cls.tables = {
            table.table_id: table
            for table in apply_table_repairs(tables, document, CONFIG)
        }

    def test_t7_z_header_restored(self) -> None:
        table = self.tables["T7"]
        self.assertEqual(table.header_rows, 2)
        self.assertEqual(table.n_cols, 11)
        self.assertEqual(table.header_paths[7], ["断面收缩率Zc/%", "不小于"])
        self.assertEqual(table.header_paths[8], ["硬度b", "不大于"])
        self.assertEqual(table.rows[2][7], "50")


@unittest.skipUnless(DOC_JX.exists(), "JX-25-035 corpus file is not present")
class JxCaptionRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document, pages = ingest(DOC_JX)
        tables = extract_tables(pages)
        cls.tables = {
            table.table_id: table
            for table in apply_table_repairs(tables, document, CONFIG)
        }

    def test_t6_caption_from_appendix(self) -> None:
        self.assertEqual(
            self.tables["T6"].caption, "附录A 化学成分试验标准"
        )


@unittest.skipUnless(DOC_1591.exists(), "GB/T 1591-2018 corpus file is not present")
class Gbt1591RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document, pages = ingest(DOC_1591)
        tables = extract_tables(pages)
        cls.tables = {
            table.table_id: table
            for table in apply_table_repairs(tables, document, CONFIG)
        }

    def test_t1_header_elements_and_thickness(self) -> None:
        table = self.tables["T1"]
        self.assertEqual(table.header_rows, 4)
        self.assertEqual(table.n_cols, 17)
        self.assertIn("C", table.header_paths[2])
        self.assertEqual(table.header_paths[2][-1], "≤40")
        self.assertEqual(table.header_paths[3][-1], ">40")
        self.assertEqual(table.header_paths[6][-2], "P")
        self.assertEqual(table.header_paths[7][-2], "S")
        self.assertEqual(table.header_paths[8][-2], "Nb")
        self.assertEqual(table.header_paths[9][-2], "V")
        self.assertEqual(table.header_paths[10][-2], "Ti")
        self.assertEqual(table.header_paths[15][-2], "N")
        self.assertEqual(table.rows[4][0], "Q355")
        self.assertEqual(table.rows[4][1], "B")
        self.assertEqual(table.rows[4][2], "0.24")
        self.assertEqual(table.rows[4][3], "0.24")
        self.assertEqual(table.rows[4][6], "0.035")
        self.assertEqual(table.rows[4][8], "—")
        self.assertEqual(table.rows[12][0], "Q460")
        self.assertEqual(table.rows[12][15], "0.015")

    def test_t4_chemistry_rows_are_aligned(self) -> None:
        table = self.tables["T4"]
        self.assertEqual(table.n_cols, 16)
        self.assertEqual(table.header_rows, 3)
        self.assertEqual(table.n_rows, 19)
        self.assertEqual(table.rows[3][0], "Q355N")
        self.assertEqual(table.rows[3][1], "B")
        self.assertEqual(table.rows[6][2], "0.18")
        self.assertEqual(table.rows[7][2], "0.16")
        self.assertEqual(table.rows[8][0], "Q390N")
        self.assertEqual(table.rows[8][14], "0.015")
        self.assertEqual(table.rows[11][1], "E")
        self.assertEqual(table.rows[12][0], "Q420N")
        self.assertEqual(table.rows[14][15], "0.025")
        self.assertEqual(table.rows[17][0], "Q460N")
        self.assertEqual(table.rows[18][5], "0.025")
        self.assertEqual(table.rows[18][15], "0.025")
        self.assertEqual(table.header_paths[15][-1], "Als不小于")

    def test_t13_last_impact_column_keeps_parent_header(self) -> None:
        table = self.tables["T13"]
        self.assertEqual(table.header_paths[11][-2:], ["-60℃", "横向"])
        self.assertIn("KV", table.header_paths[11][0])
        self.assertEqual(table.header_paths[11], table.header_paths[10][:1] + ["-60℃", "横向"])


class LearnedRepairTests(unittest.TestCase):
    """Self-heal rules: per-document replay and approved template reuse."""

    HEADERS = ["牌号", "状态", "直径/mm", "Rm/MPa", "Rp0.2/MPa", "A/%"]

    def make_table(self, document_rows=None, table_id: str = "T1"):
        from metal_doc_agent.contracts import TableGrid

        rows = [list(self.HEADERS)]
        rows.extend(
            document_rows
            or [["2A11", "T4", "≤150", "370", "215", "12"]]
        )
        return TableGrid(
            table_id=table_id,
            page_no=1,
            caption="表1 棒材的力学性能",
            n_rows=len(rows),
            n_cols=len(self.HEADERS),
            header_rows=1,
            rows=rows,
            header_paths=[[header] for header in self.HEADERS],
        )

    def write_learned(self, payload: dict) -> Path:
        import json
        import tempfile

        directory = tempfile.mkdtemp()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(directory, ignore_errors=True)
        )
        path = Path(directory) / "table_repairs.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return path

    @staticmethod
    def make_document(doc_id: str = "doc-1", standard_no: str = ""):
        from metal_doc_agent.contracts import DocumentMeta

        return DocumentMeta(
            doc_id=doc_id,
            source_path=f"{doc_id}.pdf",
            file_name=f"{doc_id}.pdf",
            standard_no=standard_no,
            title="棒材",
            page_count=1,
        )

    def test_document_rule_replays_by_doc_id(self) -> None:
        spec = {
            "replace_rows": {
                "1": ["2A11", "T4", "≤150", "370", "215", "14"]
            }
        }
        learned = self.write_learned({"documents": {"doc-1": {"T1": spec}}})
        table = self.make_table()
        repaired = apply_table_repairs(
            [table],
            self.make_document(),
            None,
            learned_path=learned,
        )[0]
        self.assertEqual(repaired.rows[1][5], "14")

    def test_document_rule_matches_normalized_standard_no(self) -> None:
        spec = {"patch_cells": {"1": {"5": "16"}}}
        learned = self.write_learned(
            {"documents": {"GBT403032021": {"T1": spec}}}
        )
        table = self.make_table()
        repaired = apply_table_repairs(
            [table],
            self.make_document(standard_no="GB/T 40303-2021"),
            None,
            learned_path=learned,
        )[0]
        self.assertEqual(repaired.rows[1][5], "16")

    def test_approved_template_applies_on_same_signature(self) -> None:
        from metal_doc_agent.tablegrid.repairs import table_signature

        source = self.make_table()
        signature = table_signature(source)
        spec = {"patch_cells": {"1": {"5": "310"}}}
        learned = self.write_learned(
            {
                "templates": {
                    signature: {
                        "table_id": "T1",
                        "spec": spec,
                        "status": "approved",
                    }
                }
            }
        )
        target = self.make_table(
            [["6061", "T6", "≤150", "310", "275", "12"]],
        )
        self.assertEqual(table_signature(target), signature)
        repaired = apply_table_repairs(
            [target],
            self.make_document(doc_id="doc-2"),
            None,
            learned_path=learned,
        )[0]
        self.assertEqual(repaired.rows[1][5], "310")

    def test_pending_template_is_not_applied(self) -> None:
        from metal_doc_agent.tablegrid.repairs import table_signature

        signature = table_signature(self.make_table())
        learned = self.write_learned(
            {
                "templates": {
                    signature: {
                        "table_id": "T1",
                        "spec": {"patch_cells": {"1": {"5": "310"}}},
                        "status": "pending",
                    }
                }
            }
        )
        table = self.make_table()
        repaired = apply_table_repairs(
            [table],
            self.make_document(doc_id="doc-2"),
            None,
            learned_path=learned,
        )[0]
        self.assertEqual(repaired.rows[1][5], "12")

    def test_template_drops_numbers_absent_from_source_table(self) -> None:
        from metal_doc_agent.tablegrid.repairs import table_signature

        signature = table_signature(self.make_table())
        learned = self.write_learned(
            {
                "templates": {
                    signature: {
                        "table_id": "T1",
                        "spec": {
                            "replace_rows": {
                                "1": ["2A11", "T4", "≤150", "370", "215", "99"]
                            }
                        },
                        "status": "approved",
                    }
                }
            }
        )
        table = self.make_table()
        repaired = apply_table_repairs(
            [table],
            self.make_document(doc_id="doc-2"),
            None,
            learned_path=learned,
        )[0]
        self.assertEqual(repaired.rows[1][5], "12")

    def test_template_with_other_table_id_is_ignored(self) -> None:
        from metal_doc_agent.tablegrid.repairs import table_signature

        signature = table_signature(self.make_table())
        learned = self.write_learned(
            {
                "templates": {
                    signature: {
                        "table_id": "T2",
                        "spec": {"patch_cells": {"1": {"5": "310"}}},
                        "status": "approved",
                    }
                }
            }
        )
        table = self.make_table()
        repaired = apply_table_repairs(
            [table],
            self.make_document(doc_id="doc-2"),
            None,
            learned_path=learned,
        )[0]
        self.assertEqual(repaired.rows[1][5], "12")


if __name__ == "__main__":
    unittest.main()
