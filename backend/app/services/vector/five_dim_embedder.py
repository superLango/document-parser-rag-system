"""五维向量编码器（独立实现）。

Milvus 配置 ``proxy.maxVectorFieldNum=10``，支持单 Collection 5 个向量字段，
因此恢复完整的五维设计（原 4 维将 type+structural 合并为 meta，现已拆分）。

五维维度定义：

| 维度 | 含义 | 编码方式 | 数据来源 |
|------|------|----------|----------|
| Path | 文档结构路径 | 层级路径文本 embedding | hierarchy_path |
| Title | 标题语义 | 标题文本 embedding | 章节标题 |
| Content | 内容语义 | 文本内容 embedding | 子块正文（表格含题注） |
| Type | 内容类型 | 分类值文本 embedding | 表格/文本/列表等类型 |
| Structural | 结构位置 | 位置编码 + 排版特征文本 embedding | 层级深度 + 块内位置 |

仅依赖 ``embedding_service``（bge-m3），不依赖 LLM。

性能优化（P2.3，经参数调优确认最优方案）：
    - **不分组编码**：5*N 文本合并为 1 次 embed 调用。参数调优显示不分组
      （2.26s）比分组（2.09s+锁开销=3.24s）快，因为分组需 2 次 embed 调用
      且 ``_embed_lock`` 导致串行化，额外锁开销抵消了短文本加速收益。
    - **跳过 sparse**：五维向量只需 dense，传 ``return_sparse=False`` 跳过
      sparse 权重计算与格式转换，减少 ~20% 耗时。
    - **batch_size=16**：参数调优显示 bs=16（1.13s/2.26s）优于 bs=32（1.21s/2.73s）
      和 bs=64（1.52s/4.24s），因为小 batch 在 GPU 上调度更灵活。
    - **max_length=8192**：覆盖 content 维度的大表格 HTML（最长 2000 字符）。
      调优显示 ml=2048 与 ml=8192 耗时几乎一致（2.255s vs 2.256s），
      因大部分文本 < 100 字符，max_length 仅影响长文本。

基准测试（GPU, 136 子块 × 5 维 = 680 文本）：
    - 优化前（统一 ml=8192 + sparse + bs=16）: 7.47s
    - 优化后（统一 ml=8192 + no_sparse + bs=16）: 2.26s（提速 70%）
"""

from __future__ import annotations

import logging

from app.services.vector.vector_models import ChildChunk

logger = logging.getLogger(__name__)

# 五维维度名称（Milvus 配置 proxy.maxVectorFieldNum=10，支持单 Collection 5 个向量字段）
DIMENSIONS = ["path", "title", "content", "type", "structural"]

# Content 维度截断长度（防止 token 超限）
_CONTENT_MAX_CHARS = 2000

# 参数调优确认的最优参数
# 调优脚本: scripts/tune_five_dim_params.py
_OPTIMAL_BATCH_SIZE = 16  # bs=16 优于 32/64
_OPTIMAL_MAX_LENGTH = 8192  # 覆盖大表格，与 ml=2048 耗时一致


class FiveDimEmbedder:
    """五维向量编码器。

    为每个 ``ChildChunk`` 生成五维向量（path/title/content/type/structural），
    原地填充到 ``ChildChunk`` 的对应字段。

    优化策略（P2.3，经参数调优确认）：
        - **不分组**：5*N 文本合并为 1 次 embed 调用，避免分组的 2 次锁开销。
        - **跳过 sparse**：``return_sparse=False``。
        - **batch_size=16, max_length=8192**：调优最优组合。
    """

    @staticmethod
    def _build_path_text(chunk: ChildChunk) -> str:
        """Path 维度文本：层级路径。"""
        return chunk.hierarchy_path or ""

    @staticmethod
    def _build_title_text(chunk: ChildChunk) -> str:
        """Title 维度文本：标题。"""
        return chunk.title or ""

    @staticmethod
    def _build_content_text(chunk: ChildChunk) -> str:
        """Content 维度文本：内容（截断防止 token 超限）。

        表格块的 content 已由 ``TableCaptionLinker`` 前置题注文本，
        因此表格可通过题注语义被召回。
        """
        return (chunk.content or "")[:_CONTENT_MAX_CHARS]

    @staticmethod
    def _build_type_text(chunk: ChildChunk) -> str:
        """Type 维度文本：内容类型分类。

        将类型映射为描述性文本，便于 embedding 模型理解语义：
        - 表格块 → "表格 数据结构 行列"
        - 文本块 → "文本 段落 说明"
        """
        if chunk.has_table:
            base = "表格 数据结构 行列"
        else:
            base = "文本 段落 说明"
        if chunk.semantic_label:
            return f"{base} {chunk.semantic_label}"
        return base

    @staticmethod
    def _build_structural_text(chunk: ChildChunk) -> str:
        """Structural 维度文本：结构位置 + 排版特征。

        示例："第3级 第0块 7.4 力学性能"
        """
        parts: list[str] = [
            f"第{chunk.level}级",
            f"第{chunk.chunk_index}块",
        ]
        if chunk.hierarchy_path:
            parts.append(chunk.hierarchy_path)
        return " ".join(parts)

    async def encode_batch(self, chunks: list[ChildChunk]) -> int:
        """批量为子块生成五维向量（原地填充）。

        最优方案（P2.3 参数调优确认）：
            5*N 个文本合并为 1 次 embed 调用，``return_sparse=False``，
            ``batch_size=16``，``max_length=8192``。

        Args:
            chunks: 待编码的子块列表。

        Returns:
            成功编码的子块数量。
        """
        if not chunks:
            return 0

        from app.services.embedding.embedding_service import embedding_service

        n = len(chunks)

        # 构造 5*N 文本列表（维度优先排列）
        builders = {
            "path": self._build_path_text,
            "title": self._build_title_text,
            "content": self._build_content_text,
            "type": self._build_type_text,
            "structural": self._build_structural_text,
        }

        all_texts: list[str] = []
        for dim in DIMENSIONS:
            builder = builders[dim]
            all_texts.extend(builder(c) for c in chunks)

        # 1 次 embed 调用（不分组 + 跳过 sparse + 最优参数）
        result = await embedding_service.embed(
            all_texts,
            batch_size=_OPTIMAL_BATCH_SIZE,
            return_sparse=False,
            max_length=_OPTIMAL_MAX_LENGTH,
        )
        dense_vectors = result["dense_vectors"]  # np.ndarray, shape=(5*N, 1024)

        # 切分向量，填充到每个 chunk
        for i, chunk in enumerate(chunks):
            for j, dim in enumerate(DIMENSIONS):
                vec = dense_vectors[j * n + i]
                # 转为 list[float] 供 Milvus 写入
                setattr(chunk, f"{dim}_vector", vec.tolist())

        logger.info(
            "五维向量编码完成",
            extra={
                "chunk_count": n,
                "dimensions": len(DIMENSIONS),
                "total_texts": len(all_texts),
            },
        )
        return n


# 模块级单例
five_dim_embedder = FiveDimEmbedder()
