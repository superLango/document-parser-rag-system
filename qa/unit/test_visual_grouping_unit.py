"""L1 单元测试：视觉归属——表格注行合并（MinerU 借鉴 P0）。"""

import pytest

from app.services.parsekit.types import BBox, LayoutBlock
from app.services.parsekit.visual_grouping import group_table_footnotes


def _block(block_type, x0, y0, x1, y1, page=1, structural=None):
    return LayoutBlock(
        type=block_type,
        bbox=BBox(x0, y0, x1, y1),
        page_index=page,
        confidence=0.9,
        structural=structural or {},
    )


def _table(y0=0.2, y1=0.5, x0=0.1, x1=0.9):
    return _block("table", x0, y0, x1, y1)


# ---------- 合并成功场景 ----------

def test_footnote_note_merged():
    """vision_footnote 注行（footnote 类型）紧贴表格底部 → 合并。"""
    table = _table(y1=0.5)
    note = _block("footnote", 0.15, 0.51, 0.85, 0.53)
    layouts, stats = group_table_footnotes([[table, note]])
    assert stats["merged_table_footnotes"] == 1
    assert len(layouts[0]) == 1  # 注行已移除
    assert layouts[0][0].bbox.y1 == pytest.approx(0.53)
    assert layouts[0][0].structural["merged_table_footnotes"] == 1


def test_text_note_merged():
    """text 通栏注行（宽度比≥0.85、单行、紧贴）→ 合并。"""
    table = _table(y1=0.5)
    note = _block("text", 0.12, 0.51, 0.88, 0.53)
    layouts, stats = group_table_footnotes([[table, note]])
    assert stats["merged_table_footnotes"] == 1
    assert layouts[0][0].bbox.y1 == pytest.approx(0.53)


def test_title_note_merged():
    """paragraph_title 映射的 title 通栏注行 → 合并（page18 场景）。"""
    table = _table(y1=0.5)
    note = _block("title", 0.12, 0.505, 0.88, 0.52)  # 宽度比 0.76/0.8=0.95
    layouts, stats = group_table_footnotes([[table, note]])
    assert stats["merged_table_footnotes"] == 1
    assert layouts[0][0].bbox.y1 == pytest.approx(0.52)


def test_footnote_multiline_merged():
    """多条 footnote 注行连续合并。"""
    table = _table(y1=0.5)
    n1 = _block("footnote", 0.15, 0.51, 0.85, 0.53)
    n2 = _block("footnote", 0.15, 0.54, 0.85, 0.56)
    layouts, stats = group_table_footnotes([[table, n1, n2]])
    assert stats["merged_table_footnotes"] == 2
    assert len(layouts[0]) == 1
    assert layouts[0][0].bbox.y1 == pytest.approx(0.56)


# ---------- 拒绝合并场景 ----------

def test_short_title_not_merged():
    """表格下方的短小节标题（宽度比<0.85）不合并。"""
    table = _table(y1=0.5)
    title = _block("title", 0.2, 0.51, 0.35, 0.53)  # 宽度比 0.15/0.8=0.19
    layouts, stats = group_table_footnotes([[table, title]])
    assert stats["merged_table_footnotes"] == 0
    assert len(layouts[0]) == 2


def test_paragraph_text_not_merged():
    """多行正文段落（高度>0.04）不合并。"""
    table = _table(y1=0.5)
    para = _block("text", 0.12, 0.51, 0.88, 0.58)  # 高度 0.07 > 0.04
    layouts, stats = group_table_footnotes([[table, para]])
    assert stats["merged_table_footnotes"] == 0
    assert len(layouts[0]) == 2


def test_table_at_page_bottom_not_merged():
    """表格延伸到页面底部（y1≥0.9）时不向下合并（防跨页误并）。"""
    table = _table(y0=0.8, y1=0.91)
    note = _block("footnote", 0.15, 0.92, 0.85, 0.94)
    _, stats = group_table_footnotes([[table, note]])
    assert stats["merged_table_footnotes"] == 0


def test_gap_too_large_not_merged():
    """注行与表格间隙过大（>0.02）不合并。"""
    table = _table(y1=0.5)
    note = _block("footnote", 0.15, 0.55, 0.85, 0.57)  # gap=0.05
    _, stats = group_table_footnotes([[table, note]])
    assert stats["merged_table_footnotes"] == 0


def test_intervening_block_stops_scan():
    """表格与注行之间有 caption/number 块时停止扫描。"""
    table = _table(y1=0.5)
    caption = _block("table_caption", 0.3, 0.51, 0.7, 0.53)
    note = _block("footnote", 0.15, 0.55, 0.85, 0.57)
    _, stats = group_table_footnotes([[table, caption, note]])
    assert stats["merged_table_footnotes"] == 0


def test_text_only_first_line_merged():
    """text/title 只合并首行，防止正文段落连锁误并。"""
    table = _table(y1=0.5)
    n1 = _block("text", 0.12, 0.51, 0.88, 0.53)
    n2 = _block("text", 0.12, 0.54, 0.88, 0.56)  # 正文第二行
    layouts, stats = group_table_footnotes([[table, n1, n2]])
    assert stats["merged_table_footnotes"] == 1
    assert len(layouts[0]) == 2  # 表格 + 未合并的第二行


def test_note_from_other_page_not_merged():
    """跨页块不合并。"""
    table = _table(y1=0.5)
    note = _block("footnote", 0.15, 0.51, 0.85, 0.53, page=2)
    _, stats = group_table_footnotes([[table, note]])
    assert stats["merged_table_footnotes"] == 0


# ---------- 表格内公式归并（防表格内容重复） ----------

def test_table_inner_formula_removed():
    """表格 bbox 内的 formula（单元格数据误检）移除，不独立输出。"""
    from app.services.parsekit.visual_grouping import merge_inline_formula_into_text

    table = _table(y0=0.3, y1=0.6)
    inner_formula = _block("formula", 0.3, 0.35, 0.45, 0.37)
    kept, removed = merge_inline_formula_into_text([[table, inner_formula]])
    assert removed == 1
    assert len(kept[0]) == 1
    assert kept[0][0].type == "table"


def test_table_outer_formula_kept():
    """表格外的独立公式保留。"""
    from app.services.parsekit.visual_grouping import merge_inline_formula_into_text

    table = _table(y0=0.3, y1=0.6)
    formula = _block("formula", 0.2, 0.7, 0.4, 0.75)  # 表格下方独立公式
    kept, removed = merge_inline_formula_into_text([[table, formula]])
    assert removed == 0
    assert len(kept[0]) == 2
    assert kept[0][1].type == "formula"
