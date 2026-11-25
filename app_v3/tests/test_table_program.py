from __future__ import annotations

from app_v3.table_program.engine import execute_program
from app_v3.table_program.ir import TableIR
from app_v3.table_program.replay import validate_program


def _ir():
    return TableIR.from_ocr({
        "table_id": "T9",
        "page_no": 9,
        "header_rows": 2,
        "header_paths": [["牌号"], ["状态"], ["厚度mm"], ["室温拉伸性能", "抗拉强度Rm/MPa"]],
        "column_units": ["", "", "mm", "MPa"],
        "rows": [
            ["牌号", "状态", "厚度mm", "抗拉强度Rm/MPa"],
            ["", "", "", ""],
            ["N4、N5", "M", "0.1~1.5", "≥345"],
            ["N6", "Y", "0.1~1.5", "-"],
        ],
    })


def test_melt_engine_records():
    program = {
        "steps": [
            {"op": "melt", "id_columns": [0, 1, 2],
             "value_columns": [{"column": 3, "measure": "抗拉强度(Rm)", "unit": "MPa",
                                "conditions": {"试验温度": "室温"}}]},
        ]
    }
    records = execute_program(program, _ir())
    assert len(records) == 1
    assert records[0]["raw"] == "≥345"
    assert records[0]["measure"] == "抗拉强度(Rm)"
    assert records[0]["unit"] == "MPa"


def test_explode_then_melt():
    program = {
        "steps": [
            {"op": "explode", "column": 0},
            {"op": "melt", "id_columns": [0, 1, 2],
             "value_columns": [{"column": 3, "measure": "抗拉强度(Rm)", "unit": "MPa"}]},
        ]
    }
    records = execute_program(program, _ir())
    # N4/N5 两行 + N6 一行（N6 值为 "-" 被跳过）
    assert len(records) == 2
    assert {record["key_values"]["0"] for record in records} == {"N4", "N5"}


def test_replay_coverage():
    program = {
        "steps": [
            {"op": "melt", "id_columns": [0, 1, 2],
             "value_columns": [{"column": 3, "measure": "抗拉强度(Rm)", "unit": "MPa"}]},
        ]
    }
    ir = _ir()
    records = execute_program(program, ir)
    valid = validate_program(program, ir, records)
    assert valid["ok"] is True
    assert valid["coverage"] == 1.0


def test_replay_missing_detected():
    program = {
        "steps": [
            {"op": "melt", "id_columns": [0, 1, 2],
             "value_columns": [{"column": 3, "measure": "抗拉强度(Rm)", "unit": "MPa"}]},
        ]
    }
    ir = _ir()
    records = []
    valid = validate_program(program, ir, records)
    assert valid["ok"] is False
    assert valid["missing"]
    assert valid["coverage"] < 1.0
