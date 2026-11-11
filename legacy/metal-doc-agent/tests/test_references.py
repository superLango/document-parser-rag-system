import unittest

from metal_doc_agent.contracts import DocumentMeta, Page
from metal_doc_agent.references import extract_references


def doc(standard_no: str | None = "GB/T 40303-2021") -> DocumentMeta:
    return DocumentMeta(
        doc_id="test-doc",
        source_path="x.md",
        file_name="x.md",
        standard_no=standard_no,
    )


class ReferenceTests(unittest.TestCase):
    def test_normative_section_fields_and_dedupe(self) -> None:
        pages = [
            Page(
                page_no=4,
                markdown=(
                    "## 2 规范性引用文件\n"
                    "GB/T 228.1-2021 金属材料 拉伸试验 第1部分：室温试验方法\n"
                    "GB/T 2975—2018 钢及钢产品 力学性能试验取样位置及试样制备\n"
                    "ASTM E8 金属材料拉伸试验方法\n"
                    "## 3 要求\n"
                    "拉伸试验按 GB/T 228.1 执行。\n"
                ),
            )
        ]
        graph = extract_references(pages, doc())
        edges = {edge.standard_no: edge for edge in graph.references}

        tension = edges["GB/T 228.1"]
        self.assertEqual(tension.edition, "2021")
        self.assertTrue(tension.dated)
        self.assertEqual(tension.relation, "normative")
        self.assertIn("金属材料", tension.title or "")
        self.assertFalse(tension.resolved)

        sampling = edges["GB/T 2975"]
        self.assertEqual(sampling.edition, "2018")
        self.assertTrue(sampling.dated)
        self.assertIn("取样位置", sampling.title or "")

        astm = edges["ASTM E8"]
        self.assertFalse(astm.dated)
        self.assertIsNone(astm.edition)
        self.assertEqual(len(graph.references), 3)

    def test_undated_inline_reference_merges_with_dated_edge(self) -> None:
        pages = [
            Page(
                page_no=4,
                markdown=(
                    "## 2 规范性引用文件\n"
                    "GB/T 228.1 金属材料 拉伸试验 第1部分：室温试验方法\n"
                    "## 3 要求\n"
                    "拉伸试验按 GB/T 228.1-2021 执行。\n"
                ),
            )
        ]
        graph = extract_references(pages, doc("GB/T 40303-2021"))
        edges = [edge for edge in graph.references if edge.standard_no == "GB/T 228.1"]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].edition, "2021")
        self.assertTrue(edges[0].dated)

    def test_self_standard_no_is_excluded(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "# GB/T 40303—2021\n"
                    "## 2 规范性引用文件\n"
                    "GB/T 228.1-2021 金属材料 拉伸试验 第1部分：室温试验方法\n"
                ),
            )
        ]
        graph = extract_references(pages, doc("GB/T 40303-2021"))
        self.assertEqual(
            [edge.standard_no for edge in graph.references], ["GB/T 228.1"]
        )

    def test_enterprise_and_military_numbers(self) -> None:
        pages = [
            Page(
                page_no=3,
                markdown=(
                    "## 2 规范性引用文件\n"
                    "GJB/Z33-1993 航空用钢和高温合金质量控制导则\n"
                    "Q/S10-0351-2004 某企业标准\n"
                    "JX-25-035 某企业规范\n"
                    "MAS 7079 某规范\n"
                    "ASTM E 21 金属材料高温拉伸试验\n"
                ),
            )
        ]
        graph = extract_references(pages, doc("Q/S10-0351-2004"))
        numbers = {edge.standard_no for edge in graph.references}
        self.assertIn("GJB/Z 33", numbers)
        self.assertIn("JX-25-035", numbers)
        self.assertIn("MAS 7079", numbers)
        self.assertIn("ASTM E21", numbers)
        self.assertNotIn("Q/S10-0351", numbers)

    def test_inline_references_require_citation_cue(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "# 前 言\n"
                    "本标准代替 GB 3191-82。\n"
                    "本标准采用 GB/T 3190-1996 中的牌号。\n"
                ),
            ),
            Page(
                page_no=2,
                markdown=(
                    "## 2 引用标准\n"
                    "GB/T 228-87 金属拉伸试验方法\n"
                    "## 3 要求\n"
                    "化学成分应符合 GB/T 3190 的规定。\n"
                    "Q355B 钢的力学性能见表 1。\n"
                ),
            ),
        ]
        graph = extract_references(pages, doc("GB/T 3191-1998"))
        edges = {edge.standard_no: edge for edge in graph.references}
        self.assertEqual(set(edges), {"GB/T 228", "GB/T 3190"})
        self.assertEqual(edges["GB/T 228"].relation, "normative")
        self.assertEqual(edges["GB/T 228"].edition, "1987")
        self.assertEqual(edges["GB/T 3190"].relation, "clause")
        self.assertIsNone(edges["GB/T 3190"].edition)
        self.assertEqual(edges["GB/T 3190"].clause_id, "3")
        self.assertEqual(edges["GB/T 3190"].page_no, 2)
        self.assertEqual(edges["GB/T 228"].clause_id, "2")

    def test_ams_std_and_amsys_heading(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 2、引用标准\n"
                    "ASTM E8 金属材料拉伸试验\n"
                    "AMS-STD-2154 压力加工金属超声波检测技术\n"
                ),
            )
        ]
        graph = extract_references(pages, doc("JX-25-035"))
        numbers = {edge.standard_no for edge in graph.references}
        self.assertEqual(numbers, {"ASTM E8", "AMS-STD-2154"})
        self.assertTrue(all(edge.relation == "normative" for edge in graph.references))

    def test_gaps_contain_unresolved_references(self) -> None:
        pages = [
            Page(
                page_no=4,
                markdown=(
                    "## 2 规范性引用文件\n"
                    "GB/T 228.1-2021 金属材料 拉伸试验\n"
                    "GB/T 2039 金属拉伸蠕变及持久试验方法\n"
                ),
            )
        ]
        graph = extract_references(pages, doc())
        self.assertEqual(graph.gaps, ["GB/T 2039", "GB/T 228.1-2021"])


if __name__ == "__main__":
    unittest.main()
