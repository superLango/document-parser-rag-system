from metal_doc_agent.contracts import ClauseRecord, ExtractedValue, TableGrid
from metal_doc_agent.schema_projection import (
    _requirement_from_item_clauses,
    _requirement_from_qualitative_tables,
)
from metal_doc_agent.tablegrid.profile import classify_profile


def table(
    table_id: str,
    caption: str,
    header_paths: list[list[str]],
    rows: list[list[str]],
    profile: str = "inspection",
) -> dict:
    return {
        "table_id": table_id,
        "caption": caption,
        "profile": profile,
        "header_rows": 1,
        "header_paths": header_paths,
        "rows": rows,
    }


def test_intergranular_corrosion_table_profile_and_verdict() -> None:
    headers = [
        ["GB/T 20878中序号"],
        ["统一数字代号"],
        ["新牌号"],
        ["旧牌号"],
        ["GB/T 4334.2", "试验状态"],
        ["GB/T 4334.2", "腐蚀减重", "[g/(m2·h)]"],
        [""],
    ]
    grid = TableGrid(
        table_id="T14",
        page_no=17,
        caption="表12 晶间腐蚀试验",
        n_rows=3,
        n_cols=len(headers),
        header_rows=1,
        rows=[
            [path[-1] for path in headers],
            ["17", "S30408", "06Cr19Ni10", "0Cr18Ni9", "固溶处理", "协议", ""],
            ["18", "S30403", "022Cr19Ni10", "00Cr19Ni10", "敏化处理", "协议", ""],
        ],
        header_paths=headers,
        profile="unknown",
    )
    # The verdict column itself is empty in the header but carries the value.
    grid.rows[1][-1] = "不允许有晶间腐蚀裂纹"
    grid.rows[2][-1] = "不允许有晶间腐蚀裂纹"
    assert classify_profile(grid) == "inspection"

    requirement = _requirement_from_qualitative_tables(
        "晶间腐蚀",
        "晶间腐蚀",
        "全部牌号",
        {"T14": table("T14", grid.caption or "", headers, grid.rows)},
    )
    assert requirement == "不允许有晶间腐蚀裂纹"


def test_stress_corrosion_verdict_is_read_from_result_column() -> None:
    headers = [
        ["牌号"],
        ["状态"],
        ["壁厚a/mm"],
        ["试样受力方向"],
        ["试验应力/MPa"],
        ["试验时间/d"],
        ["结果要求"],
    ]
    rows = [
        [path[-1] for path in headers],
        ["7075", "T73", "≥20", "高向", "170", "≥20", "不出现裂纹"],
    ]
    requirement = _requirement_from_qualitative_tables(
        "应力腐蚀",
        "应力腐蚀",
        "7075",
        {"T11": table("T11", "表6 应力腐蚀性能", headers, rows)},
    )
    assert requirement == "不出现裂纹"


def test_intergranular_feature_does_not_borrow_stress_corrosion_table() -> None:
    headers = [["牌号"], ["状态"], ["结果要求"]]
    rows = [["牌号", "状态", "结果要求"], ["7075", "T73", "不出现裂纹"]]
    assert (
        _requirement_from_qualitative_tables(
            "晶间腐蚀",
            "晶间腐蚀",
            "全部牌号",
            {"T11": table("T11", "表6 应力腐蚀性能", headers, rows)},
        )
        is None
    )


def test_microstructure_clause_synonym_for_high_magnification() -> None:
    clause = ClauseRecord(
        clause_id="3.10.6",
        fields={
            "requirement": ExtractedValue(
                raw="型材的显微组织不准许过烧。",
                text="型材的显微组织不准许过烧。",
                comparator="text",
            )
        },
    )
    assert (
        _requirement_from_item_clauses("高倍组织", "高倍组织", [clause])
        == "型材的显微组织不准许过烧"
    )


def test_sampling_schedule_is_not_a_qualitative_verdict_table() -> None:
    headers = [["检验项目"], ["取样规定"], ["要求的章条号"], ["试验方法的章条号"]]
    rows = [
        ["检验项目", "取样规定", "要求的章条号", "试验方法的章条号"],
        ["晶间腐蚀", "每批抽取2根", "3.8", "4.7"],
    ]
    assert (
        _requirement_from_qualitative_tables(
            "晶间腐蚀",
            "晶间腐蚀",
            "全部牌号",
            {"T22": table("T22", "表11 型材的取样规定", headers, rows)},
        )
        is None
    )
