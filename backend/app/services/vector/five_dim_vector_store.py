"""单 Collection 五维向量存储（独立实现）。

采用 Milvus 官方多路召回标准方案：
- **单 Collection**，5 个独立向量字段（path/title/content/type/structural）
- 每个向量字段独立 HNSW 索引
- 业务字段（content/title/hierarchy_path/parent_text 等）直接存储在同一 Collection
- 数据强一致性：同一文档的所有向量原子写入/删除
- 支持按 kb_id 隔离 Collection

使用示例::

    from app.services.vector.five_dim_vector_store import five_dim_vector_store

    # 批量插入（默认Collection）
    count = await five_dim_vector_store.insert_chunks(chunks, doc_id="doc_123")

    # 指定KB插入
    count = await five_dim_vector_store.insert_chunks(chunks, doc_id="doc_123", kb_id="kb-uuid-here")

    # 按文档删除
    deleted = await five_dim_vector_store.delete_by_doc_id("doc_123")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from app.core.config import settings
from app.services.vector.vector_models import ChildChunk

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 1024

DIMENSIONS = ["path", "title", "content", "type", "structural"]

_DEFAULT_COLLECTION = settings.FIVE_DIM_VECTOR_COLLECTION


def _get_collection_name(kb_id: str | None = None) -> str:
    if kb_id is None:
        return _DEFAULT_COLLECTION
    # 完整 32 位无连字符 hex 后缀，保证跨 KB 隔离与命名唯一
    return f"doc_five_dim_{kb_id.replace('-', '')}"


class FiveDimVectorStore:
    """单 Collection 五维向量存储（支持按kb_id隔离）。

    采用单例模式：Milvus 连接与 Collection 实例在首次实际调用时加载并复用。
    所有同步 Milvus 调用通过 ``asyncio.to_thread`` 包装为异步接口。
    """

    _instance: FiveDimVectorStore | None = None
    _collections: dict[str, Collection] = {}
    _connected: bool = False

    def __new__(cls) -> FiveDimVectorStore:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

    def _ensure_connected(self) -> None:
        if not self._connected:
            host = getattr(settings, "MILVUS_HOST", "localhost")
            port = getattr(settings, "MILVUS_PORT", 19530)
            connections.connect(alias="five_dim", host=host, port=str(port))
            self._connected = True
            logger.info("Milvus 连接建立", extra={"host": host, "port": port})

    def _get_collection(self, kb_id: str | None = None) -> Collection:
        self._ensure_connected()
        collection_name = _get_collection_name(kb_id)
        
        if collection_name in self._collections:
            return self._collections[collection_name]

        if utility.has_collection(collection_name, using="five_dim"):
            collection = Collection(collection_name, using="five_dim")
            logger.info(
                "加载已有 Collection",
                extra={"collection_name": collection_name},
            )
        else:
            collection = self._create_collection(collection_name)
            logger.info(
                "创建新 Collection",
                extra={"collection_name": collection_name},
            )

        try:
            collection.load()
        except Exception as e:
            logger.warning(f"Collection load 失败，尝试继续: {e}")
        
        self._collections[collection_name] = collection
        return collection

    def _create_collection(self, collection_name: str) -> Collection:
        fields = [
            FieldSchema(
                name="chunk_id",
                dtype=DataType.VARCHAR,
                max_length=128,
                is_primary=True,
            ),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(
                name="hierarchy_path", dtype=DataType.VARCHAR, max_length=8192
            ),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(
                name="parent_text", dtype=DataType.VARCHAR, max_length=65535
            ),
            FieldSchema(name="chunk_index", dtype=DataType.INT32),
            FieldSchema(name="level", dtype=DataType.INT8),
            FieldSchema(name="has_table", dtype=DataType.BOOL),
            FieldSchema(
                name="semantic_label", dtype=DataType.VARCHAR, max_length=256
            ),
            FieldSchema(name="source_pages", dtype=DataType.JSON),
            FieldSchema(
                name="path_vector", dtype=DataType.FLOAT_VECTOR, dim=_EMBEDDING_DIM
            ),
            FieldSchema(
                name="title_vector", dtype=DataType.FLOAT_VECTOR, dim=_EMBEDDING_DIM
            ),
            FieldSchema(
                name="content_vector",
                dtype=DataType.FLOAT_VECTOR,
                dim=_EMBEDDING_DIM,
            ),
            FieldSchema(
                name="type_vector", dtype=DataType.FLOAT_VECTOR, dim=_EMBEDDING_DIM
            ),
            FieldSchema(
                name="structural_vector",
                dtype=DataType.FLOAT_VECTOR,
                dim=_EMBEDDING_DIM,
            ),
            # 稀疏向量（BM25，客户端计算；Milvus 2.4 原生 SPARSE_FLOAT_VECTOR）。
            # 注意：Milvus 2.4 不支持稀疏字段可空，因此必须保证每次 insert 都携带
            # 非空稀疏向量（由 insert_chunks 兜底生成），否则 Milvus 会拒绝入库。
            FieldSchema(
                name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR
            ),
        ]

        schema = CollectionSchema(
            fields=fields,
            description="五维向量索引（单 Collection 多向量字段，path/title/content/type/structural）+ 稀疏向量",
        )
        collection = Collection(
            name=collection_name,
            schema=schema,
            using="five_dim",
        )

        for dim in DIMENSIONS:
            collection.create_index(
                field_name=f"{dim}_vector",
                index_params={
                    "index_type": "HNSW",
                    "metric_type": "IP",
                    "params": {"M": 16, "efConstruction": 200},
                },
            )
            logger.info(f"创建 HNSW 索引: {dim}_vector")

        # 稀疏倒排索引
        collection.create_index(
            field_name="sparse_vector",
            index_params={
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": "IP",
                "params": {"drop_ratio_build": 0.2},
            },
        )
        logger.info(f"创建稀疏倒排索引: sparse_vector")

        return collection

    @classmethod
    def create_kb_collection(cls, kb_id: str) -> None:
        store = cls()
        store._ensure_connected()
        collection_name = _get_collection_name(kb_id)
        if not utility.has_collection(collection_name, using="five_dim"):
            store._create_collection(collection_name)
            logger.info("KB五维Collection已创建", extra={"collection_name": collection_name, "kb_id": kb_id})
        else:
            logger.info("KB五维Collection已存在", extra={"collection_name": collection_name, "kb_id": kb_id})

    @classmethod
    def drop_kb_collection(cls, kb_id: str) -> None:
        store = cls()
        store._ensure_connected()
        collection_name = _get_collection_name(kb_id)
        if collection_name in store._collections:
            del store._collections[collection_name]
        if utility.has_collection(collection_name, using="five_dim"):
            utility.drop_collection(collection_name, using="five_dim")
            logger.warning("KB五维Collection已删除", extra={"collection_name": collection_name, "kb_id": kb_id})

    @classmethod
    async def create_kb_collections(cls, kb_id) -> None:
        kb_id_str = str(kb_id) if not isinstance(kb_id, str) else kb_id
        cls.create_kb_collection(kb_id_str)

    @classmethod
    async def drop_kb_collections(cls, kb_id) -> None:
        kb_id_str = str(kb_id) if not isinstance(kb_id, str) else kb_id
        cls.drop_kb_collection(kb_id_str)

    @classmethod
    async def rebuild_kb_collection(cls, kb_id, *, batch_size: int = 1000) -> int:
        """重建 KB 的五维 Collection，为现有数据补齐稀疏向量（BM25）。

        过程（无需重新嵌入稠密向量）：
        1. 读取旧集合全部行（含 5 个稠密向量字段）。
        2. 用 content+title 拟合 KB 的 BM25 模型并持久化。
        3. 为每行计算稀疏向量。
        4. 删除旧集合，按新 schema（含 sparse_vector）重建。
        5. 分批量重新入库。

        Args:
            kb_id: 知识库 ID。
            batch_size: 单批插入条数。

        Returns:
            int: 重新入库的块数。
        """
        from app.services.vector.bm25_sparse import KBBM25, set_kb_bm25

        store = cls()
        store._ensure_connected()
        kb_id_str = str(kb_id) if not isinstance(kb_id, str) else kb_id
        collection_name = _get_collection_name(kb_id_str)

        # 1) 读取旧数据
        output_fields = [
            "chunk_id", "doc_id", "parent_id", "hierarchy_path", "title",
            "content", "parent_text", "chunk_index", "level",
            "has_table", "semantic_label", "source_pages",
            "path_vector", "title_vector", "content_vector",
            "type_vector", "structural_vector",
        ]
        if utility.has_collection(collection_name, using="five_dim"):
            old = Collection(collection_name, using="five_dim")
            old.load()
            rows = old.query(
                expr="chunk_id != ''", output_fields=output_fields, limit=16384
            )
        else:
            rows = []
        logger.info(
            "重建 KB 集合：读取旧数据",
            extra={"kb_id": kb_id_str, "rows": len(rows)},
        )

        if not rows:
            # 无数据：仅重建 schema
            cls.drop_kb_collection(kb_id_str)
            cls.create_kb_collection(kb_id_str)
            return 0

        # 2) 拟合 BM25
        corpus = [f"{r.get('content', '')} {r.get('title', '')}" for r in rows]
        model = KBBM25(kb_id_str).fit(corpus)
        model.save()
        set_kb_bm25(kb_id_str, model)

        # 3) 计算稀疏向量
        for r in rows:
            r["sparse_vector"] = model.encode_document(
                f"{r.get('content', '')} {r.get('title', '')}"
            )

        # 4) 删除并重建集合
        cls.drop_kb_collection(kb_id_str)
        store._collections.pop(collection_name, None)
        new_col = store._create_collection(collection_name)
        new_col.load()
        store._collections[collection_name] = new_col

        # 5) 分批量入库
        inserted = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            new_col.insert(batch)
            inserted += len(batch)
        new_col.flush()
        logger.info(
            "重建 KB 集合完成",
            extra={"kb_id": kb_id_str, "inserted": inserted},
        )
        return inserted

    async def insert_chunks(
        self, chunks: list[ChildChunk], doc_id: str, kb_id: str | None = None
    ) -> int:
        if not chunks:
            return 0

        # 稀疏向量：加载 KB 的 BM25 模型（不存在则返回 None），存在时为每个块编码。
        # 模型缺失时不在此处生成，由 rebuild_kb_collection 等流程负责构建。
        if kb_id is not None:
            from app.services.vector.bm25_sparse import get_kb_bm25
            kb_bm25 = get_kb_bm25(kb_id)
            if kb_bm25 is not None:
                for chunk in chunks:
                    if chunk.sparse_vector is None:
                        chunk.sparse_vector = kb_bm25.encode_document(
                            f"{chunk.content} {chunk.title}"
                        )

        for chunk in chunks:
            for dim in DIMENSIONS:
                vec = getattr(chunk, f"{dim}_vector", None)
                if vec is None:
                    raise ValueError(
                        f"子块 {chunk.id} 的 {dim}_vector 未生成，"
                        f"请先调用 FiveDimEmbedder.encode_batch"
                    )

        rows: list[dict[str, Any]] = [
            chunk.to_milvus_row(doc_id) for chunk in chunks
        ]

        collection = self._get_collection(kb_id)
        await asyncio.to_thread(collection.insert, rows)

        logger.info(
            "五维向量插入完成",
            extra={"doc_id": doc_id, "chunk_count": len(chunks), "kb_id": kb_id},
        )
        return len(chunks)

    async def delete_by_doc_id(self, doc_id: str, kb_id: str | None = None) -> int:
        collection = self._get_collection(kb_id)
        expr = f'doc_id == "{doc_id}"'
        await asyncio.to_thread(collection.delete, expr)

        logger.info("按文档删除向量", extra={"doc_id": doc_id, "kb_id": kb_id})
        return 0

    async def hybrid_search(
        self,
        query_vectors: dict[str, list[float]],
        doc_id: str,
        top_k: int,
        per_dim_top_k: int,
        weights: dict[str, float],
        ef: int = 64,
        kb_id: str | None = None,
        sparse_query: dict[int, float] | None = None,
        sparse_weight: float | None = None,
    ) -> list[dict[str, Any]]:
        from pymilvus import AnnSearchRequest, WeightedRanker

        collection = self._get_collection(kb_id)

        # 权重由调用方从配置显式传入（缺失即报错，不做硬编码默认兜底）
        if not weights:
            raise ValueError("未提供五维检索权重 weights（应由调用方从 retrieval.weights 配置传入）")

        search_requests: list[AnnSearchRequest] = []
        weight_values: list[float] = []
        for dim in DIMENSIONS:
            vec = query_vectors.get(dim)
            if vec is None:
                continue
            req = AnnSearchRequest(
                data=[vec],
                anns_field=f"{dim}_vector",
                param={"metric_type": "IP", "params": {"ef": ef}},
                limit=per_dim_top_k,
                expr=f'doc_id == "{doc_id}"',
            )
            search_requests.append(req)
            weight_values.append(weights.get(dim, 0.2))

        # 稀疏路（可选）：BM25 词法匹配，与稠密路一起融合
        if sparse_query and sparse_weight:
            search_requests.append(
                AnnSearchRequest(
                    data=[sparse_query],
                    anns_field="sparse_vector",
                    param={"metric_type": "IP"},
                    limit=per_dim_top_k,
                    expr=f'doc_id == "{doc_id}"',
                )
            )
            weight_values.append(sparse_weight)

        if not search_requests:
            logger.warning("hybrid_search 未提供任何维度的查询向量")
            return []

        ranker = WeightedRanker(*weight_values)

        results = await asyncio.to_thread(
            collection.hybrid_search,
            reqs=search_requests,
            rerank=ranker,
            limit=top_k,
            output_fields=[
                "chunk_id", "doc_id", "parent_id", "hierarchy_path", "title",
                "content", "parent_text", "chunk_index", "level",
                "has_table", "semantic_label", "source_pages",
            ],
        )

        hits: list[dict[str, Any]] = []
        result_list = results[0] if results else []
        for hit in result_list:
            entity = hit.entity.to_dict() if hasattr(hit, "entity") else {}
            hits.append({
                "chunk_id": entity.get("chunk_id", ""),
                "score": float(hit.score) if hasattr(hit, "score") else 0.0,
                "doc_id": entity.get("doc_id", ""),
                "parent_id": entity.get("parent_id", ""),
                "hierarchy_path": entity.get("hierarchy_path", ""),
                "title": entity.get("title", ""),
                "content": entity.get("content", ""),
                "parent_text": entity.get("parent_text", ""),
                "chunk_index": entity.get("chunk_index", 0),
                "level": entity.get("level", 0),
                "has_table": entity.get("has_table", False),
                "semantic_label": entity.get("semantic_label", ""),
                "source_pages": entity.get("source_pages", []),
            })

        logger.info(
            "hybrid_search 完成",
            extra={
                "doc_id": doc_id,
                "dims_used": len(search_requests),
                "top_k": top_k,
                "returned": len(hits),
                "kb_id": kb_id,
                "use_sparse": bool(sparse_query and sparse_weight),
            },
        )
        return hits

    async def sparse_search(
        self,
        sparse_query: dict[int, float],
        doc_id: str,
        top_k: int,
        kb_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """稀疏（BM25）专用检索，返回该文档内词法命中的块（Phase 2 兜底用）。"""
        from pymilvus import AnnSearchRequest, WeightedRanker

        collection = self._get_collection(kb_id)
        req = AnnSearchRequest(
            data=[sparse_query],
            anns_field="sparse_vector",
            param={"metric_type": "IP"},
            limit=top_k,
            expr=f'doc_id == "{doc_id}"',
        )
        results = await asyncio.to_thread(
            collection.hybrid_search,
            reqs=[req],
            rerank=WeightedRanker(1.0),
            limit=top_k,
            output_fields=[
                "chunk_id", "doc_id", "parent_id", "hierarchy_path", "title",
                "content", "parent_text", "chunk_index", "level",
                "has_table", "semantic_label", "source_pages",
            ],
        )
        hits: list[dict[str, Any]] = []
        result_list = results[0] if results else []
        for hit in result_list:
            entity = hit.entity.to_dict() if hasattr(hit, "entity") else {}
            hits.append({
                "chunk_id": entity.get("chunk_id", ""),
                "score": float(hit.score) if hasattr(hit, "score") else 0.0,
                "content": entity.get("content", ""),
                "title": entity.get("title", ""),
                "has_table": bool(entity.get("has_table", False)),
            })
        return hits


five_dim_vector_store = FiveDimVectorStore()
