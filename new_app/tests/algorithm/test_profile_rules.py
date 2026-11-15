from __future__ import annotations

from services.ocr.algorithms.profile import classify_profile, detect_orientation
from services.ocr.contracts import TableGrid


def test_transposed_composition_with_leading_label_columns() -> None:
    rows = [
        ["牌号", "牌号", "Co9998", "Co9995", "Co9980"],
        ["化学成分/%", "Co不小于", "99.98", "99.95", "99.80"],
        ["化学成分/%", "杂质含量不大于", "C", "0.004", "0.005"],
        ["化学成分/%", "杂质含量不大于", "S", "0.001", "0.001"],
        ["化学成分/%", "杂质含量不大于", "Mn", "0.001", "0.005"],
        ["化学成分/%", "杂质含量不大于", "Fe", "0.003", "0.006"],
    ]
    table = TableGrid(
        table_id="T33",
        page_no=3,
        header_rows=1,
        header_paths=[["牌号"], ["牌号"], ["Co9998"], ["Co9995"], ["Co9980"]],
        n_cols=5,
        rows=rows,
    )
    assert classify_profile(table) == "chemical_composition"
    assert detect_orientation(table) == "element_rows"


def test_temper_o_column_is_not_an_element_row() -> None:
    rows = [
        ["牌号", "供应状态", "试样状态a", "厚度mm", "抗拉强度(Rm)MPa"],
        ["1A99", "O", "O", ">6.00~12.50", "≥60"],
        ["1A99", "O", "O", ">12.50~20.00", "≥60"],
        ["1A99", "O", "O", ">20.00~25.00", "≥60"],
    ]
    table = TableGrid(
        table_id="T1",
        page_no=7,
        header_rows=1,
        header_paths=[
            ["牌号"],
            ["供应状态"],
            ["试样状态a"],
            ["厚度mm"],
            ["抗拉强度(Rm)MPa"],
        ],
        n_cols=5,
        rows=rows,
    )
    assert detect_orientation(table) == "grade_rows"


def test_composition_tolerance_table_is_admin() -> None:
    table = TableGrid(
        table_id="T1",
        page_no=1,
        header_rows=1,
        header_paths=[["元素"], ["C"], ["Cr"], ["Mn"], ["允许偏差"]],
        n_cols=5,
        rows=[
            ["元素", "C", "Cr", "Mn", "允许偏差"],
            ["标准", "≤0.01", "≤0.15", "≤0.20", "-0.01"],
        ],
    )
    assert classify_profile(table) == "admin"
