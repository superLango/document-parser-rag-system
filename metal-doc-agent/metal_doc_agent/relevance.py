"""Reference relevance classification and 1-hop expansion budget (M1.5.3).

References are classified by title/standard-number markers and relation. Only
schema-related and method references are candidates for expansion, capped at
eight standards per document. Page budget is enforced when the referenced
document is actually available locally.
"""

from __future__ import annotations

from .contracts import ReferenceEdge, ReferenceGraph

SCHEMA_MARKERS = (
    "化学成分",
    "力学性能",
    "尺寸",
    "外形",
    "重量",
    "技术条件",
    "规范",
    "牌号",
    "状态",
    "交货",
    "检验规则",
    "包装",
    "标志",
    "质量证明书",
)
METHOD_MARKERS = (
    "试验方法",
    "化学分析",
    "分析方法",
    "测定",
    "拉伸",
    "冲击",
    "硬度",
    "弯曲",
    "持久",
    "蠕变",
    "探伤",
    "超声",
    "金相",
    "组织",
    "取样",
    "光谱",
    "分析",
)
METHOD_PREFIXES = (
    "GB/T 223",
    "GB/T 228",
    "GB/T 229",
    "GB/T 230",
    "GB/T 231",
    "GB/T 232",
    "GB/T 2039",
    "GB/T 2975",
    "GB/T 4338",
    "GB/T 6394",
    "GB/T 10561",
    "GB/T 16865",
    "GB/T 17432",
    "GB/T 20066",
    "GB/T 4162",
    "ASTM A604",
    "ASTM E",
    "HB 5220",
    "HB/Z 59",
    "GJB 5909",
)


def classify_reference(edge: ReferenceEdge) -> str:
    title = edge.title or ""
    if edge.relation == "informative":
        return "informative"
    if any(marker in title for marker in METHOD_MARKERS):
        return "method"
    standard_no = edge.standard_no or ""
    if any(standard_no.startswith(prefix) for prefix in METHOD_PREFIXES):
        return "method"
    if any(marker in title for marker in SCHEMA_MARKERS):
        return "schema"
    if edge.relation == "normative":
        return "schema"
    return "unknown"


def plan_references(
    graph: ReferenceGraph,
    max_documents: int = 8,
    max_pages: int = 30,
) -> ReferenceGraph:
    for edge in graph.references:
        edge.relevance = classify_reference(edge)

    priority = {"schema": 0, "method": 1, "unknown": 2, "informative": 3}
    ordered = sorted(
        graph.references,
        key=lambda edge: (
            priority.get(edge.relevance or "unknown", 9),
            0 if edge.relation == "normative" else 1,
            edge.standard_no or "",
        ),
    )

    selected: set[str] = set()
    selected_edges = 0
    exceeded = False
    for edge in ordered:
        key = edge.standard_no or edge.raw
        if edge.relevance == "informative":
            edge.expand = False
            edge.selection_reason = "informative"
            continue
        if key in selected:
            edge.expand = True
            edge.selection_reason = "duplicate"
            continue
        if len(selected) >= max_documents:
            edge.expand = False
            edge.selection_reason = "budget_exceeded"
            exceeded = True
            continue
        selected.add(key)
        selected_edges += 1
        edge.expand = True
        edge.selection_reason = "selected"

    graph.budget = {
        "max_documents": max_documents,
        "max_pages": max_pages,
        "selected_documents": len(selected),
        "selected_edges": selected_edges,
        "page_budget_used": None,
        "exceeded": exceeded,
    }
    return graph
