from metal_doc_agent.contracts import (
    ClauseRecord,
    ExtractedValue,
    ItemInventoryEntry,
)
from metal_doc_agent.extraction.qwen import _implausible_property
from metal_doc_agent.schema_projection import (
    FEATURE_TABLE_PROFILES,
    _hanson_item_row,
    _implausible_item_requirement,
    _requirement_from_item_clauses,
    _requirement_from_tables,
)


def test_unit_header_and_chemistry_values_are_rejected() -> None:
    assert _implausible_property("Rm", "Rp0.2/MPa")
    assert _implausible_property("Rm", "A/%(5d)")
    assert _implausible_property("KV2", "KV2/J单个最小值")
    assert _implausible_property("Rm", "≥max.20ppm")
    assert _implausible_property("Rm", "锻件化学成分P、S含量（wt%）分别≤0.007%")


def test_implausible_hardness_and_plausible_values() -> None:
    assert _implausible_property("HB", "3.35")
    assert _implausible_property("HBW", "3.3~3.8")
    assert not _implausible_property("HB", "228~285")
    assert not _implausible_property("Rm", "≥620")
    assert not _implausible_property("A", "≥18")


def test_qualitative_table_requirement_lookup() -> None:
    tables = {
        "T4": {"table_id": "T4", "caption": "表4 低倍组织要求"},
        "T5": {"table_id": "T5", "caption": "表5 非金属夹杂物"},
    }
    assert _requirement_from_tables("低倍", tables) == "应符合表4 低倍组织要求的规定"
    assert _requirement_from_tables("非金属夹杂", tables) == "应符合表5 非金属夹杂物的规定"
    assert _requirement_from_tables("化学成分", tables) is None


def test_persistence_profiles_are_covered() -> None:
    assert "mechanical_properties" in FEATURE_TABLE_PROFILES["高温光滑持久"]
    assert "inspection" in FEATURE_TABLE_PROFILES["非金属夹杂"]


def test_requirement_falls_back_to_clause_sentence() -> None:
    clause = ClauseRecord(
        clause_id="5.1",
        title="力学性能",
        fields={
            "requirement": ExtractedValue(
                raw="抗拉强度Rm≥930MPa，断后伸长率A≥12%。",
                text="抗拉强度Rm≥930MPa，断后伸长率A≥12%。",
            )
        },
    )
    result = _requirement_from_item_clauses("抗拉强度 Rm", "室温拉伸", [clause])
    assert result is not None
    assert "≥930" in result
    assert _requirement_from_item_clauses("晶粒度", "晶粒度", [clause]) is None


def test_missing_requirement_never_crashes_row_projection() -> None:
    row = _hanson_item_row(
        ItemInventoryEntry(item_raw="晶粒度"),
        None,
        None,
        None,
        None,
        None,
        [],
        None,
    )
    assert row["标准要求"] == ""


def test_impact_energy_upper_bound() -> None:
    assert _implausible_item_requirement("冲击吸收功 KU2", "夏比冲击", "≥1020")
    assert not _implausible_item_requirement("冲击吸收功 KU2", "夏比冲击", "≥32")
    assert not _implausible_item_requirement("抗拉强度 Rm", "室温拉伸", "≥1020")
