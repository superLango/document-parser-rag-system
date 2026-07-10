"""Milvus 向量数据库封装 - Dense+Sparse 混合检索 + RRF 融合。

按方案 8.3 节实现核心能力：
- 向量插入：批量插入 dense + sparse 向量及业务字段
- 混合检索：Dense 检索(IP, nprobe=16) + Sparse 检索(IP) + RRF 融合
- 删除：按 doc_id 删除所有相关分块

采用单例模式确保 Collection 仅加载一次；与 embedding_service 一致使用
懒加载策略——模块导入时不连接 Milvus，首次实际调用时才建立连接，
避免在无 Milvus 环境下导入即失败。

使用示例：
    from app.services.vector_store import vector_store

    # 批量插入
    pks = await vector_store.insert(chunks)

    # 混合检索
    results = await vector_store.hybrid_search(
        query_dense=dense_vec,
        query_sparse={"indices": [...], "values": [...]},
        top_k=10,
    )

    # 按文档删除
    deleted = await vector_store.delete_by_doc_id("doc_123")
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
from pymilvus import Collection, connections, utility

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class VectorStore:
    """Milvus 向量库封装。

    采用单例模式：Milvus 连接与 Collection 实例在首次实际调用时加载并复用，
    避免重复连接与加载开销，同时确保模块导入时不产生网络副作用。
    所有同步的 Milvus 调用通过 asyncio.to_thread 包装为异步接口，
    避免阻塞事件循环。

    Attributes:
        _instance: 单例实例。
        _collection: Milvus Collection 对象，懒加载。
        _connected: 是否已建立连接。
    """

    _instance: VectorStore | None = None
    _collection: Collection | None = None
    _connected: bool = False

    def __new__(cls) -> VectorStore:
        """单例模式 - Collection 仅连接加载一次。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化向量库封装，不连接 Milvus（懒加载）。

        连接推迟到首次实际调用 ``insert`` / ``hybrid_search`` 等方法时，
        确保模块导入时不依赖 Milvus 服务可用性。单例模式下
        ``__init__`` 仅在首次构造时生效。
        """

    def _ensure_connected(self) -> None:
        """确保已连接 Milvus（懒加载入口）。"""
        if not self._connected:
            self._connect()

    def _connect(self) -> None:
        """连接 Milvus 并加载 Collection。

        从配置项读取 Milvus 连接信息，建立连接后加载 Collection 到内存。
        连接失败时抛出 RuntimeError，由调用方决定重试或降级。

        Raises:
            RuntimeError: Milvus 连接失败时抛出。
        """
        try:
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=str(settings.MILVUS_PORT),
            )
        except Exception as exc:  # noqa: BLE001 - 顶层需统一捕获连接类异常
            logger.error(
                "连接 Milvus 失败，请确认服务已启动",
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
                error=str(exc),
            )
            raise RuntimeError(
                f"无法连接 Milvus({settings.MILVUS_HOST}:{settings.MILVUS_PORT}): {exc}"
            ) from exc

        self._collection = Collection(settings.MILVUS_COLLECTION)
        self._collection.load()
        self._connected = True
        logger.info(
            "已连接 Milvus 并加载 Collection",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            collection=settings.MILVUS_COLLECTION,
        )

    async def insert(self, chunks: list[dict]) -> list[int]:
        """批量插入文档分块。

        通过 asyncio.to_thread 将同步 insert 调用交由线程池执行，
        避免阻塞事件循环。

        Args:
            chunks: 待插入的分块列表，每个分块包含：
                - chunk_id: str, 分块唯一标识（业务侧生成）
                - text: str, 分块原文
                - dense_vector: np.ndarray (1024,), 已归一化的密集向量
                - sparse_vector: dict, Milvus SPARSE_FLOAT_VECTOR 格式
                  {"indices": [int, ...], "values": [float, ...]}
                - doc_id: str, 所属文档 ID
                - title_chain: str, 文档标题层级链
                - metadata: dict, 扩展元信息（页码、坐标等）

        Returns:
            list[int]: 插入的记录主键 ID列表。
        """
        self._ensure_connected()

        # 按 Collection schema 字段顺序组织数据
        data = [
            [c["chunk_id"] for c in chunks],                # chunk_id
            [c["text"] for c in chunks],                   # text
            [c["dense_vector"].tolist() for c in chunks],  # dense_vector
            [c["sparse_vector"] for c in chunks],           # sparse_vector (Milvus 格式)
            [c["doc_id"] for c in chunks],                  # doc_id
            [c["title_chain"] for c in chunks],             # title_chain
            [c["metadata"] for c in chunks],                # metadata
        ]

        result = await asyncio.to_thread(self._collection.insert, data)

        logger.info(
            "批量插入向量完成",
            count=len(chunks),
            inserted=result.insert_count,
        )
        return result.primary_keys

    async def hybrid_search(
        self,
        query_dense: np.ndarray,
        query_sparse: dict,
        top_k: int = 10,
        nprobe: int = 16,
    ) -> list[dict]:
        """Dense + Sparse 混合检索 + RRF 融合。

        按方案 8.3 节实现：
        1. Dense 检索 (metric_type=IP, nprobe=16, limit=top_k*2)
        2. Sparse 检索 (metric_type=IP, limit=top_k*2)
        3. RRF (Reciprocal Rank Fusion) 融合两路结果取 top_k

        两路检索均扩大到 top_k*2 以提高 RRF 融合的召回率，
        融合后截取前 top_k 条返回。

        Args:
            query_dense: 查询密集向量 (1024,), 已归一化。
            query_sparse: 查询稀疏向量，Milvus 格式
                {"indices": [int, ...], "values": [float, ...]}。
            top_k: 最终返回的结果数，默认 10。
            nprobe: Dense 检索的 nprobe 参数，默认 16。

        Returns:
            list[dict]: 融合后的检索结果，按 RRF 分数降序排列，每项包含：
                - id: Milvus 主键
                - chunk_id: 分块唯一标识
                - text: 分块原文
                - doc_id: 所属文档 ID
                - title_chain: 文档标题层级链
                - metadata: 扩展元信息
                - score: RRF 融合分数
                - rank: 最终排名（从 1 开始）
        """
        self._ensure_connected()

        # Dense 检索：metric_type=IP，配合归一化向量等价于余弦相似度
        dense_results = await asyncio.to_thread(
            self._collection.search,
            data=[query_dense.tolist()],
            anns_field="dense_vector",
            param={"metric_type": "IP", "params": {"nprobe": nprobe}},
            limit=top_k * 2,
            output_fields=["chunk_id", "text", "doc_id", "title_chain", "metadata"],
        )

        # Sparse 检索：metric_type=IP，对齐稠密侧度量
        sparse_results = await asyncio.to_thread(
            self._collection.search,
            data=[query_sparse],
            anns_field="sparse_vector",
            param={"metric_type": "IP"},
            limit=top_k * 2,
            output_fields=["chunk_id", "text", "doc_id", "title_chain", "metadata"],
        )

        # RRF 融合两路检索结果
        fused = self._reciprocal_rank_fusion(
            dense_results[0], sparse_results[0], top_k=top_k
        )

        logger.info(
            "混合检索完成",
            top_k=top_k,
            dense_hits=len(dense_results[0]),
            sparse_hits=len(sparse_results[0]),
            fused_count=len(fused),
        )
        return fused

    def _reciprocal_rank_fusion(
        self, dense_hits: Any, sparse_hits: Any, top_k: int, k: int = 60
    ) -> list[dict]:
        """RRF (Reciprocal Rank Fusion) 融合两路检索结果。

        RRF 公式: score(d) = Σ 1/(k + rank_i(d))
        其中 k=60 是标准 RRF 参数，用于平滑排名对分数的影响。

        对于同时出现在 Dense 和 Sparse 结果中的文档，其 RRF 分数累加，
        因此两路检索都命中的文档会获得更高的融合分数。

        Args:
            dense_hits: Dense 检索结果（Hits 对象，可迭代）。
            sparse_hits: Sparse 检索结果（Hits 对象，可迭代）。
            top_k: 返回前 K 条融合结果。
            k: RRF 平滑参数，默认 60。

        Returns:
            list[dict]: 融合后的结果列表，按 RRF 分数降序排列。
        """
        # id -> {"score": float, "entity": dict, "dense_rank": int?, "sparse_rank": int?}
        scores: dict[Any, dict] = {}

        # 处理 Dense 结果：hit.entity 返回 Hit 自身，to_dict() 也返回自身，
        # ["entity"] 取出输出字段字典
        for rank, hit in enumerate(dense_hits):
            pk = hit.id
            scores[pk] = {
                "score": 1.0 / (k + rank + 1),
                "entity": hit.entity.to_dict()["entity"],
                "dense_rank": rank + 1,
            }

        # 处理 Sparse 结果：累加 RRF 分数
        for rank, hit in enumerate(sparse_hits):
            pk = hit.id
            if pk in scores:
                scores[pk]["score"] += 1.0 / (k + rank + 1)
                scores[pk]["sparse_rank"] = rank + 1
            else:
                scores[pk] = {
                    "score": 1.0 / (k + rank + 1),
                    "entity": hit.entity.to_dict()["entity"],
                    "sparse_rank": rank + 1,
                }

        # 按 RRF 分数降序排列
        sorted_results = sorted(
            scores.items(), key=lambda x: x[1]["score"], reverse=True
        )

        # 格式化输出，截取 top_k 条
        results: list[dict] = []
        for rank, (pk, info) in enumerate(sorted_results[:top_k]):
            entity = info["entity"]
            results.append(
                {
                    "id": pk,
                    "chunk_id": entity.get("chunk_id", ""),
                    "text": entity.get("text", ""),
                    "doc_id": entity.get("doc_id", ""),
                    "title_chain": entity.get("title_chain", ""),
                    "metadata": entity.get("metadata", {}),
                    "score": info["score"],
                    "rank": rank + 1,
                }
            )

        return results

    async def delete_by_doc_id(self, doc_id: str) -> int:
        """按文档 ID 删除所有相关分块。

        通过 doc_id 过滤表达式定位并删除该文档的全部向量记录，
        用于文档重新解析或删除时清理向量库。

        Args:
            doc_id: 待删除的文档 ID。

        Returns:
            int: 实际删除的记录数。
        """
        self._ensure_connected()

        result = await asyncio.to_thread(
            self._collection.delete, expr=f'doc_id == "{doc_id}"'
        )

        logger.info(
            "按 doc_id 删除向量完成",
            doc_id=doc_id,
            deleted=result.delete_count,
        )
        return result.delete_count

    async def count(self, doc_id: str | None = None) -> int:
        """统计记录数。

        Args:
            doc_id: 若指定则统计该文档的分块数，否则统计全部记录数。

        Returns:
            int: 记录数。
        """
        self._ensure_connected()

        if doc_id:
            # 使用 Milvus count(*) 聚合函数统计匹配记录数
            results = await asyncio.to_thread(
                self._collection.query,
                expr=f'doc_id == "{doc_id}"',
                output_fields=["count(*)"],
            )
            if results:
                return results[0].get("count(*)", 0)
            return 0

        return self._collection.num_entities

    async def delete_all(self) -> None:
        """删除整个集合并重置连接状态（用于知识库重建）。

        直接删除 Milvus 集合，下次插入时会自动重建。
        重置单例的连接与 Collection 缓存，确保后续操作重新初始化。
        """
        # 确保已连接，以便 utility 操作可用
        self._ensure_connected()
        collection_name = settings.MILVUS_COLLECTION

        def _drop_sync() -> None:
            """同步删除集合（在线程池中执行）。"""
            if utility.has_collection(collection_name):
                utility.drop_collection(collection_name)
                logger.info("集合已删除", collection=collection_name)

        await asyncio.to_thread(_drop_sync)

        # 重置单例状态，使后续操作重新连接与加载
        VectorStore._collection = None
        VectorStore._connected = False


# 模块级单例，懒加载，导入时不连接 Milvus
vector_store = VectorStore()
