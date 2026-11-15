from services.orchestration.workflow import (
    ROUTE_AGENT_MAX_TABLES,
    apply_sibling_fallback,
    filter_tables_by_quality,
    select_agent_tables,
)


def _grid_dict(
    table_id: str,
    orientation: str = "grade_rows",
    n_cols: int = 7,
    quality: float = 1.0,
    flags: list[str] | None = None,
) -> dict:
    headers = [
        "牌号",
        "供应状态",
        "试样状态a",
        "厚度mm",
        "抗拉强度(Rm)MPa",
        "规定非比例延伸强度(Rp0.2)MPa",
        "断后伸长率%",
    ]
    return {
        "table_id": table_id,
        "page_no": 7,
        "profile": "mechanical_properties",
        "orientation": orientation,
        "n_cols": n_cols,
        "header_rows": 1,
        "header_paths": [[header] for header in headers],
        "rows": [headers, ["1A99", "O", "O", ">6.00~12.50", "≥60", "≥25", "≥20"]],
        "quality": quality,
        "quality_flags": flags or [],
    }


def _table(
    table_id: str,
    quality: float,
    flags: list[str] | None = None,
    profile: str = "mechanical_properties",
) -> dict:
    return {
        "table_id": table_id,
        "page_no": 1,
        "quality": quality,
        "quality_flags": flags or [],
        "profile": profile,
    }


def test_filter_tables_by_quality_splits_buckets() -> None:
    tables = [_table("T1", 1.0), _table("T2", 0.1, ["prose_fragment"]), _table("T3", 0.8)]
    kept, filtered = filter_tables_by_quality(tables, 0.25)
    assert [item["table_id"] for item in kept] == ["T1", "T3"]
    assert filtered[0]["table_id"] == "T2"
    assert filtered[0]["flags"] == ["prose_fragment"]


def test_filter_tables_by_quality_disabled() -> None:
    tables = [_table("T1", 0.0)]
    kept, filtered = filter_tables_by_quality(tables, 0.0)
    assert kept == tables
    assert filtered == []


def test_select_agent_tables_requires_property_profile_and_quality() -> None:
    pending = [
        (_table("T1", 0.9), {"table_id": "T1"}),
        (_table("T2", 0.9, profile="unknown"), {"table_id": "T2"}),
        (_table("T3", 0.5), {"table_id": "T3"}),
        (_table("T4", 0.9, ["prose_fragment"]), {"table_id": "T4"}),
        (_table("T5", 0.8, profile="chemical_composition"), {"table_id": "T5"}),
    ]
    selected = select_agent_tables(pending)
    assert [table["table_id"] for table, _ in selected] == ["T1", "T5"]


def test_select_agent_tables_is_capped() -> None:
    pending = [
        (_table(f"T{index}", 0.9), {"table_id": f"T{index}"})
        for index in range(ROUTE_AGENT_MAX_TABLES + 4)
    ]
    assert len(select_agent_tables(pending)) == ROUTE_AGENT_MAX_TABLES


def test_sibling_fallback_routes_low_confidence_property_table() -> None:
    assignments = [
        {
            "table_id": "T2",
            "recipe_id": "mechanical_properties_v1",
            "version": "1.6.51",
            "score": 0.7124,
            "margin": 0.7124,
            "runner_up": "chemical_composition_v1",
        },
        {"table_id": "T1", "recipe_id": None, "score": 0.5624},
    ]
    tables = {
        "T1": _grid_dict("T1", orientation="element_rows", n_cols=8),
        "T2": _grid_dict("T2"),
    }
    assert apply_sibling_fallback(assignments, tables) == 1
    assert assignments[1]["recipe_id"] == "mechanical_properties_v1"
    assert assignments[1]["status"] == "sibling"
    assert assignments[1]["score"] >= 0.6


def test_sibling_fallback_skips_blocked_quality_tables() -> None:
    assignments = [
        {
            "table_id": "T2",
            "recipe_id": "mechanical_properties_v1",
            "version": "1.6.51",
            "score": 0.7124,
            "margin": 0.7124,
        },
        {"table_id": "T1", "recipe_id": None, "score": 0.5624},
    ]
    tables = {
        "T1": _grid_dict("T1", flags=["prose_fragment"]),
        "T2": _grid_dict("T2"),
    }
    assert apply_sibling_fallback(assignments, tables) == 0
    assert assignments[1]["recipe_id"] is None
