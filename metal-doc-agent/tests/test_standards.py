import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.contracts import ReferenceEdge, ReferenceGraph
from metal_doc_agent.standards import (
    StandardRecord,
    StandardRegistry,
    load_registry,
    resolve_references,
)


def edge(standard_no: str, edition: str | None = None) -> ReferenceEdge:
    return ReferenceEdge(
        raw=f"{standard_no}-{edition}" if edition else standard_no,
        standard_no=standard_no,
        edition=edition,
        dated=bool(edition),
        relation="normative",
        page_no=4,
        clause_id="2",
    )


def registry() -> StandardRegistry:
    return StandardRegistry(
        records=[
            StandardRecord(
                standard_no="GB/T 40303",
                edition="2021",
                title="GH4169合金棒材通用技术条件",
                status="current",
                doc_id="gbt40303_2021",
            ),
            StandardRecord(
                standard_no="GB/T 3191",
                edition="2010",
                status="current",
                doc_id="gbt3191_2010",
                supersedes=("GB/T 3191-1998",),
            ),
            StandardRecord(
                standard_no="GB/T 3191",
                edition="1998",
                status="superseded",
                doc_id="gbt3191_1998",
            ),
            StandardRecord(
                standard_no="GJB 2294A",
                edition="2014",
                status="current",
                doc_id="gjb2294a_2014",
                supersedes=("GJB 2294-1995",),
            ),
            StandardRecord(
                standard_no="GJB 2294",
                edition="1995",
                status="superseded",
            ),
            StandardRecord(
                standard_no="DUP",
                edition="2020",
                status="current",
            ),
            StandardRecord(
                standard_no="DUP",
                edition="2021",
                status="current",
            ),
        ]
    )


class StandardsTests(unittest.TestCase):
    def test_dated_reference_resolves_exact_edition(self) -> None:
        graph = ReferenceGraph(
            doc_id="x", references=[edge("GB/T 40303", "2021")]
        )
        report = resolve_references(graph, registry())
        item = graph.references[0]
        self.assertTrue(item.resolved)
        self.assertEqual(item.resolved_doc_id, "gbt40303_2021")
        self.assertEqual(item.resolution_basis, "dated")
        self.assertEqual(item.status, "current")
        self.assertEqual(item.title, "GH4169合金棒材通用技术条件")
        self.assertEqual(report.resolved, 1)
        self.assertFalse(graph.gaps)

    def test_dated_superseded_reference_reports_successor(self) -> None:
        graph = ReferenceGraph(
            doc_id="x", references=[edge("GB/T 3191", "1998")]
        )
        resolve_references(graph, registry())
        item = graph.references[0]
        self.assertTrue(item.resolved)
        self.assertEqual(item.status, "superseded")
        self.assertEqual(item.superseded_by, "GB/T 3191-2010")

    def test_undated_reference_uses_current_edition(self) -> None:
        graph = ReferenceGraph(doc_id="x", references=[edge("GB/T 3191")])
        report = resolve_references(graph, registry())
        item = graph.references[0]
        self.assertTrue(item.resolved)
        self.assertEqual(item.edition, None)
        self.assertEqual(item.resolved_doc_id, "gbt3191_2010")
        self.assertEqual(item.resolution_basis, "undated-current")
        self.assertEqual(report.undated, 1)

    def test_undated_old_base_resolves_to_successor(self) -> None:
        graph = ReferenceGraph(doc_id="x", references=[edge("GJB 2294")])
        resolve_references(graph, registry())
        item = graph.references[0]
        self.assertTrue(item.resolved)
        self.assertEqual(item.resolved_doc_id, "gjb2294a_2014")
        self.assertEqual(item.resolution_basis, "undated-successor")

    def test_missing_edition_is_a_gap_not_a_guess(self) -> None:
        graph = ReferenceGraph(
            doc_id="x", references=[edge("GB/T 40303", "2018")]
        )
        report = resolve_references(graph, registry())
        item = graph.references[0]
        self.assertFalse(item.resolved)
        self.assertIsNone(item.resolved_doc_id)
        self.assertEqual(report.unresolved, 1)
        self.assertEqual(graph.gaps, ["GB/T 40303-2018（版本未入库）"])

    def test_unknown_standard_is_a_gap(self) -> None:
        graph = ReferenceGraph(doc_id="x", references=[edge("GB/T 228.1", "2021")])
        report = resolve_references(graph, registry())
        self.assertFalse(graph.references[0].resolved)
        self.assertEqual(report.unresolved, 1)
        self.assertEqual(graph.gaps, ["GB/T 228.1-2021（未入库）"])

    def test_multiple_current_editions_are_a_conflict(self) -> None:
        graph = ReferenceGraph(doc_id="x", references=[edge("DUP")])
        report = resolve_references(graph, registry())
        item = graph.references[0]
        self.assertFalse(item.resolved)
        self.assertEqual(item.status, "conflict")
        self.assertEqual(report.conflicts, 1)
        self.assertEqual(graph.gaps, ["DUP（多个现行版本）"])

    def test_load_registry_preserves_underscored_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "standards.json"
            path.write_text(
                json.dumps(
                    {
                        "standards": [
                            {
                                "standard_no": "Q/S 10-0537",
                                "edition": "2004",
                                "status": "current",
                                "doc_id": "qs10_0537_2004",
                                "source_file": "markdown/1c4c_x.md",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            registry = load_registry(path)
            resolution = registry.resolve("Q/S 10-0537", "2004")
            self.assertEqual(resolution.record.doc_id, "qs10_0537_2004")
            self.assertEqual(resolution.record.source_file, "markdown/1c4c_x.md")

    def test_version_report_markdown(self) -> None:
        graph = ReferenceGraph(
            doc_id="x",
            references=[edge("GB/T 40303", "2021"), edge("GB/T 228.1", "2021")],
        )
        report = resolve_references(graph, registry())
        markdown = report.to_markdown(graph)
        self.assertIn("# 版本解析报告：x", markdown)
        self.assertIn("| GB/T 40303 | 2021 |", markdown)
        self.assertIn("已解析", markdown)
        self.assertIn("未解析", markdown)


if __name__ == "__main__":
    unittest.main()
