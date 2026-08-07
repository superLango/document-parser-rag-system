"""层级感知重建与五维向量化数据模型。

定义三个核心数据结构，贯穿 OCR 适配 → 层级重建 → 父子块切分 → 五维向量化全流程：

- ``DocumentElement``：OCR 解析后的原始文档元素（merged.json 转换而来）
- ``ParentChunk``：父块，完整的章节或逻辑单元（不存向量，仅作 parent_text）
- ``ChildChunk``：子块，切分后的最小检索单元（生成五维向量入库）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DocumentElement:
    """OCR 解析后的文档元素。

    由 ``OcrAdapter`` 从 ``merged.json`` 转换而来，经表格清洗、跨页合并、
    层级重建后，最终由 ``HierarchyChunker`` 切分为父子块。

    Attributes:
        type: 元素类型（title / paragraph / table）。
        bbox: 边界框 [x1, y1, x2, y2]。
        content: 文本内容或 HTML 表格。
        page_num: 页码（1-based）。
        native_label: OCR 原始标签（doc_title / paragraph_title / table 等）。
        font_height: 字体高度近似（bbox 高度）。
        hierarchy_level: 层级深度（层级重建后填充，1=一级标题）。
        hierarchy_path: 层级路径（层级重建后填充，如 "7.4 力学性能"）。
        index: 元素在原文档中的序号。
        caption: 表格题注文本（``TableCaptionLinker`` 填充，仅 table 类型）。
            通过题注编号匹配关联，作为表格的检索文本，使表格可通过题注语义召回。
        table_num: 表格编号（如 "表3"），由 ``TableCaptionLinker`` 从题注或上下文提取。
    """

    type: str
    bbox: list[float]
    content: str
    page_num: int
    native_label: str = ""
    font_height: float = 0.0
    hierarchy_level: int = 0
    hierarchy_path: str = ""
    index: int = 0
    caption: str = ""
    table_num: str = ""


@dataclass
class ParentChunk:
    """父块：完整的章节或逻辑单元。

    **不作为向量存储**，仅作为 ``parent_text`` 挂载到每个子块。
    召回后用 ``parent_text`` 替换子块，为 LLM 提供完整上下文。

    Attributes:
        id: 父块唯一标识。
        hierarchy_path: 层级路径，如 "7.4 力学性能"。
        title: 章节标题。
        level: 层级深度。
        content: 父块完整原文（作为子块的 parent_text）。
        parent_path: 父级路径（如有）。
        source_pages: 来源页码列表。
        has_table: 是否包含表格。
        semantic_label: 语义标签。
    """

    id: str
    hierarchy_path: str
    title: str
    level: int
    content: str
    parent_path: str | None = None
    source_pages: list[int] = field(default_factory=list)
    has_table: bool = False
    semantic_label: str = ""


@dataclass
class ChildChunk:
    """子块：切分后的最小检索单元。

    生成五维向量存入 Milvus，继承父级的 ``hierarchy_path`` 与 ``title``。
    携带 ``parent_text``（父块完整原文），召回后可替换子块提供完整上下文。

    Attributes:
        id: 子块唯一标识（格式: ``{parent_id}_{chunk_index}``）。
        parent_id: 父块 ID。
        hierarchy_path: 层级路径（继承自父块）。
        title: 标题（继承自父块）。
        content: 子块正文。
        parent_text: 父块完整原文（召回后替换子块用）。
        chunk_index: 在父块中的位置序号。
        level: 层级深度（继承自父块）。
        has_table: 是否为表格块。
        semantic_label: 语义标签。
        source_pages: 来源页码列表。
        path_vector: Path 维度向量（embedding 后填充）。
        title_vector: Title 维度向量。
        content_vector: Content 维度向量。
        type_vector: Type 维度向量。
        structural_vector: Structural 维度向量。
    """

    id: str
    parent_id: str
    hierarchy_path: str
    title: str
    content: str
    parent_text: str
    chunk_index: int
    level: int
    has_table: bool = False
    semantic_label: str = ""
    source_pages: list[int] = field(default_factory=list)
    # 五维向量（embedding 后填充）
    # Milvus 配置 proxy.maxVectorFieldNum=10，支持单 Collection 5 个向量字段
    path_vector: list[float] | None = None
    title_vector: list[float] | None = None
    content_vector: list[float] | None = None
    type_vector: list[float] | None = None
    structural_vector: list[float] | None = None
    # 稀疏向量（BM25，Milvus SPARSE_FLOAT_VECTOR，客户端计算后填充）
    sparse_vector: dict[int, float] | None = None

    def to_milvus_row(self, doc_id: str) -> dict[str, Any]:
        """转换为 Milvus 单 Collection 数据行。

        Args:
            doc_id: 文档 ID（向量库关联键）。

        Returns:
            符合 ``FiveDimVectorStore`` Schema 的字典。
        """
        row: dict[str, Any] = {
            "chunk_id": self.id,
            "doc_id": doc_id,
            "parent_id": self.parent_id,
            "hierarchy_path": _truncate_bytes(self.hierarchy_path, 8192),
            "title": _truncate_bytes(self.title, 512),
            "content": _truncate_bytes(self.content, 65535),
            "parent_text": _truncate_bytes(self.parent_text, 65535),
            "chunk_index": self.chunk_index,
            "level": self.level,
            "has_table": self.has_table,
            "semantic_label": _truncate_bytes(self.semantic_label, 256),
            "source_pages": self.source_pages,
        }
        for dim in ("path", "title", "content", "type", "structural"):
            vec = getattr(self, f"{dim}_vector")
            if vec is not None:
                row[f"{dim}_vector"] = vec
        if self.sparse_vector is not None:
            row["sparse_vector"] = self.sparse_vector
        return row


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """按字节安全截断字符串（UTF-8 编码）。

    Milvus VARCHAR max_length 以字节为单位，中文字符占 3 字节。
    """
    if not text:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # 截断到 max_bytes 字节，并确保不截断在多字节字符中间
    truncated = encoded[:max_bytes]
    # 解码时忽略可能的不完整尾部字节
    return truncated.decode("utf-8", errors="ignore")
