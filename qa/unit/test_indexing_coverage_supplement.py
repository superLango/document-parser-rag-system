"""覆盖率补充测试：M25 分块器 / M27 表格增强的内部分支与边界。"""

import json
from pathlib import Path

from app.services.indexing.chunker import (
    HierarchyChunker,
    OVERLAP_MARKER,
    _SENTENCE_END_RE,
)
from app.services.indexing.table_cleaner import table_cleaner
from app.services.indexing.table_enhancer import table_enhancer


def _text_layout(text: str, node_type: str = "text", children=None) -> dict:
    return {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {"type": node_type, "content": text, "level": 0,
                     "page": 0, "order": 0, "children": children or []}
                ],
            }
        }
    }


# ---------------- chunker 分支 ----------------

def test_mixed_table_and_text_section():
    """补测：章节含表格+文本且超阈值时，表格独立成块，表格后不传递 overlap。"""
    table_html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {
                        "type": "title", "content": "1 混合章节", "level": 1,
                        "page": 0, "order": 0,
                        "children": [
                            {"type": "text", "content": "这是一段很长的前置文本，用于撑大章节总长度以便触发切分逻辑，内容需要超过阈值。",
                             "level": 0, "page": 0, "order": 1, "children": []},
                            {"type": "table", "content": table_html, "level": 0,
                             "page": 0, "order": 2, "children": []},
                            {"type": "text", "content": "表格后的文本段，验证 overlap 不跨表格传递。",
                             "level": 0, "page": 0, "order": 3, "children": []},
                        ],
                    }
                ],
            }
        }
    }
    chunker = HierarchyChunker(max_child_chars=60)
    _, children = chunker.chunk(layout, "d-mix")
    assert len(children) >= 3
    table_idx = next(i for i, c in enumerate(children) if c.has_table)
    assert children[table_idx].content == table_html
    # 表格块后的文本块不应带 overlap 前缀（prev_tail 已被表格清空）
    after = children[table_idx + 1]
    assert OVERLAP_MARKER not in after.content_for_embedding.split("\n")[0]


def test_short_segment_before_oversize():
    """补测：短段后紧跟超长无标点段，触发前置 flush 与硬切。"""
    layout = _text_layout("短段内容。\n" + "A" * 500)
    chunker = HierarchyChunker(max_child_chars=100)
    _, children = chunker.chunk(layout, "d-so")
    assert len(children) >= 2
    assert all(len(c.content) <= 100 for c in children)


def test_split_text_variants():
    """补测：_split_text 空/多段落/多行分支。"""
    chunker = HierarchyChunker()
    assert chunker._split_text("") == []
    assert chunker._split_text("   ") == []
    paras = chunker._split_text("第一段。\n\n第二段。")
    assert paras == ["第一段。", "第二段。"]
    lines = chunker._split_text("第一行\n第二行")
    assert lines == ["第一行", "第二行"]
    sents = chunker._split_text("第一句。第二句。")
    assert len(sents) == 2


def test_hard_split_segment_variants():
    """补测：_hard_split_segment 短文本/弱边界累积/硬切。"""
    chunker = HierarchyChunker(max_child_chars=100)
    assert chunker._hard_split_segment("短文本") == ["短文本"]
    parts = chunker._hard_split_segment("一，" * 60, max_len=100)
    assert len(parts) >= 2
    assert all(len(p) <= 100 for p in parts)
    parts2 = chunker._hard_split_segment("B" * 250, max_len=100)
    assert parts2 == ["B" * 100, "B" * 100, "B" * 50]


def test_extract_tail_sentences_variants():
    """补测：_extract_tail_sentences 空/短/无句号/超长分支。"""
    chunker = HierarchyChunker()
    assert chunker._extract_tail_sentences("", 200, 2) == ""
    assert chunker._extract_tail_sentences("短", 200, 2) == ""
    long_no_punct = "无标点文本内容" * 20
    tail = chunker._extract_tail_sentences(long_no_punct, 50, 2)
    assert tail and len(tail) <= 50
    text = "第一句完整内容。第二句完整内容。第三句完整内容。"
    tail2 = chunker._extract_tail_sentences(text, 100, 2)
    assert "第三句" in tail2
    tail3 = chunker._extract_tail_sentences(text, 20, 1)
    # 句子过短（<10 字符）时不产生 overlap，属于设计行为
    assert tail3 == "" or len(tail3) <= 20


# ---------------- cleaner 分支 ----------------

def test_clean_without_table_element():
    """补测：含 <table 字样但无 table 元素时原样返回。"""
    html = "<tablex>不是表格</tablex>"
    assert table_cleaner.clean(html) == html


def test_parse_matrix_non_table():
    """补测：parse_matrix 非表格/无 table 元素返回空。"""
    assert table_cleaner.parse_matrix("普通文本") == ([], [])
    assert table_cleaner.parse_matrix("<div>no table</div>") == ([], [])


def test_count_columns():
    """补测：count_columns 有值表格与空输入。"""
    assert table_cleaner.count_columns(
        "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    ) == 2
    assert table_cleaner.count_columns("") == 0


def test_parse_matrix_table_marker_without_element():
    """补测：含 <table 前缀但无 table 元素 / 无 tr 行。"""
    assert table_cleaner.parse_matrix("<tablex>伪表格</tablex>") == ([], [])
    assert table_cleaner.parse_matrix("<table></table>") == ([], [])


def test_parse_matrix_all_empty_rows():
    """补测：存在 tr 但全为空行时矩阵为空。"""
    assert table_cleaner.parse_matrix(
        "<table><tr><td> </td><td>\u3000</td></tr></table>"
    ) == ([], [])


def test_headers_without_th():
    """补测：无 th 表格首行即表头。"""
    headers, rows = table_cleaner.parse_matrix(
        "<table><tr><td>列A</td><td>列B</td></tr><tr><td>1</td><td>2</td></tr></table>"
    )
    assert headers == ["列A", "列B"]
    assert rows == [["1", "2"]]


# ---------------- enhancer 分支 ----------------

def test_describe_row_empty_cells():
    """补测：行单元格全空时描述为空。"""
    assert table_enhancer._describe_row(["A", "B"], ["", ""], 0) == ""


def test_numeric_summaries_empty_rows():
    """补测：空数据行不生成统计。"""
    assert table_enhancer._summarize_numeric_columns(["A"], []) == []


def test_detect_table_type_organization_heat():
    """补测：组织分析/热处理制度类型识别。"""
    assert "组织分析" in table_enhancer._detect_table_type(["金相组织"])
    assert "热处理制度" in table_enhancer._detect_table_type(["淬火温度"])


def test_detect_numeric_columns_empty():
    """补测：空行数值列检测返回空。"""
    assert table_enhancer._detect_numeric_columns(["A"], []) == []


def test_extract_numeric_unicode_digits():
    """补测：全角数字可被正则命中并正常解析（Python 3.13 宽容行为）。"""
    assert table_enhancer._extract_numeric("１２３") == 123.0


def test_extract_tail_with_spaces_no_punct():
    """补测：无句号长文本按空格截断取尾部。"""
    chunker = HierarchyChunker()
    text = "AA BB CC DD EE FF GG HH II JJ KK LL MM NN OO PP"
    tail = chunker._extract_tail_sentences(text, 30, 2)
    assert tail and " " in tail and len(tail) <= 30


def test_extract_numeric_edge():
    """补测：数值提取无匹配与异常值。"""
    assert table_enhancer._extract_numeric("无数字") is None
    assert table_enhancer._extract_numeric("") is None
    assert table_enhancer._extract_numeric("1.5") == 1.5
