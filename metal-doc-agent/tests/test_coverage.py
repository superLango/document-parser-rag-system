import unittest

from metal_doc_agent.contracts import (
    DocumentMeta,
    ItemInventory,
    ItemInventoryEntry,
    Page,
    Record,
    TableClauseLink,
    TableGrid,
    TableLinkResult,
)
from metal_doc_agent.coverage import build_links, build_outline
from metal_doc_agent.coverage.audit import build_coverage_audit
from metal_doc_agent.extraction.clauses import extract_clauses


def make_table(
    table_id: str,
    page_no: int,
    caption: str | None,
    *,
    continuation_of: str | None = None,
    profile: str = "mechanical_properties",
    rows: list[list[str]] | None = None,
) -> TableGrid:
    body = rows or [["牌号", "Rm"], ["A", "100"], ["B", "200"]]
    return TableGrid(
        table_id=table_id,
        page_no=page_no,
        n_rows=len(body),
        n_cols=len(body[0]),
        header_rows=1,
        rows=body,
        header_paths=[["牌号"], ["Rm"]],
        profile=profile,
        orientation="grade_rows",
        caption=caption,
        continuation_of=continuation_of,
    )


def make_document() -> DocumentMeta:
    return DocumentMeta(
        doc_id="doc", source_path="doc.md", file_name="doc.md", standard_no="GB/T X"
    )


class OutlineTests(unittest.TestCase):
    def test_clause_ids_include_appendix(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown="## 7.4 力学性能\n表3\n\n## B.2.3 力学性能\n表B.3\n",
            )
        ]
        outline = build_outline(make_document(), pages)
        clause_ids = {
            node.clause_id for node in outline.nodes if node.kind == "clause"
        }
        self.assertIn("7.4", clause_ids)
        self.assertIn("B.2.3", clause_ids)
        node_ids = {node.node_id for node in outline.nodes}
        self.assertIn("clause:B.2.3", node_ids)


class LinkerTests(unittest.TestCase):
    def test_explicit_reference_links_table(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 7.4 力学性能\n"
                    "棒材的力学性能应符合表3的规定。\n"
                    "\n表3 棒材的力学性能\n"
                ),
            )
        ]
        table = make_table("T4", 1, "表3 棒材的力学性能")
        result = build_links("doc", pages, [table])
        link = result.links[0]
        self.assertEqual(link.clause_id, "7.4")
        self.assertEqual(link.basis, "explicit")
        self.assertEqual(link.confidence, 1.0)
        self.assertEqual(result.coverage["link_rate"], 1.0)

    def test_fallback_to_nearest_heading(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown="## 7.6 显微组织\n\n表9 其他\n",
            )
        ]
        table = make_table("T9", 1, "表9 其他")
        result = build_links("doc", pages, [table])
        self.assertEqual(result.links[0].clause_id, "7.6")
        self.assertIn(result.links[0].basis, {"caption", "nearest"})

    def test_continuation_inherits_parent(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown="## 7.4 力学性能\n应符合表3的规定。\n\n表3 力学性能\n",
            ),
            Page(page_no=2, markdown="表3 力学性能（续）\n"),
        ]
        parent = make_table("T4", 1, "表3 力学性能")
        child = make_table("T6", 2, "表3 力学性能（续）", continuation_of="T4")
        result = build_links("doc", pages, [parent, child])
        child_link = next(item for item in result.links if item.table_id == "T6")
        self.assertEqual(child_link.clause_id, "7.4")
        self.assertEqual(child_link.basis, "continuation")

    def test_self_continuation_is_ignored(self) -> None:
        pages = [Page(page_no=1, markdown="## 7.4 力学性能\n")]
        table = make_table("T4", 1, None, continuation_of="T4")
        result = build_links("doc", pages, [table])
        self.assertNotEqual(result.links[0].basis, "continuation")


class ClauseFieldTests(unittest.TestCase):
    def test_sampling_method_temperature(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 5.2 取样数量\n"
                    "每批取3个试样，按GB/T 228.1进行试验，试验温度 室温。\n"
                ),
            )
        ]
        output = extract_clauses(pages, make_document())
        clause = output.clauses[0]
        self.assertIn("sample_quantity", clause.fields)
        self.assertEqual(clause.fields["method_standard"].text, "GB/T228.1")
        self.assertEqual(clause.fields["test_temperature"].text, "室温")

    def test_appendix_clause_and_requirement(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## B.2.3 力学性能\n"
                    "油气用棒材的力学性能应符合表B.3的规定。\n"
                    "## 7.5.1 低倍组织\n"
                    "棒材不允许有缩孔、裂纹。\n"
                ),
            )
        ]
        output = extract_clauses(pages, make_document())
        ids = {clause.clause_id for clause in output.clauses}
        self.assertIn("B.2.3", ids)
        self.assertIn("7.5.1", ids)

    def test_numeric_body_line_is_not_a_clause(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown="## 3.2 化学成分\n4006、4007、4015合金应符合表5的规定。\n",
            )
        ]
        output = extract_clauses(pages, make_document())
        ids = {clause.clause_id for clause in output.clauses}
        self.assertEqual(ids, {"3.2"})


class CoverageAuditTests(unittest.TestCase):
    def test_mentions_mapped_and_orphan_row(self) -> None:
        pages = [Page(page_no=1, markdown="## 7.4 力学性能\n应进行室温拉伸试验。\n")]
        table = make_table("T1", 1, "表1 力学性能")
        inventory = ItemInventory(
            doc_id="doc",
            items=[
                ItemInventoryEntry(
                    item_raw="室温拉伸",
                    item_canonical="室温拉伸",
                    item_family="tensile",
                    facets={"temperature": "室温"},
                    evidence=["T1:1"],
                )
            ],
        )
        links = TableLinkResult(
            doc_id="doc",
            links=[
                TableClauseLink(
                    table_id="T1",
                    clause_id="7.4",
                    basis="explicit",
                    confidence=1.0,
                )
            ],
            coverage={
                "tables": 1,
                "linked": 1,
                "explicit": 1,
                "nearest": 0,
                "unlinked": 0,
                "link_rate": 1.0,
            },
        )
        record = Record(record_id="r1", source_table_id="T1", grade="A")
        audit = build_coverage_audit(
            "doc", pages, [table], inventory, links, records=[record]
        )
        self.assertEqual(audit.stats["clause_mentions"], 1)
        self.assertEqual(audit.stats["clause_mentions_mapped"], 1)
        self.assertEqual(audit.stats["unmapped_mentions"], 0)
        self.assertEqual(audit.stats["orphan_rows"], 1)
        self.assertEqual(audit.status, "review")

    def test_unmapped_mention_is_gap(self) -> None:
        pages = [Page(page_no=1, markdown="应进行晶间腐蚀检验。\n")]
        inventory = ItemInventory(doc_id="doc", items=[])
        links = TableLinkResult(doc_id="doc", coverage={"link_rate": 1.0})
        audit = build_coverage_audit("doc", pages, [], inventory, links)
        self.assertEqual(audit.stats["unmapped_mentions"], 1)
        self.assertTrue(
            any(gap["type"] == "unmapped_mention" for gap in audit.gaps)
        )


if __name__ == "__main__":
    unittest.main()
