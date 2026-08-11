"""S2 索引数据模型：文档元素 → 父子块（与 S1 document_chunks 表字段对齐）。

设计差异（相对旧项目 vector_models.py）：
- 输入元素来自 layout.json v1.2 的 document_tree，而不是 Popo merged.json；
- 块类型集合对齐 parsekit BLOCK_TYPES（formula/image/list_item/footnote 等）；
- ChildChunk 直接携带 content_for_embedding（表格增强文本），原始 content 保留；
- chunk_id 格式固定为 {doc_id}_p{parent_idx}_{child_idx}，与 S1 唯一约束一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DocumentElement:
    """由 document_tree 节点归一化后的分块输入元素。

    Attributes:
        type: parsekit 块类型（title/text/table/formula/list_item/...）。
        content: 块内容（表格为原始 HTML，其余为文本/Markdown 片段）。
        page: 页码（0-based，与 layout.json pages 下标一致）。
        order: 块在阅读顺序中的序号。
        hierarchy_path: 层级面包屑（"1 范围 > 1.1 术语"）。
        title: 所属章节标题（面包屑末段）。
        level: 标题层级（1-6）。
        has_table: 是否表格块。
        caption: 表格题注文本（从 tree 的 table_caption 子节点提取）。
        table_num: 表格编号（如 "表3"，从题注正则提取）。
        source: 内容来源（rule/text/ocr，无 tree 降级时取自 block）。
    """

    type: str
    content: str
    page: int
    order: int
    hierarchy_path: str = ""
    title: str = ""
    level: int = 0
    has_table: bool = False
    caption: str = ""
    table_num: str = ""
    source: str = "rule"


@dataclass(slots=True)
class ParentChunk:
    """父块：完整章节（不落库，仅作为 parent_text 上下文来源）。"""

    id: str
    hierarchy_path: str
    title: str
    level: int
    content: str
    source_pages: list[int] = field(default_factory=list)
    has_table: bool = False
    semantic_label: str = ""


@dataclass(slots=True)
class ChildChunk:
    """子块：最小检索单元，字段与 S1 document_chunks 表一一对应。"""

    chunk_id: str
    parent_chunk_id: str
    chunk_index: int
    hierarchy_path: str
    title: str
    level: int
    has_table: bool
    semantic_label: str
    source_pages: list[int]
    content: str
    content_for_embedding: str
    parent_text: str
    tokens: int
