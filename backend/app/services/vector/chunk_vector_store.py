"""Milvus 向量数据库封装 - Dense+Sparse 混合检索 + RRF 融合（支持按KB隔离）。

按方案 8.3 节实现核心能力：
- 向量插入：批量插入 dense + sparse 向量及业务字段
- 混合检索：Dense 检索(IP, nprobe=16) + Sparse 检索(IP) + RRF 融合
- 删除：按 doc_id 删除所有相关分块
- 支持按 kb_id 隔离 Collection

采用单例模式确保 Collection 仅加载一次；与 embedding_service 一致使用
懒加载策略——模块导入时不连接 Milvus，首次实际调用时才建立连接，
避免在无 Milvus 环境下导入即失败。

使用示例：
    from app.services.vector.chunk_vector_store import chunk_vector_store

    # 批量插入（默认Collection）
    pks = await chunk_vector_store.insert(chunks)

    # 指定KB插入
    pks = await chunk_vector_store.insert(chunks, kb_id="kb-uuid-here")

    # 混合检索
    results = await chunk_vector_store.hybrid_search(
        query_dense=dense_vec,
        query_sparse={"indices": [...], "values": [...]},
        top_k=10,
        kb_id="kb-uuid-here",
    )

    # 按文档删除
    deleted = await chunk_vector_store.delete_by_doc_id("doc_123")
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_EMBEDDING_DIM = 1024

_DEFAULT_COLLECTION = "doc_chunks"


def _get_collection_name(kb_id) -> str:
    """生成KB专属Collection名。

    兼容 UUID 对象和字符串两种输入，取完整 32 位无连字符 hex 作为后缀
    （与 ``kb_lifecycle._verify_milvus`` 校验命名一致，保证隔离校验不失效）。
    """
    if kb_id is None:
        return _DEFAULT_COLLECTION
    import uuid as _uuid
    if isinstance(kb_id, _uuid.UUID):
        kb_str = kb_id.hex
    else:
        kb_str = str(kb_id).replace("-", "")
    return f"doc_chunks_{kb_str}"


class ChunkVectorStore:
    """Milvus 向量库封装（支持按KB隔离）。

    采用单例模式：Milvus 连接与 Collection 实例在首次实际调用时加载并复用，
    避免重复连接与加载开销，同时确保模块导入时不产生网络副作用。
    所有同步的 Milvus 调用通过 asyncio.to_thread 包装为异步接口，
    避免阻塞事件循环。
    """

    _instance: ChunkVectorStore | None = None
    _collections: dict[str, Collection] = {}
    _connected: bool = False
    _loaded: set[str] = set()

    def __new__(cls) -> ChunkVectorStore:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

    def _ensure_connected(self) -> None:
        if not self._connected:
            self._connect()

    def _connect(self) -> None:
        try:
            connections.connect(
                alias="chunk_store",
                host=settings.MILVUS_HOST,
                port=str(settings.MILVUS_PORT),
            )
        except Exception as exc:
            logger.error(
                "连接 Milvus 失败，请确认服务已启动",
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
                error=str(exc),
            )
            raise RuntimeError(
                f"无法连接 Milvus({settings.MILVUS_HOST}:{settings.MILVUS_PORT}): {exc}"
            ) from exc
        self._connected = True
        logger.info(
            "已连接 Milvus（chunk_vector_store）",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
        )

    def _get_collection(self, kb_id: str | None = None, load: bool = False) -> Collection:
        self._ensure_connected()
        collection_name = _get_collection_name(kb_id)

        if collection_name in self._collections:
            col = self._collections[collection_name]
            if load and collection_name not in self._loaded:
                try:
                    col.load()
                    self._loaded.add(collection_name)
                except Exception as e:
                    logger.warning(f"Collection load 失败: {e}")
            return col

        if not utility.has_collection(collection_name, using="chunk_store"):
            logger.info(
                "Collection 不存在，自动创建",
                collection=collection_name,
            )
            self._create_collection(collection_name)

        col = Collection(collection_name, using="chunk_store")
        self._collections[collection_name] = col

        if load:
            try:
                col.load()
                self._loaded.add(collection_name)
            except Exception as e:
                logger.warning(f"Collection load 失败: {e}")

        logger.info(
            "Collection 已准备",
            collection=collection_name,
            kb_id=kb_id or "global",
        )
        return col

    @staticmethod
    def _create_collection(collection_name: str) -> None:
        fields = [
            FieldSchema(
                name="chunk_id",
                dtype=DataType.VARCHAR,
                max_length=128,
                is_primary=True,
            ),
            FieldSchema(
                name="text",
                dtype=DataType.VARCHAR,
                max_length=65535,
            ),
            FieldSchema(
                name="dense_vector",
                dtype=DataType.FLOAT_VECTOR,
                dim=_EMBEDDING_DIM,
            ),
            FieldSchema(
                name="sparse_vector",
                dtype=DataType.SPARSE_FLOAT_VECTOR,
            ),
            FieldSchema(
                name="doc_id",
                dtype=DataType.VARCHAR,
                max_length=64,
            ),
            FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(
                name="hierarchy_path", dtype=DataType.VARCHAR, max_length=8192
            ),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
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
        ]

        schema = CollectionSchema(
            fields=fields,
            description="文档分块向量库（Dense+Sparse混合检索，支持父子块层级）",
        )
        collection = Collection(
            name=collection_name,
            schema=schema,
            using="chunk_store",
        )

        collection.create_index(
            field_name="dense_vector",
            index_params={
                "index_type": "HNSW",
                "metric_type": "IP",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
        collection.create_index(
            field_name="sparse_vector",
            index_params={
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": "IP",
            },
        )
        logger.info(
            "Collection 已创建并建立索引",
            collection=collection_name,
            dim=_EMBEDDING_DIM,
        )

    @classmethod
    def create_kb_collection(cls, kb_id: str) -> None:
        store = cls()
        store._ensure_connected()
        collection_name = _get_collection_name(kb_id)
        if not utility.has_collection(collection_name, using="chunk_store"):
            cls._create_collection(collection_name)
            logger.info("KB Chunk Collection已创建", extra={"collection_name": collection_name, "kb_id": kb_id})
        else:
            logger.info("KB Chunk Collection已存在", extra={"collection_name": collection_name, "kb_id": kb_id})
        store._get_collection(kb_id, load=False)

    @classmethod
    def drop_kb_collection(cls, kb_id: str) -> None:
        store = cls()
        store._ensure_connected()
        collection_name = _get_collection_name(kb_id)
        if collection_name in store._collections:
            del store._collections[collection_name]
        store._loaded.discard(collection_name)
        if utility.has_collection(collection_name, using="chunk_store"):
            utility.drop_collection(collection_name, using="chunk_store")
            logger.warning("KB Chunk Collection已删除", extra={"collection_name": collection_name, "kb_id": kb_id})

    @classmethod
    async def create_kb_collections(cls, kb_id) -> None:
        kb_id_str = str(kb_id) if not isinstance(kb_id, str) else kb_id
        cls.create_kb_collection(kb_id_str)

    @classmethod
    async def drop_kb_collections(cls, kb_id) -> None:
        kb_id_str = str(kb_id) if not isinstance(kb_id, str) else kb_id
        cls.drop_kb_collection(kb_id_str)

    async def count_kb(self, kb_id) -> int:
        kb_id_str = str(kb_id) if not isinstance(kb_id, str) else kb_id
        col = self._get_collection(kb_id_str, load=False)
        return col.num_entities

    async def insert(
        self, chunks: list[dict], kb_id: str | None = None
    ) -> list[int]:
        col = self._get_collection(kb_id, load=False)

        sparse_list: list[dict[int, float]] = []
        for c in chunks:
            sv = c.get("sparse_vector", {})
            if isinstance(sv, dict) and "indices" in sv and "values" in sv:
                sparse_list.append(
                    {int(k): float(v) for k, v in zip(sv["indices"], sv["values"])}
                )
            else:
                sparse_list.append({int(k): float(v) for k, v in sv.items()})

        data = [
            [c.get("chunk_id", "") for c in chunks],
            [c.get("text", "") for c in chunks],
            [c["dense_vector"].tolist() if isinstance(c.get("dense_vector"), np.ndarray) else c.get("dense_vector", []) for c in chunks],
            sparse_list,
            [c.get("doc_id", "") for c in chunks],
            [c.get("parent_id", "") for c in chunks],
            [c.get("hierarchy_path", "") for c in chunks],
            [c.get("title", "") for c in chunks],
            [c.get("parent_text", "") for c in chunks],
            [c.get("chunk_index", 0) for c in chunks],
            [c.get("level", 0) for c in chunks],
            [c.get("has_table", False) for c in chunks],
            [c.get("semantic_label", "") for c in chunks],
            [c.get("source_pages", []) for c in chunks],
        ]

        result = await asyncio.to_thread(col.insert, data)

        logger.info(
            "批量插入向量完成",
            count=len(chunks),
            inserted=result.insert_count,
            kb_id=kb_id or "global",
        )
        return result.primary_keys

    async def insert_chunks_from_popochunks(
        self,
        child_chunks: list[Any],
        doc_id: str,
        kb_id: str | None = None,
    ) -> int:
        if not child_chunks:
            return 0

        from app.services.embedding.embedding_service import embedding_service

        def _get_attr(chunk: Any, name: str, default: Any = None) -> Any:
            if isinstance(chunk, dict):
                return chunk.get(name, default)
            return getattr(chunk, name, default)

        texts = [_get_attr(chunk, "content", "") for chunk in child_chunks]
        embeddings = await embedding_service.embed_documents(texts)
        dense_vectors = embeddings["dense_vectors"]
        sparse_indices = embeddings["sparse_indices"]

        chunks_to_insert: list[dict] = []
        for idx, chunk in enumerate(child_chunks):
            chunks_to_insert.append({
                "chunk_id": _get_attr(chunk, "id", ""),
                "text": _get_attr(chunk, "content", ""),
                "dense_vector": dense_vectors[idx],
                "sparse_vector": sparse_indices[idx],
                "doc_id": doc_id,
                "parent_id": _get_attr(chunk, "parent_id", ""),
                "hierarchy_path": _get_attr(chunk, "hierarchy_path", ""),
                "title": _get_attr(chunk, "title", ""),
                "parent_text": _get_attr(chunk, "parent_text", ""),
                "chunk_index": _get_attr(chunk, "chunk_index", idx),
                "level": _get_attr(chunk, "level", 0),
                "has_table": _get_attr(chunk, "has_table", False),
                "semantic_label": _get_attr(chunk, "semantic_label", ""),
                "source_pages": _get_attr(chunk, "source_pages", []),
            })

        await self.insert(chunks_to_insert, kb_id=kb_id)
        logger.info(
            "Popo ChildChunks插入完成",
            doc_id=doc_id,
            chunk_count=len(child_chunks),
            kb_id=kb_id or "global",
        )
        return len(child_chunks)

    async def hybrid_search(
        self,
        query_dense: np.ndarray,
        query_sparse: dict,
        top_k: int = 10,
        ef: int = 64,
        kb_id: str | None = None,
    ) -> list[dict]:
        col = self._get_collection(kb_id, load=True)

        if isinstance(query_sparse, dict) and "indices" in query_sparse and "values" in query_sparse:
            query_sparse_dict: dict[int, float] = {
                int(k): float(v)
                for k, v in zip(query_sparse["indices"], query_sparse["values"])
            }
        else:
            query_sparse_dict = {int(k): float(v) for k, v in query_sparse.items()}

        ef_search = max(ef, top_k * 2)
        try:
            dense_results = await asyncio.wait_for(
                asyncio.to_thread(
                    col.search,
                    data=[query_dense.tolist()],
                    anns_field="dense_vector",
                    param={"metric_type": "IP", "params": {"ef": ef_search}},
                    limit=top_k * 2,
                    output_fields=[
                        "chunk_id", "text", "doc_id", "parent_id", "hierarchy_path",
                        "title", "parent_text", "chunk_index", "level",
                        "has_table", "semantic_label", "source_pages",
                    ],
                ),
                timeout=20.0,
            )
        except asyncio.TimeoutError as exc:
            logger.error("Dense 检索超时（20s）", ef=ef_search, top_k=top_k)
            raise RuntimeError("向量检索超时，请稍后重试") from exc

        try:
            sparse_results = await asyncio.wait_for(
                asyncio.to_thread(
                    col.search,
                    data=[query_sparse_dict],
                    anns_field="sparse_vector",
                    param={"metric_type": "IP"},
                    limit=top_k * 2,
                    output_fields=[
                        "chunk_id", "text", "doc_id", "parent_id", "hierarchy_path",
                        "title", "parent_text", "chunk_index", "level",
                        "has_table", "semantic_label", "source_pages",
                    ],
                ),
                timeout=20.0,
            )
        except asyncio.TimeoutError as exc:
            logger.error("Sparse 检索超时（20s）", top_k=top_k)
            raise RuntimeError("向量检索超时，请稍后重试") from exc

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
            kb_id=kb_id or "global",
        )
        return fused

    def _reciprocal_rank_fusion(
        self, dense_hits: Any, sparse_hits: Any, top_k: int, k: int = 60
    ) -> list[dict]:
        scores: dict[Any, dict] = {}

        for rank, hit in enumerate(dense_hits):
            pk = hit.id
            entity = hit.entity.to_dict()["entity"] if hasattr(hit, "entity") else {}
            scores[pk] = {
                "score": 1.0 / (k + rank + 1),
                "entity": entity,
                "dense_rank": rank + 1,
            }

        for rank, hit in enumerate(sparse_hits):
            pk = hit.id
            entity = hit.entity.to_dict()["entity"] if hasattr(hit, "entity") else {}
            if pk in scores:
                scores[pk]["score"] += 1.0 / (k + rank + 1)
                scores[pk]["sparse_rank"] = rank + 1
            else:
                scores[pk] = {
                    "score": 1.0 / (k + rank + 1),
                    "entity": entity,
                    "sparse_rank": rank + 1,
                }

        sorted_results = sorted(
            scores.items(), key=lambda x: x[1]["score"], reverse=True
        )

        results: list[dict] = []
        for rank, (pk, info) in enumerate(sorted_results[:top_k]):
            entity = info["entity"]
            results.append(
                {
                    "id": pk,
                    "chunk_id": entity.get("chunk_id", ""),
                    "text": entity.get("text", ""),
                    "doc_id": entity.get("doc_id", ""),
                    "parent_id": entity.get("parent_id", ""),
                    "hierarchy_path": entity.get("hierarchy_path", ""),
                    "title": entity.get("title", ""),
                    "parent_text": entity.get("parent_text", ""),
                    "chunk_index": entity.get("chunk_index", 0),
                    "level": entity.get("level", 0),
                    "has_table": entity.get("has_table", False),
                    "semantic_label": entity.get("semantic_label", ""),
                    "source_pages": entity.get("source_pages", []),
                    "score": info["score"],
                    "rank": rank + 1,
                }
            )

        return results

    async def delete_by_doc_id(
        self, doc_id: str, kb_id: str | None = None
    ) -> int:
        def _do_delete() -> Any:
            col = self._get_collection(kb_id, load=False)
            try:
                if col.num_entities == 0:
                    logger.info(
                        "Collection 数据量为 0，跳过 delete",
                        doc_id=doc_id,
                        kb_id=kb_id or "global",
                    )
                    return type('R', (), {'delete_count': 0})()
            except Exception as exc:
                logger.warning(
                    "检查 num_entities 失败，继续尝试 delete",
                    error=str(exc)[:200],
                )
            return col.delete(expr=f'doc_id == "{doc_id}"')

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_do_delete),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "按 doc_id 删除向量超时（10s），跳过",
                doc_id=doc_id,
                kb_id=kb_id or "global",
            )
            return 0

        deleted = getattr(result, 'delete_count', 0)
        logger.info(
            "按 doc_id 删除向量完成",
            doc_id=doc_id,
            deleted=deleted,
            kb_id=kb_id or "global",
        )
        return deleted

    async def delete_all(self, kb_id: str | None = None) -> None:
        self._ensure_connected()
        collection_name = _get_collection_name(kb_id)

        def _drop_sync() -> None:
            if utility.has_collection(collection_name, using="chunk_store"):
                utility.drop_collection(collection_name, using="chunk_store")
                logger.info("集合已删除", collection=collection_name)

        await asyncio.to_thread(_drop_sync)

        if collection_name in self._collections:
            del self._collections[collection_name]
        self._loaded.discard(collection_name)


chunk_vector_store = ChunkVectorStore()
vector_store = chunk_vector_store
