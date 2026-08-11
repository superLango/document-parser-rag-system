"""L4 边界异常：M25 分块器 + M27 表格增强。"""

import json
from pathlib import Path

from app.services.indexing.chunker import HierarchyChunker
from app.services.indexing.table_cleaner import table_cleaner
from app.services.indexing.table_enhancer import table_enhancer

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "layout_sample.json").read_text(
        encoding="utf-8"
    )
)


def _tree_layout(tree: dict) -> dict:
    return {"rebuild": {"document_tree": {"type": "root", "children": [tree]} }}


def test_empty_tree_and_no_rebuild():
    """L4M25-01：rebuild 缺失/空树不崩溃。"""
    assert HierarchyChunker().chunk({}, "d") == ([], [])
    assert HierarchyChunker().chunk({"rebuild": {}}, "d") == ([], [])
    assert HierarchyChunker().chunk({"rebuild": {"document_tree": {"children": []}}}, "d") == ([], [])


def test_very_long_section_splits_within_bounds():
    """L4M25-02：超长章节子块不超过阈值（表格块除外）。"""
    chunker = HierarchyChunker(max_child_chars=300)
    long_text = "这是一段用于压力测试的长文本内容。" * 200
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {"type": "text", "content": long_text, "level": 0,
                     "page": 0, "order": 0, "children": []}
                ],
            }
        }
    }
    _, children = chunker.chunk(layout, "d-long")
    assert len(children) >= 2
    for c in children:
        assert len(c.content) <= 300


def test_no_title_nodes():
    """L4M25-03：无标题节点时父块标题取路径末段。"""
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {"type": "text", "content": "无标题正文。", "level": 0,
                     "page": 0, "order": 0, "children": []}
                ],
            }
        }
    }
    parents, children = HierarchyChunker().chunk(layout, "d-nt")
    assert parents[0].title == "文档根节点"
    assert children[0].title == "文档根节点"


def test_malformed_table_does_not_crash():
    """L4M27-04：畸形表格清洗/增强不抛异常。"""
    for bad in (
        "<table><tr><td>未闭合",
        "<table><tr><th rowspan='x'>坏属性</th></tr></table>",
        "<table><tr><td colspan='999999'>超大跨度</td></tr></table>",
    ):
        cleaned = table_cleaner.clean(bad)
        assert isinstance(cleaned, str)
        text = table_enhancer.enhance(bad)
        assert isinstance(text, str)


def test_unknown_block_types_skipped_safely():
    """L4M25-05：未知块类型不崩溃且可降级。"""
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {"type": "unknown_future_type", "content": "x", "level": 0,
                     "page": 0, "order": 0, "children": []},
                    {"type": "image", "content": "img.png", "level": 0,
                     "page": 0, "order": 1, "children": []},
                    {"type": "text", "content": "正常正文。", "level": 0,
                     "page": 0, "order": 2, "children": []},
                ],
            }
        }
    }
    parents, children = HierarchyChunker().chunk(layout, "d-unk")
    assert len(children) == 1
    assert "正常正文" in children[0].content


def test_single_oversize_segment_isolated():
    """L4M25-06：单段超长文本独立成块且不丢失内容。"""
    chunker = HierarchyChunker(max_child_chars=50)
    text = "这是一个超过阈值的独立长句子，不能被截断在句子中间。"
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {"type": "text", "content": text, "level": 0,
                     "page": 0, "order": 0, "children": []}
                ],
            }
        }
    }
    _, children = chunker.chunk(layout, "d-oversize")
    assert len(children) == 1
    assert children[0].content == text


def test_caption_without_number():
    """L4M27-07：题注无编号时增强文本正常生成。"""
    text = table_enhancer.enhance(
        "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>",
        caption="力学性能表",
    )
    assert "题注：力学性能表" in text
    assert "【表 力学性能表】" not in text  # 无编号时不产生空编号前缀
