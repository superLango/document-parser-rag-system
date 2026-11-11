"""TableGrid extraction, profile detection and data-driven repairs."""

from services.ocr.algorithms.repairs import apply_repairs
from services.ocr.algorithms.table_grid import parse_table

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
