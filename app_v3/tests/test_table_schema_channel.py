from __future__ import annotations

from app_v3.channels.table_schema_channel import expand_table
from app_v3.table_program.ir import TableIR


def _ir():
    return TableIR.from_ocr({
        "table_id": "T1",
        "page_no": 1,
        "header_rows": 1,
        "header_paths": [["牌号"], ["状态"], ["厚度mm"], ["抗拉强度Rm/MPa"], ["硬度HV"]],
        "column_units": ["", "", "mm", "MPa", "HV"],
        "rows": [
            ["牌号", "状态", "厚度mm", "抗拉强度Rm/MPa", "硬度HV"],
            ["N4、N5", "M", "0.1~1.5", "≥345", "188~215"],
        ],
    })


def test_expand_table_descriptor():
    descriptor = {
        "id": "T1",
        "keys": [0, 1, 2],
        "cols": [
            {"i": 3, "k": "m", "m": "抗拉强度(Rm)", "u": "MPa", "op": "≥",
             "conds": [{"t": "temperature", "v": "室温"}], "cat": "室温拉伸"},
            {"i": 4, "k": "m", "m": "硬度值", "u": "HV", "op": "≤", "cat": "硬度试验"},
        ],
    }
    records = expand_table(_ir(), descriptor)
    assert len(records) == 4  # 2 牌号 × 2 度量列
    assert records[0]["category"] == "室温拉伸"
    assert records[0]["item"] == "抗拉强度(Rm)"
    assert records[0]["grade"] == "N4"
    assert records[0]["requirement"] == "≥345"
