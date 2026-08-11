"""L1 单元测试：M25 层级父子分块器。"""

import json
from pathlib import Path

from app.services.indexing.chunker import (
    HierarchyChunker,
    OVERLAP_MARKER,
    MAX_OVERLAP_CHARS,
)
from app.services.indexing.models import ChildChunk, ParentChunk

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "layout_sample.json").read_text(
        encoding="utf-8"
    )
)


def test_hierarchy_breadcrumb_and_title():
    """L1M25-01：标题节点生成层级面包屑，子块继承 title/hierarchy_path/level。"""
    parents, children = HierarchyChunker().chunk(FIXTURE, "doc-uuid")
    paths = [p.hierarchy_path for p in parents]
    assert paths == ["1 范围", "2 力学性能"]
    c1 = [c for c in children if c.hierarchy_path == "1 范围"][0]
    assert c1.title == "1 范围"
    assert c1.level == 1


def test_chunk_id_format():
    """L1M25-02：chunk_id 格式 {doc_id}_p{parent_idx}_{child_idx}。"""
    _, children = HierarchyChunker().chunk(FIXTURE, "abc123")
    assert children[0].chunk_id == "abc123_p0_0"
    assert children[0].parent_chunk_id == "abc123_p0"


def test_table_not_split():
    """L1M25-03：表格块独立成子块，不参与句子切分。"""
    parents, children = HierarchyChunker().chunk(FIXTURE, "doc-t")
    table_children = [c for c in children if c.has_table]
    assert len(table_children) == 1
    assert "<table>" in table_children[0].content
    assert "表格包含" in table_children[0].content_for_embedding
    assert "表1 规定非比例延伸强度" in table_children[0].content_for_embedding


def test_content_preserved_vs_embedding():
    """L1M25-04：content 保留原始 HTML，增强文本只进 content_for_embedding。"""
    _, children = HierarchyChunker().chunk(FIXTURE, "doc-x")
    table = [c for c in children if c.has_table][0]
    assert table.content.count("<table>") == 1
    assert "表格包含2行3列" in table.content_for_embedding
    assert "【表1 规定非比例延伸强度】" in table.content_for_embedding


def test_long_text_split_by_sentence():
    """L1M25-05：超长文本按句子边界切分为多个子块。"""
    chunker = HierarchyChunker(max_child_chars=100)
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {
                        "type": "text",
                        "content": "第一句内容用于测试切分边界，长度需要足够长以触发阈值判定。"
                        "第二句内容继续填充以超出阈值，确保分块器进入切分逻辑。"
                        "第三句内容仍然继续补充长度，让总长度明显超过阈值。"
                        "第四句内容最终结束整个测试段落，句子边界完整保留。",
                        "level": 0, "page": 0, "order": 0, "children": [],
                    }
                ],
            }
        }
    }
    parents, children = chunker.chunk(layout, "doc-long")
    assert len(children) >= 2
    for c in children:
        assert len(c.content) <= 100 or c.content[-1] in "。！？.!?；;"


def test_overlap_between_adjacent_chunks():
    """L1M25-06：相邻文本子块携带 overlap 前缀。"""
    chunker = HierarchyChunker(max_child_chars=80, max_overlap_chars=40)
    long_text = (
        "这是第一段完整句子，用于验证重叠提取，内容需要足够长。"
        "第二段句子同样完整，继续提供上下文，支撑相邻块重叠。"
        "第三段句子是最后一段内容，保证切分确实发生。"
        "第四段句子结束所有测试内容，末尾句子必须完整保留。"
    )
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
    _, children = chunker.chunk(layout, "doc-ov")
    assert len(children) >= 2
    tail = children[0].content_for_embedding
    assert any(OVERLAP_MARKER in c.content_for_embedding for c in children[1:])


def test_fallback_without_tree():
    """L1M25-07：无 document_tree 时降级按 blocks 顺序分块。"""
    layout = json.loads(json.dumps(FIXTURE))
    layout["rebuild"]["document_tree"] = {"type": "root", "children": []}
    parents, children = HierarchyChunker().chunk(layout, "doc-fb")
    assert parents and parents[0].hierarchy_path == "文档根节点"
    assert children
    assert any(c.has_table for c in children)


def test_max_tree_depth_truncated():
    """L1M25-08：超深 document_tree 截断不崩溃。"""
    node = {"type": "text", "content": "深层节点", "level": 0, "page": 0, "order": 0, "children": []}
    root = node
    for _ in range(60):
        root = {"type": "title", "content": "t", "level": 1, "page": 0, "order": 0, "children": [root]}
    layout = {"rebuild": {"document_tree": {"type": "root", "children": [root]}}}
    parents, children = HierarchyChunker().chunk(layout, "doc-deep")
    assert isinstance(parents, list) and isinstance(children, list)


def test_empty_layout_returns_empty():
    """L1M25-09：空 layout 返回空结果。"""
    parents, children = HierarchyChunker().chunk({}, "doc-empty")
    assert parents == [] and children == []


def test_source_pages_dedup_sorted():
    """L1M25-10：子块 source_pages 去重且保持顺序。"""
    _, children = HierarchyChunker().chunk(FIXTURE, "doc-pg")
    p1 = [c for c in children if c.hierarchy_path == "1 范围"][0]
    assert p1.source_pages == [0]
    p2 = [c for c in children if c.hierarchy_path == "2 力学性能"][0]
    assert p2.source_pages == [1]


def test_parent_text_contains_full_section():
    """L1M25-11：子块携带父块完整原文 parent_text。"""
    _, children = HierarchyChunker().chunk(FIXTURE, "doc-pt")
    c = [c for c in children if c.hierarchy_path == "2 力学性能"][0]
    assert "拉伸试验按 GB/T 228.1 执行。" in c.parent_text
