import unittest

from metal_doc_agent.contracts import ReferenceEdge, ReferenceGraph
from metal_doc_agent.relevance import classify_reference, plan_references


def edge(
    standard_no: str,
    *,
    title: str | None = None,
    relation: str = "normative",
    edition: str | None = None,
) -> ReferenceEdge:
    return ReferenceEdge(
        raw=standard_no,
        standard_no=standard_no,
        title=title,
        edition=edition,
        dated=bool(edition),
        relation=relation,  # type: ignore[arg-type]
    )


class RelevanceTests(unittest.TestCase):
    def test_method_reference_by_title(self) -> None:
        item = edge("GB/T 223.5", title="钢铁及合金化学分析方法")
        self.assertEqual(classify_reference(item), "method")

    def test_method_reference_by_standard_prefix(self) -> None:
        self.assertEqual(classify_reference(edge("GB/T 228.1")), "method")

    def test_product_standard_is_schema(self) -> None:
        item = edge("GB/T 40303", title="GH4169合金棒材通用技术条件")
        self.assertEqual(classify_reference(item), "schema")

    def test_informative_is_not_expanded(self) -> None:
        item = edge("GB/T 1.1", title="标准化工作导则", relation="informative")
        self.assertEqual(classify_reference(item), "informative")

    def test_budget_selects_at_most_eight_documents(self) -> None:
        graph = ReferenceGraph(
            doc_id="x",
            references=[
                edge(f"GB/T {1000 + index}", title=f"产品标准{index}")
                for index in range(10)
            ],
        )
        plan_references(graph)
        selected = [item for item in graph.references if item.expand]
        excluded = [
            item for item in graph.references if item.selection_reason == "budget_exceeded"
        ]
        self.assertEqual(len(selected), 8)
        self.assertEqual(len(excluded), 2)
        self.assertTrue(graph.budget["exceeded"])
        self.assertEqual(graph.budget["selected_documents"], 8)

    def test_informative_reference_is_skipped(self) -> None:
        graph = ReferenceGraph(
            doc_id="x",
            references=[
                edge("GB/T 1.1", title="标准化工作导则", relation="informative"),
                edge("GB/T 40303", title="产品标准"),
            ],
        )
        plan_references(graph)
        informative = graph.references[0]
        self.assertFalse(informative.expand)
        self.assertEqual(informative.selection_reason, "informative")
        self.assertEqual(graph.budget["selected_documents"], 1)

    def test_duplicate_standard_counts_once(self) -> None:
        graph = ReferenceGraph(
            doc_id="x",
            references=[
                edge("GB/T 3191", title="产品标准", edition="1998"),
                edge("GB/T 3191", title="产品标准", edition="2010"),
            ],
        )
        plan_references(graph)
        self.assertEqual(graph.budget["selected_documents"], 1)
        self.assertEqual(
            sorted(item.selection_reason or "" for item in graph.references),
            ["duplicate", "selected"],
        )


if __name__ == "__main__":
    unittest.main()
