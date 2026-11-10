import json
from pathlib import Path

from metal_doc_agent.contracts import DocumentMeta, TableGrid
from metal_doc_agent.schema_projection import (
    _condition_cell_value,
    _requirement_from_condition_tables,
)
from metal_doc_agent.tablegrid.repairs import apply_table_repairs


def _horizontal_table() -> dict:
    return {
        "table_id": "T3",
        "caption": "表2",
        "profile": "dimension",
        "header_rows": 1,
        "n_cols": 6,
        "header_paths": [
            ["棒材直径in(mm)"],
            ["试样方向"],
            ["σbksi(MPa)"],
            ["σ0.2ksi(MPa)"],
            ["δ5%"],
            ["ψ%"],
        ],
        "rows": [
            [
                "棒材直径in(mm)",
                "试样方向",
                "σbksi(MPa)",
                "σ0.2ksi(MPa)",
                "δ5%",
                "ψ%",
            ],
            ["7(180)~10(254)", "横向", "195(1345)", "160(1100)", "12", "15"],
        ],
    }


def _vertical_table() -> dict:
    return {
        "table_id": "T5",
        "caption": "表3 力学性能",
        "profile": "mechanical_properties",
        "header_rows": 2,
        "n_cols": 6,
        "header_paths": [
            ["试验项目"],
            ["试验温度"],
            ["性能"],
            ["最小值"],
            ["最大值"],
            ["单位"],
        ],
        "rows": [
            ["试验项目", "试验温度", "性能", "规定值", "规定值", "规定值"],
            ["试验项目", "试验温度", "性能", "最小值", "最大值", "单位"],
            ["KV冲击试验", "0℃", "单个最小值", "40", "/", "J"],
            ["拉伸试验", "室温", "抗拉强度(Rm)", "760", "960", "MPa"],
        ],
    }


def test_horizontal_condition_table_uses_mpa_value() -> None:
    tables = {"T3": _horizontal_table()}
    result = _requirement_from_condition_tables(
        "抗拉强度 Rm", "室温拉伸", "S10", tables, ["S10"]
    )
    assert result is not None
    assert "1345MPa" in result
    assert "横向" in result
    assert "160(1100)" not in result
    yield_result = _requirement_from_condition_tables(
        "规定塑性延伸强度 Rp0.2", "室温拉伸", "S10", tables, ["S10"]
    )
    assert yield_result is not None and "1100MPa" in yield_result
    assert "195(1345)" not in yield_result
    assert "Rp0.2" not in yield_result


def test_vertical_condition_table_reads_min_max() -> None:
    tables = {"T5": _vertical_table()}
    result = _requirement_from_condition_tables(
        "室温拉伸", "室温拉伸", "12Cr13", tables, ["12Cr13"]
    )
    assert result is not None
    assert "760~960MPa" in result
    impact = _requirement_from_condition_tables(
        "夏比冲击", "夏比冲击", "12Cr13", tables, ["12Cr13"]
    )
    assert impact is not None and "≥40J" in impact


def test_high_temperature_column_is_not_reused_for_room_temperature() -> None:
    table = {
        "table_id": "T6",
        "caption": "表2 力学性能要求",
        "profile": "mechanical_properties",
        "header_rows": 4,
        "n_cols": 6,
        "header_paths": [
            ["热处理制度", "固溶：1000±10℃", "室温拉伸性能", "σb（MPa）"],
            ["热处理制度", "固溶：1000±10℃", "室温拉伸性能", "σs（MPa）"],
            ["热处理制度", "固溶：1000±10℃", "室温拉伸性能", "δ5（%）"],
            ["热处理制度", "固溶：1000±10℃", "室温拉伸性能", "HB(d)(mm)"],
            ["热处理制度", "固溶：1000±10℃", "高温拉伸性能", "温度(℃)"],
            ["热处理制度", "固溶：1000±10℃", "高温拉伸性能", "δ5(%)"],
        ],
        "rows": [
            ["热处理制度"] * 6,
            ["固溶：1000±10℃"] * 6,
            ["室温拉伸性能"] * 4 + ["高温拉伸性能"] * 2,
            ["σb（MPa）", "σs（MPa）", "δ5（%）", "HB(d)(mm)", "温度(℃)", "δ5(%)"],
            ["≥640", "≥240", "≥30", "≥4.00", "700", "≥30"],
        ],
    }
    room = _requirement_from_condition_tables(
        "抗拉强度 Rm", "室温拉伸", "GH3030", {"T6": table}, ["GH3030"]
    )
    assert room is not None and "≥640MPa" in room
    hot = _requirement_from_condition_tables(
        "抗拉强度 Rm", "高温拉伸", "GH3030", {"T6": table}, ["GH3030"]
    )
    assert hot is None


def test_caption_grade_guard_skips_other_grade() -> None:
    table = {
        "table_id": "T14",
        "caption": "表2 GH4202力学性能指标要求",
        "profile": "mechanical_properties",
        "header_rows": 1,
        "n_cols": 2,
        "header_paths": [["试验温度℃"], ["抗拉强度", "σb", "MPa", "不小于"]],
        "rows": [
            ["试验温度℃", "抗拉强度σbMPa不小于"],
            ["室温", "930"],
        ],
    }
    tables = {"T14": table}
    assert (
        _requirement_from_condition_tables(
            "抗拉强度 Rm", "室温拉伸", "S-07", tables, ["GH4202", "S-07"]
        )
        is None
    )
    hit = _requirement_from_condition_tables(
        "抗拉强度 Rm", "室温拉伸", "GH4202", tables, ["GH4202", "S-07"]
    )
    assert hit is not None and "≥930MPa" in hit


def test_vertical_condition_table_tolerates_none_cells() -> None:
    table = _vertical_table()
    table["rows"] = [
        [None, None, None, None, None, None],
        ["试验项目", "试验温度", "性能", "最小值", "最大值", "单位"],
        ["拉伸试验", "室温", "抗拉强度(Rm)", None, "960", "MPa"],
    ]
    result = _requirement_from_condition_tables(
        "室温拉伸", "室温拉伸", "12Cr13", {"T5": table}, ["12Cr13"]
    )
    assert result is None or "MPa" in result


def test_condition_value_rejects_text_and_hardness_diameter() -> None:
    assert _condition_cell_value("This material has 1 test material", "RM") is None
    assert _condition_cell_value("夏比V型缺口冲击试验(1)", "HB") is None
    assert _condition_cell_value("3.35", "HB(d)(mm)") is None
    assert _condition_cell_value("≥3.35", "硬度HBd") is None
    assert _condition_cell_value("760", "抗拉强度Rm/MPa") == "760MPa"
    assert _condition_cell_value("195(1345)", "σbksi(MPa)") == "1345MPa"


def test_notch_and_lateral_expansion_do_not_reuse_energy_column() -> None:
    table = {
        "table_id": "T4",
        "caption": "表3 棒材的力学性能",
        "profile": "mechanical_properties",
        "header_rows": 1,
        "n_cols": 2,
        "header_paths": [["取样方向"], ["冲击吸热能量KU1/J"]],
        "rows": [["取样方向", "冲击吸热能量KU1/J"], ["纵向", "32"]],
    }
    tables = {"T4": table}
    assert (
        _requirement_from_condition_tables(
            "KU5", "夏比冲击", "GH4169", tables, ["GH4169"]
        )
        is None
    )
    assert (
        _requirement_from_condition_tables(
            "侧膨胀值 lateral expansion", "夏比冲击", "GH4169", tables, ["GH4169"]
        )
        is None
    )


def test_vertical_table_without_header_row() -> None:
    table = {
        "table_id": "T6",
        "caption": "表4 试验及检验",
        "profile": "mechanical_properties",
        "header_rows": 1,
        "n_cols": 6,
        "header_paths": [
            ["硬度试验"],
            ["室温"],
            ["布氏硬度值"],
            ["规定值"],
            ["规定值"],
            ["单位"],
        ],
        "rows": [
            ["硬度试验", "室温", "布氏硬度值", "228", "285", "HBW"],
            ["注：(1)每组三个试样", "注：(1)每组三个试样", "注：(1)每组三个试样"],
        ],
    }
    result = _requirement_from_condition_tables(
        "布氏硬度 HBW", "布氏硬度", "12Cr13", {"T6": table}, ["12Cr13"]
    )
    assert result is not None
    assert "228~285HBW" in result


def test_vertical_table_skips_leading_numeric_condition() -> None:
    table = {
        "table_id": "T9",
        "caption": "表5 力学性能",
        "profile": "mechanical_properties",
        "header_rows": 1,
        "n_cols": 6,
        "header_paths": [["状态"], ["温度"], ["性能"], ["最小值"], ["最大值"], ["单位"]],
        "rows": [
            ["状态", "温度", "性能", "最小值", "最大值", "单位"],
            ["室温", "20", "抗拉强度(Rm)", "760", "960", "MPa"],
        ],
    }
    result = _requirement_from_condition_tables(
        "室温拉伸", "室温拉伸", "12Cr13", {"T9": table}, ["12Cr13"]
    )
    assert result is not None
    assert "760~960MPa" in result


def test_repairs_copy_rows_and_keep_header(tmp_path: Path) -> None:
    config = {
        "documents": {
            "DFHM-TEST": {
                "T2": {
                    "copy_rows_from": {"source": "T3", "from_row": 1},
                    "header_rows": 1,
                },
                "T3": {"keep_header_rows_only": True},
            }
        }
    }
    config_path = tmp_path / "repairs.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    tables = [
        TableGrid(
            table_id="T2",
            page_no=1,
            caption="表1 化学成分要求",
            header_rows=1,
            n_cols=2,
            rows=[["元素", "含量"]],
        ),
        TableGrid(
            table_id="T3",
            page_no=1,
            header_rows=1,
            n_cols=2,
            rows=[["元素", "含量"], ["碳", "0.08~0.15"], ["硅", "≤1.00"]],
        ),
    ]
    document = DocumentMeta(
        doc_id="x",
        source_path="x",
        file_name="13_DFHM-TEST采购规范.md",
    )
    repaired = apply_table_repairs(tables, document, config_path)
    by_id = {table.table_id: table for table in repaired}
    assert len(by_id["T2"].rows) == 3
    assert by_id["T2"].rows[1][0] == "碳"
    assert len(by_id["T3"].rows) == 1
