from __future__ import annotations

from services.ocr.algorithms.profile import classify_profile
from services.ocr.contracts import TableGrid


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
