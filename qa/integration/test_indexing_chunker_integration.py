"""L2 集成链路 + L3 功能场景：M25 分块器 + M27 表格增强（真实产物契约）。"""

import json
from pathlib import Path

from app.services.indexing.chunker import HierarchyChunker
from app.services.indexing.table_enhancer import table_enhancer

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "layout_sample.json").read_text(
        encoding="utf-8"
    )
)


def test_full_layout_chunk_flow():
    """L2M25-01：layout.json v1.2 全链路：2 父块 + 章节内元素正确归属。"""
    parents, children = HierarchyChunker().chunk(FIXTURE, "doc-full")
    assert len(parents) == 2
    assert len(children) == 2  # 两章内容均未超阈值，各 1 个子块
    p1 = [p for p in parents if p.hierarchy_path == "1 范围"][0]
    assert p1.has_table is True
    # 父块 content 为原始元素拼接（题注仅在增强文本中前置）
    assert p1.content.count("<table>") == 1
    p2 = [p for p in parents if p.hierarchy_path == "2 力学性能"][0]
    assert p2.has_table is False
    assert "$R_m" in p2.content


def test_table_chunk_embedding_text_flow():
    """L2M27-02：表格块 content_for_embedding 完整链路（题注+增强+原文）。"""
    _, children = HierarchyChunker().chunk(FIXTURE, "doc-tab")
    table = [c for c in children if c.has_table][0]
    assert "表格包含2行3列" in table.content_for_embedding
    assert "【表1 规定非比例延伸强度】" in table.content_for_embedding
    assert table.content_for_embedding.count("【表1 规定非比例延伸强度】") == 1  # 前缀只出现一次
    assert "<table>" in table.content_for_embedding


def test_formula_block_merged_into_text_chunk():
    """L2M25-03：公式块作为文本类型参与分块（不独立成块也不丢弃）。"""
    parents, children = HierarchyChunker().chunk(FIXTURE, "doc-f")
    p2 = [p for p in parents if p.hierarchy_path == "2 力学性能"][0]
    assert "R_m" in p2.content
    child = [c for c in children if c.hierarchy_path == "2 力学性能"][0]
    assert "R_m" in child.content


def test_chunk_models_match_s1_schema_fields():
    """L2M25-04：子块字段与 S1 document_chunks 表字段一一对应。"""
    from app.models.indexing import DocumentChunk

    _, children = HierarchyChunker().chunk(FIXTURE, "doc-schema")
    c = children[0]
    model_fields = {
        "chunk_id", "parent_chunk_id", "chunk_index", "hierarchy_path",
        "title", "level", "has_table", "semantic_label", "source_pages",
        "content", "content_for_embedding", "parent_text", "tokens",
    }
    assert model_fields <= {col.name for col in DocumentChunk.__table__.columns}
    assert set(c.__dataclass_fields__) == model_fields


def test_semantic_label_by_block_type():
    """L2M25-05：semantic_label 按块类型填充（table/text）。"""
    _, children = HierarchyChunker().chunk(FIXTURE, "doc-label")
    table = [c for c in children if c.has_table][0]
    assert table.semantic_label == "table"
    text_children = [c for c in children if not c.has_table]
    assert all(c.semantic_label == "text" for c in text_children)
