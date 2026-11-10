from metal_doc_agent.contracts import ClauseRecord, CrossStandardTask, ExtractedValue
from metal_doc_agent.cross_standard import (
    _iter_references,
    _normalize_item,
    _standard_parts,
)
from metal_doc_agent.cross_standard_expand import _extract_field
from metal_doc_agent.schema_projection import (
    _implausible_item_requirement,
    _requirement_from_chemical_sentence,
    _requirement_from_condition_tables,
)


def test_internal_standard_code_maps_to_equivalent() -> None:
    assert _standard_parts("410JX(通用)-D-S10-0318") == ("Q/S10-0318", None)
    assert _standard_parts("410JX（通用）-D-S12.1102") == ("Q/S12.1102", None)
    assert _standard_parts("410JX(通用)-D-S10-0318-2004") == (
        "Q/S10-0318",
        "2004",
    )


def test_clause_level_internal_reference_yields_task_field() -> None:
    line = (
        "每子炉批棒料切取头、尾部位进行高倍组织检查，"
        "按410JX(通用)-D-S10-0318标准要求和内控要求(表2)验收"
    )
    assert ("410JX(通用)-D-S10-0318", "标准要求") in list(
        _iter_references(line)
    )


def test_chemical_prose_sentence_for_enumerated_elements() -> None:
    clause = ClauseRecord(
        clause_id="3.1",
        title="化学成分",
        fields={
            "requirement": ExtractedValue(
                raw="P、S含量（wt%）分别≤0.007%。",
                text="P、S含量（wt%）分别≤0.007%。",
            )
        },
    )
    assert "≤0.007" in (_requirement_from_chemical_sentence("P", [clause]) or "")
    assert "≤0.007" in (_requirement_from_chemical_sentence("硫", [clause]) or "")
    assert _requirement_from_chemical_sentence("Cr", [clause]) is None


def test_item_name_is_trimmed_to_the_inspection_noun() -> None:
    assert _normalize_item("料切取头、尾部位进行高倍组织") == "高倍组织"
    assert _normalize_item("高、低倍组织") == "高、低倍组织"


def test_clause_sentinel_rejects_method_rows() -> None:
    task = CrossStandardTask(
        task_id="t",
        doc_id="d",
        inspection_item="化学成分",
        missing_fields=["标准要求"],
        requirement_standard="Q/S10-0318",
    )
    assert _extract_field("化学成分分析 GB/T223", "标准要求", task) is None
    hit = _extract_field("化学成分应满足表1的规定", "标准要求", task)
    assert hit is not None and hit["confidence"] == 0.85


def test_heading_merged_into_mechanical_value_is_rejected() -> None:
    assert _implausible_item_requirement("断后伸长率A", "室温拉伸", "≥3.7 低倍")
    assert not _implausible_item_requirement("抗拉强度 Rm", "室温拉伸", "≥1020")


def test_schedule_table_is_not_used_as_requirement() -> None:
    table = {
        "table_id": "T5",
        "caption": "表5 检验项目",
        "profile": "inspection",
        "header_rows": 1,
        "n_cols": 4,
        "header_paths": [["检验项目"], ["取样数量"], ["要求条号"], ["试验方法条号"]],
        "rows": [["低倍", "1件", "3.7", "4.3.3"]],
    }
    assert (
        _requirement_from_condition_tables(
            "低倍", "低倍", "GH907", {"T5": table}, ["GH907"]
        )
        is None
    )
