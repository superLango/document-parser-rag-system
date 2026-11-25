from __future__ import annotations

from app_v3.table_program.ir import TableIR, load_tables


def test_table_ir_from_ocr():
    table = {
        "table_id": "T9",
        "page_no": 9,
        "caption": "表7 室温力学性能",
        "header_rows": 2,
        "header_paths": [["牌号"], ["状态"], ["厚度mm"], ["室温拉伸性能", "抗拉强度Rm/MPa"]],
        "column_units": ["", "", "mm", "MPa"],
        "column_conditions": ["", "状态", "规格", "温度"],
        "rows": [
            ["牌号", "状态", "厚度mm", "抗拉强度Rm/MPa"],
            ["", "", "", ""],
            ["N4", "M", "0.1~1.5", "≥345"],
        ],
    }
    ir = TableIR.from_ocr(table)
    assert ir.table_id == "T9"
    assert ir.width == 4
    assert ir.header_rows == 2
    assert ir.data_rows[0][1][0] == "N4"
    assert ir.column_header(3) == "室温拉伸性能 抗拉强度Rm/MPa"
    assert ir.column_path(0) == ["牌号"]
    assert ir.unit(3) == "MPa"
    assert ir.cell(2, 0) == "N4"


def test_load_tables():
    ocr = {"tables": [{"table_id": "T1", "rows": [["A"], ["1"]]}]}
    tables = load_tables(ocr)
    assert "T1" in tables
    assert tables["T1"].header_rows == 1
