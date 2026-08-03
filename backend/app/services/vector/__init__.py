"""层级感知重建 + 五维向量索引模块（Popo 后处理版）。

提供从 OCR 输出（merged.json）到 Popo 后处理 → 五维向量入库的完整流程。

主要接口::

    from app.services.vector import reconstruction_service

    # 完整重建（含五维向量入库）
    result = await reconstruction_service.reconstruct("task_123", doc_id="doc_456")

    # 仅 Markdown 重建（不建向量索引）
    path = await reconstruction_service.reconstruct_only_markdown("task_123")
"""

from app.services.vector.chunker import HierarchyChunker, hierarchy_chunker
from app.services.vector.caption_linker import TableCaptionLinker, table_caption_linker
from app.services.vector.five_dim_embedder import FiveDimEmbedder, five_dim_embedder
from app.services.vector.markdown_builder import MarkdownBuilder, markdown_builder
from app.services.vector.vector_models import ChildChunk, DocumentElement, ParentChunk
from app.services.vector.popo_adapter import PopoAdapter
from app.services.vector.reconstruction_service import (
    ReconstructionService,
    reconstruction_service,
)
from app.services.vector.table_cleaner import TableCleaner, table_cleaner
from app.services.vector.five_dim_vector_store import FiveDimVectorStore, five_dim_vector_store
from app.services.vector.chunk_vector_store import ChunkVectorStore, chunk_vector_store

__all__ = [
    "DocumentElement",
    "ParentChunk",
    "ChildChunk",
    "PopoAdapter",
    "TableCleaner",
    "table_cleaner",
    "TableCaptionLinker",
    "table_caption_linker",
    "HierarchyChunker",
    "hierarchy_chunker",
    "FiveDimEmbedder",
    "five_dim_embedder",
    "FiveDimVectorStore",
    "five_dim_vector_store",
    "ChunkVectorStore",
    "chunk_vector_store",
    "MarkdownBuilder",
    "markdown_builder",
    "ReconstructionService",
    "reconstruction_service",
]
