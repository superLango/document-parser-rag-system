"""W2 Tier1: borderless table recovery from word coordinates."""

from services.ocr.algorithms.table_grid import parse_table
from services.ocr.algorithms.text_tables import build_table, build_table_html


def _words(rows: list[list[tuple[str, float, float]],], height: float = 12.0):
    words = []
    for row_index, row in enumerate(rows):
        y0 = 10.0 + row_index * 20.0
        for text, x0, width in row:
            words.append((x0, y0, x0 + width, y0 + height, text, 0, row_index, 0))
    return words


TABLE_ROWS = [
    [("牌号", 10.0, 40.0), ("Rm", 120.0, 30.0), ("A", 220.0, 20.0)],
    [("Q355B", 10.0, 45.0), ("470", 120.0, 25.0), ("22", 220.0, 20.0)],
    [("Q235B", 10.0, 45.0), ("400", 120.0, 25.0), ("26", 220.0, 20.0)],
    [("Q195", 10.0, 40.0), ("330", 120.0, 25.0), ("30", 220.0, 20.0)],
]


def test_borderless_table_is_recovered() -> None:
    table = build_table(_words(TABLE_ROWS))
    assert table is not None
    assert table.n_rows == 4
    assert table.n_cols == 3
    assert table.rows[1] == ["Q355B", "470", "22"]
    grid = parse_table(table.html, "T1", 1, caption="表1 力学性能")
    assert grid.n_cols == 3
    assert grid.header_rows == 1
    assert grid.profile == "mechanical_properties"


def test_prose_is_not_turned_into_a_table() -> None:
    words = []
    for line in range(4):
        y0 = 10.0 + line * 18.0
        for index in range(6):
            x0 = 10.0 + index * 26.0
            words.append((x0, y0, x0 + 20.0, y0 + 10.0, f"word{line}{index}", 0, line, 0))
    assert build_table_html(words) == ""


def test_bbox_limits_recovered_words() -> None:
    inside = _words(TABLE_ROWS)
    outside = [
        (400.0, 30.0, 460.0, 42.0, "噪声", 0, 0, 0),
        (400.0, 50.0, 460.0, 62.0, "99999", 0, 1, 0),
    ]
    table = build_table(inside + outside, bbox=[0.0, 0.0, 300.0, 100.0])
    assert table is not None
    assert table.n_cols == 3
    assert all("99999" not in cell for row in table.rows for cell in row)


def test_table_needs_numeric_cells() -> None:
    rows = [
        [("牌号", 10.0, 40.0), ("状态", 120.0, 30.0), ("备注", 220.0, 30.0)],
        [("Q355", 10.0, 40.0), ("正火", 120.0, 30.0), ("合格", 220.0, 30.0)],
        [("Q235", 10.0, 40.0), ("热轧", 120.0, 30.0), ("合格", 220.0, 30.0)],
        [("Q195", 10.0, 40.0), ("冷轧", 120.0, 30.0), ("合格", 220.0, 30.0)],
    ]
    # 牌号中的数字计入数字单元格；全部换成无数字牌号后应被拒绝。
    text_rows = [
        [("牌号", 10.0, 40.0), ("状态", 120.0, 30.0), ("备注", 220.0, 30.0)],
        [("甲", 10.0, 20.0), ("正火", 120.0, 30.0), ("合格", 220.0, 30.0)],
        [("乙", 10.0, 20.0), ("热轧", 120.0, 30.0), ("合格", 220.0, 30.0)],
        [("丙", 10.0, 20.0), ("冷轧", 120.0, 30.0), ("合格", 220.0, 30.0)],
    ]
    assert build_table_html(_words(text_rows)) == ""
    assert build_table(_words(rows)) is not None
