"""Document type routing (P6-A).

The type is decided from observable signals — cover text, section headings and
table headers — never from the file name or a particular standard number. That
keeps the rule set stable when a new customer document appears: it either falls
into a known type by its own wording or is reported as ``unknown`` instead of
being silently forced into the product-standard schema.

The result drives two decisions:

* which coverage template to use;
* whether product-schema projection applies at all (a heat-treatment check
  plan is explicitly out of scope and must be reported as ``not_applicable``
  rather than projected into empty rows).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import DocumentMeta, Page, TableGrid
from .tablegrid.normalize import clean_text

PRODUCT_STANDARD = "product_standard"
MANUFACTURING_OUTLINE = "manufacturing_outline"
PURCHASE_SPEC = "purchase_spec"
APPROVAL_TEST = "approval_test"
HEAT_TREATMENT_PLAN = "heat_treatment_plan"
PROCESS_DOCUMENT = "process_document"
UNKNOWN = "unknown"

TYPE_LABELS = {
    PRODUCT_STANDARD: "产品标准/技术条件",
    MANUFACTURING_OUTLINE: "制造大纲",
    PURCHASE_SPEC: "采购规范",
    APPROVAL_TEST: "批准试验要求",
    HEAT_TREATMENT_PLAN: "热处理检查计划",
    PROCESS_DOCUMENT: "工艺文件",
    UNKNOWN: "未识别",
}

TEMPLATE_BY_TYPE = {
    PRODUCT_STANDARD: "product_full",
    MANUFACTURING_OUTLINE: "product_full",
    PURCHASE_SPEC: "purchase",
    APPROVAL_TEST: "product_full",
    HEAT_TREATMENT_PLAN: "product_full",
    PROCESS_DOCUMENT: "enterprise",
    UNKNOWN: "product_full",
}

# Types whose content cannot be represented by the product schema. They keep
# their artifacts (tables/clauses/inspection items) but skip schema projection.
NOT_APPLICABLE_TYPES = {HEAT_TREATMENT_PLAN}

# Ordered: the first type with the highest score wins ties. Specific document
# kinds come before the generic product-standard fallback.
TYPE_ORDER = (
    HEAT_TREATMENT_PLAN,
    APPROVAL_TEST,
    PURCHASE_SPEC,
    MANUFACTURING_OUTLINE,
    PROCESS_DOCUMENT,
    PRODUCT_STANDARD,
)

TYPE_SIGNALS: dict[str, tuple[tuple[str, float], ...]] = {
    HEAT_TREATMENT_PLAN: (
        ("热处理检查计划", 0.9),
        ("检查组别", 0.8),
        ("抽检比例", 0.45),
        ("检查计划", 0.4),
    ),
    APPROVAL_TEST: (
        ("批准试验", 0.9),
        ("鉴定试验", 0.8),
        ("试验批", 0.45),
        ("试制批", 0.3),
    ),
    PURCHASE_SPEC: (
        ("采购规范", 0.9),
        ("采购技术规格书", 0.9),
        ("采购技术协议", 0.85),
        ("采购技术要求", 0.85),
        ("订货技术条件", 0.8),
        ("采购合同", 0.35),
        ("material specification", 0.85),
        ("purchase specification", 0.9),
    ),
    MANUFACTURING_OUTLINE: (
        ("制造大纲", 0.95),
        ("制造技术条件", 0.8),
        ("制造技术协议", 0.75),
        ("manufacturing outline", 0.9),
        ("制造工艺", 0.25),
        ("工艺路线", 0.2),
    ),
    PROCESS_DOCUMENT: (
        ("工艺规程", 0.9),
        ("作业指导书", 0.85),
        ("工艺过程卡", 0.8),
        ("工艺卡", 0.7),
        ("工序卡", 0.7),
        ("工艺文件", 0.6),
    ),
    PRODUCT_STANDARD: (
        ("本标准规定了", 0.6),
        ("本标准适用于", 0.6),
        ("规范性引用文件", 0.35),
        ("检验规则", 0.25),
        ("牌号和化学成分", 0.3),
    ),
}


@dataclass
class DocumentTypeResult:
    doc_type: str = UNKNOWN
    label: str = TYPE_LABELS[UNKNOWN]
    confidence: float = 0.0
    signals: list[str] = field(default_factory=list)
    coverage_template: str = "product_full"
    not_applicable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "doc_type": self.doc_type,
            "label": self.label,
            "confidence": round(self.confidence, 2),
            "signals": list(self.signals),
            "coverage_template": self.coverage_template,
            "not_applicable": self.not_applicable,
        }


def detect_document_type(
    document: DocumentMeta,
    pages: list[Page],
    tables: list[TableGrid] | None = None,
) -> DocumentTypeResult:
    """Classify the document from its own text and table headers."""

    table_text = _table_text(tables or [])
    head_text = _pages_text(pages, limit=2, max_chars=20000)
    full_text = _pages_text(pages, limit=None, max_chars=200000)

    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for doc_type in TYPE_ORDER:
        total = 0.0
        matched: list[str] = []
        for pattern, weight in TYPE_SIGNALS[doc_type]:
            where = _where(pattern, head_text, full_text, table_text)
            if where is None:
                continue
            # The cover page names the document; the same phrase deep in the
            # body is usually a reference to another document type
            # ("按采购合同…" inside a manufacturing outline).
            total += weight if where == "首页" else weight * 0.35
            matched.append(f"{pattern}({where})")
        if total:
            scores[doc_type] = total
            hits[doc_type] = matched

    _score_structural(document, tables or [], scores, hits)

    if not scores:
        return DocumentTypeResult()

    best = max(
        TYPE_ORDER,
        key=lambda name: (scores.get(name, 0.0), -TYPE_ORDER.index(name)),
    )
    confidence = min(1.0, scores[best])
    # A single weak phrase is not enough to claim a specific document type.
    if best != PRODUCT_STANDARD and confidence < 0.45:
        return DocumentTypeResult()
    return DocumentTypeResult(
        doc_type=best,
        label=TYPE_LABELS[best],
        confidence=confidence,
        signals=hits.get(best, [])[:8],
        coverage_template=TEMPLATE_BY_TYPE[best],
        not_applicable=best in NOT_APPLICABLE_TYPES,
    )


def _where(
    pattern: str, head: str, full: str, table_text: str
) -> str | None:
    needle = pattern.lower()
    if needle in head:
        return "首页"
    if needle in full:
        return "正文"
    if needle in table_text:
        return "表头"
    return None


def _score_structural(
    document: DocumentMeta,
    tables: list[TableGrid],
    scores: dict[str, float],
    hits: dict[str, list[str]],
) -> None:
    """Add signals that come from layout rather than prose."""

    profiles = [table.profile for table in tables]
    captions = clean_text(" ".join(table.caption or "" for table in tables))
    headers = clean_text(
        " ".join(
            " ".join(path)
            for table in tables
            for path in table.header_paths
        )
    )

    if "检查组别" in headers and any(
        marker in headers for marker in ("抽检", "检查比例", "抽检数量")
    ):
        scores[HEAT_TREATMENT_PLAN] = scores.get(HEAT_TREATMENT_PLAN, 0.0) + 0.5
        hits.setdefault(HEAT_TREATMENT_PLAN, []).append("检查组别×抽检比例(表头)")

    if "测试类别" in headers and "验收" in headers:
        scores[APPROVAL_TEST] = scores.get(APPROVAL_TEST, 0.0) + 0.3
        hits.setdefault(APPROVAL_TEST, []).append("测试类别×验收指标(表头)")

    if "制造大纲" in captions:
        scores[MANUFACTURING_OUTLINE] = scores.get(MANUFACTURING_OUTLINE, 0.0) + 0.4
        hits.setdefault(MANUFACTURING_OUTLINE, []).append("制造大纲(表题)")

    if document.standard_no and not scores:
        scores[PRODUCT_STANDARD] = 0.55
        hits[PRODUCT_STANDARD] = [f"标准号 {document.standard_no}"]

    if (
        "chemical_composition" in profiles
        and "mechanical_properties" in profiles
        and not scores
    ):
        scores[PRODUCT_STANDARD] = 0.5
        hits[PRODUCT_STANDARD] = ["化学成分表+力学性能表"]


def _pages_text(
    pages: list[Page], *, limit: int | None, max_chars: int
) -> str:
    selected = pages if limit is None else pages[:limit]
    parts: list[str] = []
    size = 0
    for page in selected:
        text = page.markdown or ""
        if size + len(text) > max_chars:
            parts.append(text[: max(0, max_chars - size)])
            break
        parts.append(text)
        size += len(text)
    return clean_text(" ".join(parts)).lower()


def _table_text(tables: list[TableGrid]) -> str:
    parts: list[str] = []
    for table in tables:
        if table.caption:
            parts.append(table.caption)
        for path in table.header_paths:
            parts.append(" ".join(path))
    return clean_text(" ".join(parts)).lower()
