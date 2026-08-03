"""sm_item Milvus 向量索引（v3 重写，迁移自 project_dict_store）。

专门管理 ``sm_item`` 检测项目的向量化存储与检索，用于：
1. 动态白名单生成：按大类(FEATURE)检索相关标准项目
2. 抽取后跨类校验：全表检索确定项目真实归属大类

数据来源：PostgreSQL ``sm_item`` 表
向量化策略：对 NAME + ITEM_ALIAS 分别向量化入库，提升别名召回率
检索方式：Dense 向量 HNSW + IP（归一化向量等价余弦相似度）

Schema 字段：
    - item_id: VARCHAR(128), 主键（feature + name + alias_idx 的 md5）
    - canonical_name: VARCHAR(200), 标准项目名
    - vector: FLOAT_VECTOR(1024), bge-m3 密集向量
    - feature: VARCHAR(100), 项目大类
    - aliases: JSON, 别名数组
    - unit: VARCHAR(50), 标准单位
    - item_pk: INT64, sm_item.id
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
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

# bge-m3 Dense 向量维度
_EMBEDDING_DIM = 1024


def _make_item_id(feature: str, canonical_name: str, alias_idx: int = 0) -> str:
    """根据大类+项目名+别名序号生成确定性主键。

    同一 (feature, canonical_name, alias_idx) 始终生成相同 item_id，便于 upsert。
    alias_idx 用于区分同一项目的 NAME 向量(idx=0)和别名向量(idx>0)。
    """
    raw = f"{feature}::{canonical_name}::{alias_idx}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:32]


class BaseDataStore:
    """sm_item Milvus 向量库封装（单例 + 懒加载）。

    与 ``FiveDimVectorStore`` 独立，使用 default alias 连接 Milvus，
    Collection 名通过 ``settings.MILVUS_PROJECT_DICT_COLLECTION`` 配置。

    所有同步 Milvus 调用通过 ``asyncio.to_thread`` 包装为异步接口。
    """

    _instance: "BaseDataStore | None" = None
    _collection: Collection | None = None
    _connected: bool = False

    def __new__(cls) -> "BaseDataStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化，不连接 Milvus（懒加载）。"""

    def _ensure_connected(self) -> Collection:
        """确保已连接 Milvus 并返回 Collection（懒加载）。"""
        if self._collection is not None:
            return self._collection

        if not self._connected:
            self._connect()

        collection_name = settings.MILVUS_PROJECT_DICT_COLLECTION
        if not utility.has_collection(collection_name):
            self._create_collection(collection_name)

        self._collection = Collection(collection_name)
        self._collection.load()
        return self._collection

    def _connect(self) -> None:
        """连接 Milvus（复用 default alias）。"""
        try:
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=str(settings.MILVUS_PORT),
            )
        except Exception as exc:
            if "already connected" not in str(exc).lower():
                raise RuntimeError(
                    f"无法连接 Milvus({settings.MILVUS_HOST}:{settings.MILVUS_PORT}): {exc}"
                ) from exc
        self._connected = True
        logger.info(
            "Milvus 连接建立（base_data）",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
        )

    @staticmethod
    def _create_collection(collection_name: str) -> None:
        """创建 sm_item Collection 及 HNSW 索引。"""
        fields = [
            FieldSchema(name="item_id", dtype=DataType.VARCHAR, max_length=128, is_primary=True),
            FieldSchema(name="canonical_name", dtype=DataType.VARCHAR, max_length=200),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=_EMBEDDING_DIM),
            FieldSchema(name="feature", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="aliases", dtype=DataType.JSON),
            FieldSchema(name="unit", dtype=DataType.VARCHAR, max_length=50),
            FieldSchema(name="item_pk", dtype=DataType.INT64),
        ]
        schema = CollectionSchema(
            fields=fields, description="检测项目字典向量库（sm_item，动态白名单+跨类校验）"
        )
        collection = Collection(name=collection_name, schema=schema, using="default")
        collection.create_index(
            field_name="vector",
            index_params={
                "index_type": "HNSW",
                "metric_type": "IP",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
        logger.info("base_data Collection 已创建", collection=collection_name)

    # ------------------------------------------------------------------
    # 数据操作
    # ------------------------------------------------------------------

    async def upsert(self, items: list[dict]) -> int:
        """批量 upsert sm_item 向量记录（先删后插）。"""
        if not items:
            return 0

        collection = self._ensure_connected()
        item_ids = [it["item_id"] for it in items]

        # 分批删除已存在的 item_id
        delete_batch = 500
        for i in range(0, len(item_ids), delete_batch):
            batch_ids = item_ids[i : i + delete_batch]
            id_list = ",".join(f'"{_id}"' for _id in batch_ids)
            await asyncio.to_thread(collection.delete, expr=f"item_id in [{id_list}]")

        # 插入数据
        data = [
            item_ids,
            [it["canonical_name"] for it in items],
            [it["vector"].tolist() for it in items],
            [it["feature"] for it in items],
            [it.get("aliases", []) for it in items],
            [it.get("unit", "") for it in items],
            [int(it.get("item_pk", 0)) for it in items],
        ]
        result = await asyncio.to_thread(collection.insert, data)
        logger.info("base_data 批量 upsert 完成", extra={"count": len(items), "inserted": result.insert_count})
        return result.insert_count

    async def search_by_feature(
        self,
        query_vector: np.ndarray,
        feature: str,
        top_k: int = 15,
        ef: int = 64,
    ) -> list[dict[str, Any]]:
        """在指定大类内做向量最近邻检索（动态白名单生成用）。

        通过 ``expr`` 过滤 feature 后再向量检索，避免跨类误匹配。

        Args:
            query_vector: 查询向量 (1024,)，已归一化。
            feature: 限定检索的项目大类（sm_item.FEATURE）。
            top_k: 返回结果数。
            ef: HNSW 搜索宽度。

        Returns:
            list[dict]: 检索结果，按相似度降序，每项含
                item_id/canonical_name/feature/aliases/unit/item_pk/score。
        """
        collection = self._ensure_connected()
        ef_search = max(ef, top_k * 2)

        results = await asyncio.to_thread(
            collection.search,
            data=[query_vector.tolist()],
            anns_field="vector",
            param={"metric_type": "IP", "params": {"ef": ef_search}},
            limit=top_k,
            expr=f'feature == "{feature}"',
            output_fields=["item_id", "canonical_name", "feature", "aliases", "unit", "item_pk"],
        )

        hits = results[0] if results else []
        output: list[dict[str, Any]] = []
        for hit in hits:
            entity = hit.entity.to_dict()["entity"]
            output.append({
                "item_id": entity.get("item_id", ""),
                "canonical_name": entity.get("canonical_name", ""),
                "feature": entity.get("feature", ""),
                "aliases": entity.get("aliases", []) or [],
                "unit": entity.get("unit", ""),
                "item_pk": entity.get("item_pk", 0),
                "score": float(hit.score),
            })
        return output

    async def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """全表向量检索（不限大类），用于抽取后跨类校验。

        Args:
            query_vector: 查询向量 (1024,)，已归一化。
            top_k: 返回结果数。

        Returns:
            list[dict]: 检索结果，按相似度降序，字段同 search_by_feature。
        """
        collection = self._ensure_connected()

        results = await asyncio.to_thread(
            collection.search,
            data=[query_vector.tolist()],
            anns_field="vector",
            param={"metric_type": "IP", "params": {"ef": max(64, top_k * 2)}},
            limit=top_k,
            output_fields=["item_id", "canonical_name", "feature", "aliases", "unit", "item_pk"],
        )

        hits = results[0] if results else []
        output: list[dict[str, Any]] = []
        for hit in hits:
            entity = hit.entity.to_dict()["entity"]
            output.append({
                "item_id": entity.get("item_id", ""),
                "canonical_name": entity.get("canonical_name", ""),
                "feature": entity.get("feature", ""),
                "aliases": entity.get("aliases", []) or [],
                "unit": entity.get("unit", ""),
                "item_pk": entity.get("item_pk", 0),
                "score": float(hit.score),
            })
        return output

    async def count(self) -> int:
        """统计向量记录总数。"""
        collection = self._ensure_connected()
        return collection.num_entities

    async def delete_all(self) -> None:
        """删除整个集合（用于全量重建前清理）。"""
        try:
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=str(settings.MILVUS_PORT),
            )
        except Exception as exc:
            if "already connected" not in str(exc).lower():
                raise RuntimeError(f"无法连接 Milvus: {exc}") from exc

        collection_name = settings.MILVUS_PROJECT_DICT_COLLECTION

        def _drop_sync() -> None:
            if utility.has_collection(collection_name):
                utility.drop_collection(collection_name)
                logger.info("base_data 集合已删除", collection=collection_name)

        await asyncio.to_thread(_drop_sync)
        BaseDataStore._collection = None
        BaseDataStore._connected = False

    async def rebuild(self, items: list[dict]) -> int:
        """全量重建（删后重建），分批插入避免单次过大。

        Args:
            items: 待插入的记录列表，每项含 item_id/canonical_name/vector/
                feature/aliases/unit/item_pk。

        Returns:
            int: 实际插入的记录数。
        """
        await self.delete_all()
        if not items:
            logger.warning("base_data rebuild: items 为空，仅清理未插入")
            return 0

        batch_size = 500
        total_inserted = 0
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            inserted = await self.upsert(batch)
            total_inserted += inserted

        logger.info(
            "base_data 全量重建完成",
            extra={"total_items": len(items), "total_inserted": total_inserted},
        )
        return total_inserted


# 模块级单例
base_data_store = BaseDataStore()
