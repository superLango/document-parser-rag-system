"""TableGrid extraction, profile detection and data-driven repairs."""

from services.ocr.algorithms.quality import score_table
from services.ocr.algorithms.repairs import apply_repairs
from services.ocr.algorithms.table_grid import parse_table
from services.ocr.contracts import TableGrid

MECHANICAL_HTML = """
<table>
<tr><th>牌号</th><th>抗拉强度 Rm/MPa</th><th>断后伸长率 A/%</th></tr>
<tr><td>Q355B</td><td>470</td><td>22</td></tr>
<tr><td>Q235B</td><td>400</td><td>26</td></tr>
</table>
"""

MERGED_HTML = """
<table>
<tr><th rowspan="2">牌号</th><th colspan="2">力学性能</th></tr>
<tr><th>Rm/MPa</th><th>A/%</th></tr>
<tr><td>Q355B</td><td>470</td><td>22</td></tr>
</table>
"""

CHEMICAL_HTML = """
<table>
<tr><th>牌号</th><th>C</th><th>Si</th><th>Mn</th><th>P</th><th>S</th></tr>
<tr><td>Q355B</td><td>0.20</td><td>0.55</td><td>1.60</td><td>0.035</td><td>0.035</td></tr>
</table>
"""

BLOCK_CHEMICAL_HTML = """
<table>
<tr><th rowspan="3">牌号</th><th colspan="2">C</th>
<th rowspan="3">Si/%</th><th rowspan="3">厚度/mm</th></tr>
<tr><th colspan="2">公称厚度/mm</th></tr>
<tr><th>≤16</th><th>&gt;16~40</th></tr>
<tr><td>Q355B</td><td>0.20</td><td>0.22</td><td>0.55</td><td>5</td></tr>
</table>
"""


def test_parse_simple_table() -> None:
    table = parse_table(MECHANICAL_HTML, "T1", 1, caption="表1 力学性能")
    assert table.n_cols == 3
    assert table.header_rows == 1
    assert table.rows[1] == ["Q355B", "470", "22"]
    assert table.units == ["MPa", "%"]
    assert table.profile == "mechanical_properties"
    assert table.orientation == "grade_rows"
    assert table.blocks and table.blocks[0].block_id == "T1-B1"


def test_rowspan_colspan_expansion() -> None:
    table = parse_table(MERGED_HTML, "T2", 1, caption="表2 力学性能")
    assert table.n_cols == 3
    assert table.header_rows == 2
    assert table.header_paths[0] == ["牌号"]
    assert table.header_paths[1] == ["力学性能", "Rm/MPa"]
    assert table.header_paths[2] == ["力学性能", "A/%"]
    assert table.rows[2] == ["Q355B", "470", "22"]


def test_chemical_profile_from_element_columns() -> None:
    table = parse_table(CHEMICAL_HTML, "T3", 1, caption="表3 化学成分")
    assert table.profile == "chemical_composition"


def test_column_metadata_for_mechanical_table() -> None:
    table = parse_table(MECHANICAL_HTML, "T6", 1, caption="表1 力学性能")
    assert table.column_units == ["", "MPa", "%"]
    assert table.column_conditions == ["", "", ""]
    assert table.column_elements == ["", "", ""]


def test_column_metadata_inherits_condition_and_element() -> None:
    table = parse_table(BLOCK_CHEMICAL_HTML, "T7", 1, caption="表1 化学成分")
    assert table.column_elements == ["", "C", "C", "Si", ""]
    assert table.column_conditions == ["", "规格", "规格", "", "规格"]
    # 元素列的单位不能取厚度条件上的 mm。
    assert table.column_units == ["", "", "", "%", "mm"]
    assert table.blocks[0].column_elements == table.column_elements


def test_column_units_ignore_offset_and_gauge_qualifiers() -> None:
    html = """
    <table>
      <tr><th>UNS</th><th>Yield Strength at 0.2% Offset ksi</th>
      <th>Elongation in 2 in. or 50 mm</th></tr>
      <tr><td>N06625</td><td>60</td><td>30</td></tr>
    </table>
    """
    table = parse_table(html, "T8", 1, caption="Mechanical properties")
    # "0.2%" 与 "50 mm" 是限定语，不能成为列单位；ksi 必须被识别。
    assert table.column_units == ["", "ksi", "%"]


def test_repair_rule_patch_cells() -> None:
    table = parse_table(MECHANICAL_HTML, "T4", 1, caption="表1 力学性能")
    rules = [
        {
            "rule_id": "fix-rm",
            "match": {"table_caption": "力学性能"},
            "action": {
                "type": "patch_cells",
                "cells": [{"row": 1, "col": 1, "value": "475"}],
            },
        }
    ]
    tables, applied = apply_repairs([table], rules=rules)
    assert applied == ["fix-rm"]
    assert tables[0].rows[1][1] == "475"


def test_repair_rule_rebuild_grid() -> None:
    table = parse_table(MECHANICAL_HTML, "T5", 1, caption="表1 力学性能")
    rules = [
        {
            "rule_id": "rebuild",
            "match": {"table_caption": "力学性能"},
            "action": {"type": "rebuild_grid", "rows": 2, "columns": 3},
        }
    ]
    tables, applied = apply_repairs([table], rules=rules)
    assert applied == ["rebuild"]
    assert tables[0].n_rows == 2
    assert tables[0].n_cols == 3
    assert tables[0].rows[0] == ["牌号", "抗拉强度 Rm/MPa", "断后伸长率 A/%"]


def test_quality_scores_record_table_high() -> None:
    table = parse_table(MECHANICAL_HTML, "T9", 1)
    score, flags = score_table(table)
    assert score >= 0.9
    assert not flags


def test_quality_rejects_prose_fragment() -> None:
    text = "3.2.3 Micrometers: Electronic micrometers, laser micrometers and probes."
    table = TableGrid(
        table_id="T9",
        page_no=1,
        n_cols=1,
        n_rows=2,
        header_rows=1,
        header_paths=[[text]],
        rows=[[text], [text]],
    )
    score, flags = score_table(table)
    assert score < 0.25
    assert "prose_fragment" in flags
