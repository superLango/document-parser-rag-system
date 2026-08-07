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

_DEFAULT_COLLECTION = "doc_five_dim"


def _get_collection_name(kb_id: str | None = None) -> str:
    if kb_id is None:
        return _DEFAULT_COLLECTION
    return f"doc_five_dim_{kb_id[:8].replace('-', '')}"


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
        ]

        schema = CollectionSchema(
            fields=fields,
            description="五维向量索引（单 Collection 多向量字段，path/title/content/type/structural）",
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

    async def insert_chunks(
        self, chunks: list[ChildChunk], doc_id: str, kb_id: str | None = None
    ) -> int:
        if not chunks:
            return 0

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
            },
        )
        return hits


five_dim_vector_store = FiveDimVectorStore()
