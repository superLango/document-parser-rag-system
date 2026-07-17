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

        # 将 sparse_vector 从 {"indices":[...],"values":[...]} 转换为
        # pymilvus 3.x 要求的 {int: float} 字典格式
        sparse_list: list[dict[int, float]] = []
        for c in chunks:
            sv = c["sparse_vector"]
            if isinstance(sv, dict) and "indices" in sv and "values" in sv:
                # 旧格式 {"indices": [int,...], "values": [float,...]}
                sparse_list.append(
                    {int(k): float(v) for k, v in zip(sv["indices"], sv["values"])}
                )
            else:
                # 已是 {int: float} 或 {str: float} 格式
                sparse_list.append({int(k): float(v) for k, v in sv.items()})

        # 按 Collection schema 字段顺序组织数据
        data = [
            [c["chunk_id"] for c in chunks],                # chunk_id
            [c["text"] for c in chunks],                   # text
            [c["dense_vector"].tolist() for c in chunks],  # dense_vector
            sparse_list,                                    # sparse_vector (pymilvus 3.x 格式)
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
        ef: int = 64,
    ) -> list[dict]:
        """Dense + Sparse 混合检索 + RRF 融合。

        按方案 8.3 节 + P2.1 优化实现：
        1. Dense 检索 (HNSW, metric_type=IP, ef=64, limit=top_k*2)
        2. Sparse 检索 (SPARSE_INVERTED_INDEX, metric_type=IP, limit=top_k*2)
        3. RRF (Reciprocal Rank Fusion) 融合两路结果取 top_k

        P2.1 优化：Dense 检索从 IVF_PQ(nprobe) 迁移到 HNSW(ef)，
        检索延迟预期降低 60%+。

        两路检索均扩大到 top_k*2 以提高 RRF 融合的召回率，
        融合后截取前 top_k 条返回。

        Args:
            query_dense: 查询密集向量 (1024,), 已归一化。
            query_sparse: 查询稀疏向量，Milvus 格式
                {"indices": [int, ...], "values": [float, ...]}。
            top_k: 最终返回的结果数，默认 10。
            ef: HNSW 检索的 ef 参数（搜索宽度），默认 64。
                ef 越大召回率越高但速度越慢，需 ≥ top_k。

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

        # 将 query_sparse 从 {"indices":[...],"values":[...]} 转换为
        # pymilvus 3.x 要求的 {int: float} 字典格式
        if isinstance(query_sparse, dict) and "indices" in query_sparse and "values" in query_sparse:
            query_sparse_dict: dict[int, float] = {
                int(k): float(v)
                for k, v in zip(query_sparse["indices"], query_sparse["values"])
            }
        else:
            query_sparse_dict = {int(k): float(v) for k, v in query_sparse.items()}

        # Dense 检索：HNSW 索引，metric_type=IP，配合归一化向量等价于余弦相似度
        # ef 为 HNSW 搜索宽度参数，需 >= top_k*2 以保证足够候选
        ef_search = max(ef, top_k * 2)
        dense_results = await asyncio.to_thread(
            self._collection.search,
            data=[query_dense.tolist()],
            anns_field="dense_vector",
            param={"metric_type": "IP", "params": {"ef": ef_search}},
            limit=top_k * 2,
            output_fields=["chunk_id", "text", "doc_id", "title_chain", "metadata"],
        )

        # Sparse 检索：SPARSE_INVERTED_INDEX，metric_type=IP，对齐稠密侧度量
        sparse_results = await asyncio.to_thread(
            self._collection.search,
            data=[query_sparse_dict],
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
            ef=ef_search,
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

    async def incremental_insert(
        self,
        chunks: list[dict],
        doc_id: str,
        replace_existing: bool = True,
    ) -> dict:
        """增量插入文档分块，无需全量重建索引（P1.5 优化）。

        按方案 5.2 节实现 RAGFlow 风格的增量索引更新，封装以下完整流程：

        1. （可选）按 doc_id 删除该文档的旧分块，避免 chunk_id 冲突
        2. 调用 ``embedding_service.embed_documents`` 批量嵌入新分块
        3. 调用 ``self.insert`` 写入 Milvus（Milvus 自动维护增量索引）
        4. 调用 ``cache_service.invalidate_by_doc_id`` 失效相关缓存
        5. 若 LlamaIndex 辅助索引已构建，调用 ``index_manager.build_indices``
           增量追加新节点（IndexManager 内部会 extend 节点列表并重建）

        各阶段具备容错能力：缓存失效与 LlamaIndex 更新失败不影响主流程。

        Args:
            chunks: 分块列表，每个分块需含 chunk_id、text、metadata 字段。
                不含向量字段（dense_vector/sparse_vector），由本方法嵌入生成。
            doc_id: 文档 ID，用于清理旧分块与缓存失效。
            replace_existing: 是否先删除该文档的旧分块。默认 True，
                适用于文档重新解析场景；首次插入设为 False 可跳过删除。

        Returns:
            dict: 增量插入结果，包含：
                - inserted_count: 新插入的分块数
                - deleted_count: 删除的旧分块数（replace_existing=True 时）
                - cache_invalidated: 缓存是否已失效
                - llm_index_updated: LlamaIndex 索引是否已更新
        """
        # 延迟导入，避免模块导入时循环依赖
        from app.services.cache_service import rag_cache_service
        from app.services.embedding_service import embedding_service

        deleted_count = 0

        # 1. 可选：删除该文档的旧分块（重新解析场景）
        if replace_existing:
            try:
                deleted_count = await self.delete_by_doc_id(doc_id)
                logger.info(
                    "增量插入：已清理旧分块",
                    doc_id=doc_id,
                    deleted=deleted_count,
                )
            except Exception as err:
                logger.warning(
                    "增量插入：清理旧分块失败，继续插入",
                    doc_id=doc_id,
                    error=str(err),
                )

        # 无新分块需要插入时直接返回
        if not chunks:
            logger.info("增量插入：无新分块需要插入", doc_id=doc_id)
            return {
                "inserted_count": 0,
                "deleted_count": deleted_count,
                "cache_invalidated": False,
                "llm_index_updated": False,
            }

        # 2. P2.5 流水线嵌入+插入：分批嵌入，嵌入批次 N 与插入批次 N-1 并行
        # 嵌入为 GPU 密集型，插入为网络 IO 密集型，两者可真正并行执行
        # 流水线批次大小：单次嵌入批量的 2 倍，平衡吞吐与延迟
        pipeline_batch_size = max(settings.EMBEDDING_BATCH_SIZE * 2, 32)
        batches: list[list[dict]] = [
            chunks[i : i + pipeline_batch_size]
            for i in range(0, len(chunks), pipeline_batch_size)
        ]

        chunks_with_vectors: list[dict] = []
        inserted_count = 0

        if len(batches) <= 1:
            # 单批次：直接嵌入+插入（保持原逻辑，避免任务调度开销）
            try:
                texts = [c.get("text", "") for c in chunks]
                embeddings = await embedding_service.embed_documents(texts)
            except Exception as err:
                logger.error(
                    "增量插入：嵌入生成失败",
                    doc_id=doc_id,
                    error=str(err),
                )
                raise

            dense_vectors = embeddings["dense_vectors"]
            sparse_indices = embeddings["sparse_indices"]

            for idx, chunk in enumerate(chunks):
                meta = chunk.get("metadata", {})
                chunks_with_vectors.append(
                    {
                        "chunk_id": chunk.get("chunk_id", f"{doc_id}_{idx}"),
                        "text": chunk.get("text", ""),
                        "dense_vector": dense_vectors[idx],
                        "sparse_vector": sparse_indices[idx],
                        "doc_id": doc_id,
                        "title_chain": meta.get("title_chain", ""),
                        "metadata": meta,
                    }
                )

            try:
                primary_keys = await self.insert(chunks_with_vectors)
                inserted_count = len(primary_keys)
            except Exception as err:
                logger.error(
                    "增量插入：Milvus 插入失败",
                    doc_id=doc_id,
                    error=str(err),
                )
                raise
        else:
            # 多批次：流水线并行（嵌入批次 N 与插入批次 N-1 并行）
            logger.info(
                "流水线嵌入+插入启动",
                doc_id=doc_id,
                total_chunks=len(chunks),
                batch_count=len(batches),
                batch_size=pipeline_batch_size,
            )
            insert_task: asyncio.Task | None = None

            for batch_idx, batch in enumerate(batches):
                # 启动当前批次嵌入
                batch_texts = [c.get("text", "") for c in batch]
                embed_task = asyncio.create_task(
                    embedding_service.embed_documents(batch_texts)
                )

                # 同时等待上一批插入完成（此时 embed_task 正在并行执行）
                if insert_task is not None:
                    try:
                        prev_pks = await insert_task
                        inserted_count += len(prev_pks)
                    except Exception as err:
                        logger.error(
                            "增量插入：流水线 Milvus 插入失败",
                            doc_id=doc_id,
                            batch_idx=batch_idx - 1,
                            error=str(err),
                        )
                        # 取消正在进行的嵌入任务
                        embed_task.cancel()
                        raise

                # 等待当前批次嵌入完成
                try:
                    embeddings = await embed_task
                except Exception as err:
                    logger.error(
                        "增量插入：流水线嵌入生成失败",
                        doc_id=doc_id,
                        batch_idx=batch_idx,
                        error=str(err),
                    )
                    raise

                dense_vectors = embeddings["dense_vectors"]
                sparse_indices = embeddings["sparse_indices"]

                # 组装当前批次的 chunks_with_vectors
                batch_chunks_with_vectors: list[dict] = []
                for idx, chunk in enumerate(batch):
                    meta = chunk.get("metadata", {})
                    batch_chunks_with_vectors.append(
                        {
                            "chunk_id": chunk.get("chunk_id", f"{doc_id}_{batch_idx}_{idx}"),
                            "text": chunk.get("text", ""),
                            "dense_vector": dense_vectors[idx],
                            "sparse_vector": sparse_indices[idx],
                            "doc_id": doc_id,
                            "title_chain": meta.get("title_chain", ""),
                            "metadata": meta,
                        }
                    )
                chunks_with_vectors.extend(batch_chunks_with_vectors)

                # 启动当前批次插入（下一轮迭代时与下一批嵌入并行）
                insert_task = asyncio.create_task(
                    self.insert(batch_chunks_with_vectors)
                )

            # 等待最后一批插入完成
            if insert_task is not None:
                try:
                    last_pks = await insert_task
                    inserted_count += len(last_pks)
                except Exception as err:
                    logger.error(
                        "增量插入：流水线最后一批 Milvus 插入失败",
                        doc_id=doc_id,
                        error=str(err),
                    )
                    raise

            logger.info(
                "流水线嵌入+插入完成",
                doc_id=doc_id,
                inserted_count=inserted_count,
                batch_count=len(batches),
            )

        # 4. 失效相关缓存（失败不影响主流程）
        cache_invalidated = False
        try:
            await rag_cache_service.invalidate_by_doc_id(doc_id)
            cache_invalidated = True
        except Exception as err:
            logger.warning(
                "增量插入：缓存失效失败",
                doc_id=doc_id,
                error=str(err),
            )

        # 4.5 P2.3：增量更新 BM25 索引（失败不影响主流程）
        # 新文档入库时同步更新 BM25 索引，避免首次检索时全量重建
        try:
            from app.services.bm25_retriever import bm25_retriever

            bm25_retriever.add_documents(chunks_with_vectors)
        except Exception as err:
            logger.warning(
                "增量插入：BM25 索引更新失败",
                doc_id=doc_id,
                error=str(err),
            )

        # 5. 增量更新 LlamaIndex 辅助索引（已构建时追加新节点）
        llm_index_updated = False
        try:
            from app.services.index_manager import index_manager

            if index_manager._built:
                from llama_index.core.schema import TextNode as LITextNode

                new_nodes: list[LITextNode] = []
                for chunk in chunks:
                    meta = chunk.get("metadata", {})
                    new_nodes.append(
                        LITextNode(
                            id_=chunk.get("chunk_id", ""),
                            text=chunk.get("text", ""),
                            metadata={
                                "doc_id": doc_id,
                                "doc_title": meta.get("doc_title", ""),
                                "file_name": meta.get("file_name", ""),
                                "chunk_type": meta.get("chunk_type", "text"),
                                "title_chain": meta.get("title_chain", ""),
                            },
                        )
                    )
                if new_nodes:
                    # IndexManager.build_indices 在 _built=True 时
                    # 会 extend 节点列表并重建内部索引
                    await index_manager.build_indices(new_nodes)
                    llm_index_updated = True
                    logger.info(
                        "增量插入：LlamaIndex 索引已更新",
                        doc_id=doc_id,
                        node_count=len(new_nodes),
                    )
        except ImportError:
            logger.debug("llama-index-core 未安装，跳过 LlamaIndex 增量更新")
        except Exception as err:
            logger.warning(
                "增量插入：LlamaIndex 索引更新失败",
                doc_id=doc_id,
                error=str(err),
            )

        logger.info(
            "增量插入完成",
            doc_id=doc_id,
            inserted=inserted_count,
            deleted=deleted_count,
            cache_invalidated=cache_invalidated,
            llm_index_updated=llm_index_updated,
        )

        return {
            "inserted_count": inserted_count,
            "deleted_count": deleted_count,
            "cache_invalidated": cache_invalidated,
            "llm_index_updated": llm_index_updated,
        }

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
