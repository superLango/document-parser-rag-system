from metal_doc_agent.contracts import (
    ClauseRecord,
    DocumentMeta,
    ExtractedValue,
    Page,
)
from metal_doc_agent.extraction.clauses import extract_clauses
from metal_doc_agent.schema_projection import (
    _citation_requirement,
    _clause_text,
    _method_from_citation,
)


def document() -> DocumentMeta:
    return DocumentMeta(
        doc_id="doc-1",
        source_path="sample.pdf",
        file_name="sample.pdf",
    )


def test_toc_entries_do_not_shadow_clause_body() -> None:
    pages = [
        Page(
            page_no=2,
            markdown=(
                "## 3.5 低倍组织 ..... 3\n"
                "## 3.6 晶粒度 ..... 3\n"
            ),
        ),
        Page(
            page_no=7,
            markdown=(
                "## 3.5 低倍组织\n\n"
                "在经酸浸的横向试样上检验低倍组织，不得有肉眼可见的"
                "空洞、针孔、裂纹、分层和外来夹杂。\n\n"
                "3.5.1 棒材直径大于100 mm时在毛坯熔检试样上检验。\n"
            ),
        ),
    ]
    output = extract_clauses(pages, document())
    clause = next(item for item in output.clauses if item.clause_id == "3.5")
    assert clause.page_no == 7
    assert "....." not in (clause.title or "")
    requirement = clause.fields["requirement"]
    assert requirement.raw.startswith("在经酸浸的横向试样上")
    assert "不得有肉眼可见" in requirement.raw


def test_negative_phrases_are_kept_as_requirements() -> None:
    pages = [
        Page(
            page_no=13,
            markdown=(
                "## 4.1 显微组织\n\n"
                "型材的显微组织不准许过烧。\n\n"
                "## 4.2 表面质量\n\n"
                "棒材表面不应有裂纹和折叠。\n\n"
                "## 4.3 低倍组织\n\n"
                "低倍组织不得有肉眼可见的缩孔。\n\n"
                "## 4.4 塔形\n\n"
                "塔形发纹不应超过三级。\n"
            ),
        )
    ]
    output = extract_clauses(pages, document())
    requirements = {
        item.clause_id: item.fields["requirement"].raw
        for item in output.clauses
        if "requirement" in item.fields
    }
    assert "不准许过烧" in requirements["4.1"]
    assert "不应有裂纹" in requirements["4.2"]
    assert "不得有肉眼可见" in requirements["4.3"]
    assert "不应超过三级" in requirements["4.4"]


def test_clause_text_falls_back_to_generic_text_field() -> None:
    clause = ClauseRecord(
        clause_id="3.9",
        fields={
            "text": ExtractedValue(
                raw="型材经剥落腐蚀试验时不应出现EB~ED级。",
                text="型材经剥落腐蚀试验时不应出现EB~ED级。",
                comparator="text",
            )
        },
    )
    assert _clause_text(clause) == "型材经剥落腐蚀试验时不应出现EB~ED级。"


def test_citation_resolves_from_clause_fields() -> None:
    clauses = [
        ClauseRecord(
            clause_id="4.4.2",
            title="高温拉伸",
            fields={
                "requirement": ExtractedValue(
                    raw="高温拉伸试验按GB/T 4338的规定进行。",
                    text="高温拉伸试验按GB/T 4338的规定进行。",
                    comparator="text",
                )
            },
        )
    ]
    assert (
        _citation_requirement("4.4.2", clauses)
        == "高温拉伸试验按GB/T 4338的规定进行。"
    )
    assert _method_from_citation("见4.4.2", clauses) == "GB/T 4338"


def test_citation_falls_back_to_page_text() -> None:
    pages_text = (
        "## 4.4.2 高温拉伸\n\n"
        "高温拉伸试验按GB/T 4338的规定进行。\n\n"
        "## 4.4.3 高温持久\n\n"
        "按GB/T 2039的规定进行。\n"
    )
    assert "GB/T 4338" in (_citation_requirement("4.4.2", [], pages_text) or "")
    assert _method_from_citation("4.4.2", [], pages_text) == "GB/T 4338"


def test_unresolved_citation_is_not_invented() -> None:
    assert _citation_requirement("4.4.2", [], "## 3.5 低倍组织\n\n不得有缩孔。") is None
    assert _method_from_citation("4.4.2", [], "") is None
    assert (
        _citation_requirement(
            "3.11", [ClauseRecord(clause_id="3.11", title="显微组织")]
        )
        is None
    )
