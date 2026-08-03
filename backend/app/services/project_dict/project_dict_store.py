"""Milvus 基础表向量库封装 - 检测项目向量检索。

独立于 ``vector_store`` 的 doc_chunks 集合，专门管理 ``sm_item`` 检测项目的
向量化存储与检索，用于：
1. 动态白名单生成：根据召回分块中的项目候选，按大类(FEATURE)检索相关标准项目
2. 抽取后校验：将 LLM 输出的项目名向量匹配到 sm_item，确定真实归属大类(FEATURE)

数据来源：
- PostgreSQL ``sm_item`` 表（每条记录 NAME + ITEM_ALIAS + FEATURE + UNIT）
- 对 NAME 和 ITEM_ALIAS 分别向量化，全部入库（提升别名召回率）
- FEATURE 字段作为 category 过滤键（关联 sm_feature.NAME）

知识库隔离（方案 §9.3，"全局共享 + KB 覆盖"语义）：
- 基础字典三表 sm_item 遵循 ``kb_id IS NULL`` 为全局共享、非 NULL 为 KB 专属。
- 本库对应采用**双 Collection**策略：
  * 全局 Collection（``settings.MILVUS_PROJECT_DICT_COLLECTION``）：存 kb_id=NULL 的全局 sm_item 向量。
  * KB 专属 Collection（``project_dict{sep}{kb_id_hex}``）：存该 KB 覆盖的 sm_item 向量。
- 检索时若提供 ``kb_id``，先查 KB 专属 Collection，不足再从全局补充，
  按 ``canonical_name`` 去重（KB 覆盖优先），保留"全局共享 + KB 覆盖"语义。
- ``_make_item_id`` 入参增加 ``kb_id`` 维度，避免跨 Collection 主键碰撞。

设计要点：
- 仅使用 Dense 向量（bge-m3 1024 维）：项目名是短文本，Dense 足够
- 支持 category 过滤检索：通过 ``expr: feature == "X"`` 避免跨类误匹配
  （注意：sm_method.FEATURE 部分是方法分类而非大类名，本集合仅存 sm_item，
  FEATURE 取值基本都是 sm_feature.NAME，可安全用于类别过滤）
- 全量重建策略：同步时 delete_all + 重新插入，简单可靠

Schema 字段：
    - item_id: VARCHAR(128), 主键（kb_id + feature + canonical_name + alias 序号的 hash）
    - canonical_name: VARCHAR(200), 标准项目名（sm_item.NAME）
    - vector: FLOAT_VECTOR(1024), bge-m3 密集向量
    - feature: VARCHAR(100), 项目大类（sm_item.FEATURE，关联 sm_feature.NAME）
    - aliases: JSON, 别名数组（sm_item.ITEM_ALIAS 拆分）
    - unit: VARCHAR(50), 标准单位
    - item_pk: INTEGER, sm_item.id（用于回查 PG 获取完整信息）

索引：
    - vector: HNSW (IP), M=16, efConstruction=200

使用示例：
    from app.services.project_dict.project_dict_store import project_dict_store

    # 全量重建（全局）
    await project_dict_store.rebuild(items)

    # 全量重建（KB 覆盖层）
    await project_dict_store.rebuild(items, kb_id=kb_id)

    # 大类内检索（动态白名单，KB 感知：KB 专属优先 + 全局补充）
    hits = await project_dict_store.search_by_feature(
        query_vector=vec, feature="室温拉伸", top_k=15, kb_id=kb_id
    )

    # 全表检索（抽取后校验）
    hits = await project_dict_store.search(query_vector=vec, top_k=1)
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
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

# bge-m3 Dense 向量维度（与 doc_chunks 一致）
_EMBEDDING_DIM = 1024


def _kb_collection_name(kb_id: uuid.UUID) -> str:
    """生成某 KB 的 project_dict Collection 名（project_dict{sep}{kb_id_hex}）。

    与 ``kb_lifecycle`` 命名规则保持一致：``{base}{sep}{kb_id_hex}``。
    """
    sep = settings.KB_MILVUS_COLLECTION_SEPARATOR
    return f"{settings.MILVUS_PROJECT_DICT_COLLECTION}{sep}{kb_id.hex}"


def _make_item_id(
    feature: str,
    canonical_name: str,
    alias_idx: int = 0,
    kb_id: uuid.UUID | None = None,
) -> str:
    """根据 kb_id+大类+项目名+别名序号生成确定性主键。

    同一 (kb_id, feature, canonical_name, alias_idx) 始终生成相同 item_id，便于 upsert。
    alias_idx 用于区分同一项目的 NAME 向量(idx=0)和别名向量(idx>0)。
    ``kb_id`` 参与哈希，避免全局记录与 KB 覆盖记录在各自 Collection 内主键碰撞
    （虽然两 Collection 物理隔离，但保持主键与业务来源一致更利于排查）。

    Args:
        feature: 项目大类（sm_item.FEATURE）。
        canonical_name: 标准项目名（sm_item.NAME）。
        alias_idx: 别名序号，0 表示 NAME 自身，>0 表示第几个别名。
        kb_id: 知识库 ID。None 表示全局记录。

    Returns:
        str: 确定性主键字符串（md5 前 32 字符）。
    """
    kb_tag = kb_id.hex if kb_id is not None else "global"
    raw = f"{kb_tag}::{feature}::{canonical_name}::{alias_idx}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:32]


class ProjectDictStore:
    """Milvus 基础表向量库封装（单例 + 懒加载）。

    与 ``VectorStore`` 一致采用单例模式，Milvus 连接与 Collection 在首次
    实际调用时加载。所有同步 Milvus 调用通过 ``asyncio.to_thread`` 包装为
    异步接口，避免阻塞事件循环。

    知识库隔离采用"全局共享 + KB 覆盖层"双 Collection 策略：
    - 全局 Collection（``kb_id=None``）：存全局 sm_item 向量，向后兼容旧流程。
    - KB 专属 Collection（``kb_id`` 非 None）：存该 KB 覆盖的 sm_item 向量。
    检索时 ``kb_id`` 非 None 会合并 KB 专属 + 全局结果（KB 优先、按名去重）。

    Attributes:
        _collection: 全局 Milvus Collection 对象，懒加载。
        _connected: 是否已建立连接。
        _kb_collections: KB 专属 Collection 缓存 ``{kb_id_hex: Collection}``。
    """

    _instance: "ProjectDictStore | None" = None
    _collection: Collection | None = None
    _connected: bool = False
    _kb_collections: dict[str, Collection] | None = None

    def __new__(cls) -> "ProjectDictStore":
        """单例模式 - Collection 仅连接加载一次。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化，不连接 Milvus（懒加载）。"""

    def _ensure_connected(self) -> None:
        """确保已连接 Milvus（懒加载入口）。"""
        if not self._connected:
            self._connect()

    def _connect(self) -> None:
        """连接 Milvus 并加载全局基础表 Collection（不存在时自动创建）。

        复用 default alias 的 Milvus 连接（与 ``vector_store`` 共享连接，
        避免重复建立连接）。Collection 不存在时按 schema 创建并建立索引。

        Raises:
            RuntimeError: Milvus 连接失败时抛出。
        """
        try:
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=str(settings.MILVUS_PORT),
            )
        except Exception as exc:  # noqa: BLE001 - 顶层统一捕获连接类异常
            # 连接已存在时 pymilvus 会抛异常，忽略即可
            if "already connected" not in str(exc).lower():
                logger.error(
                    "连接 Milvus 失败（project_dict）",
                    host=settings.MILVUS_HOST,
                    port=settings.MILVUS_PORT,
                    error=str(exc),
                )
                raise RuntimeError(
                    f"无法连接 Milvus({settings.MILVUS_HOST}:{settings.MILVUS_PORT}): {exc}"
                ) from exc

        collection_name = settings.MILVUS_PROJECT_DICT_COLLECTION

        if not utility.has_collection(collection_name):
            logger.info(
                "project_dict Collection 不存在，自动创建",
                collection=collection_name,
            )
            self._create_collection(collection_name)

        self._collection = Collection(collection_name)
        self._collection.load()
        self._connected = True
        logger.info(
            "已连接 Milvus 并加载 project_dict Collection",
            collection=collection_name,
        )

    @staticmethod
    def _create_collection(collection_name: str) -> None:
        """创建基础表 Collection 及 HNSW 索引。

        Args:
            collection_name: 集合名称。
        """
        fields = [
            FieldSchema(
                name="item_id",
                dtype=DataType.VARCHAR,
                max_length=128,
                is_primary=True,
            ),
            FieldSchema(
                name="canonical_name",
                dtype=DataType.VARCHAR,
                max_length=200,
            ),
            FieldSchema(
                name="vector",
                dtype=DataType.FLOAT_VECTOR,
                dim=_EMBEDDING_DIM,
            ),
            FieldSchema(
                name="feature",
                dtype=DataType.VARCHAR,
                max_length=100,
            ),
            FieldSchema(
                name="aliases",
                dtype=DataType.JSON,
            ),
            FieldSchema(
                name="unit",
                dtype=DataType.VARCHAR,
                max_length=50,
            ),
            FieldSchema(
                name="item_pk",
                dtype=DataType.INT64,
            ),
        ]

        schema = CollectionSchema(
            fields=fields, description="检测项目字典向量库（基于 sm_item，动态白名单检索）"
        )
        collection = Collection(name=collection_name, schema=schema, using="default")

        # Dense 向量索引：HNSW + IP（归一化向量等价于余弦相似度）
        collection.create_index(
            field_name="vector",
            index_params={
                "index_type": "HNSW",
                "metric_type": "IP",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
        logger.info(
            "project_dict Collection 已创建并建立索引",
            collection=collection_name,
            dim=_EMBEDDING_DIM,
        )

    # ============================================================
    # 知识库隔离路由（方案 §9.3，全局共享 + KB 覆盖层）
    # ============================================================
    def _resolve_collection(self, kb_id: uuid.UUID | None = None) -> Collection:
        """解析目标 Collection。

        - ``kb_id`` 为 None：返回全局单例 Collection（向后兼容旧流程）。
        - ``kb_id`` 不为 None：返回该 KB 专属 Collection（懒加载并缓存；
          不存在则自动创建）。

        Args:
            kb_id: 知识库 ID，None 表示走全局 Collection。

        Returns:
            Collection: 目标 Milvus Collection 对象。
        """
        if kb_id is None:
            self._ensure_connected()
            assert self._collection is not None
            return self._collection
        return self._get_kb_collection(kb_id)

    def _get_kb_collection(self, kb_id: uuid.UUID) -> Collection:
        """获取（必要时创建并加载）KB 专属 Collection，带缓存。"""
        if self._kb_collections is None:
            self._kb_collections = {}
        key = kb_id.hex
        cached = self._kb_collections.get(key)
        if cached is not None:
            return cached

        # 确保已连接 Milvus
        self._ensure_connected()

        name = _kb_collection_name(kb_id)
        if not utility.has_collection(name):
            logger.info("KB project_dict Collection 不存在，自动创建", collection=name, kb_id=str(kb_id))
            ProjectDictStore._create_collection(name)
        col = Collection(name)
        col.load()
        self._kb_collections[key] = col
        logger.info("已加载 KB project_dict Collection", collection=name, kb_id=str(kb_id))
        return col

    async def create_kb_collections(self, kb_id: uuid.UUID) -> None:
        """创建 KB 专属 project_dict Collection（供 kb_lifecycle 调用）。

        幂等：已存在则跳过。创建后立即加载到内存并缓存。
        注意：KB 专属 Collection 仅存该 KB 覆盖的 sm_item，全局 sm_item 仍存全局 Collection。
        """
        self._ensure_connected()
        name = _kb_collection_name(kb_id)
        if not utility.has_collection(name):
            ProjectDictStore._create_collection(name)
            logger.info("KB project_dict Collection 已创建", collection=name, kb_id=str(kb_id))
        # 加载并缓存
        self._get_kb_collection(kb_id)

    async def drop_kb_collections(self, kb_id: uuid.UUID) -> None:
        """删除 KB 专属 project_dict Collection（供 kb_lifecycle 调用，合规销毁）。

        幂等：不存在则跳过。同时清理缓存。仅删除 KB 覆盖层，全局 Collection 不受影响。
        """
        self._ensure_connected()
        name = _kb_collection_name(kb_id)
        if self._kb_collections is not None:
            self._kb_collections.pop(kb_id.hex, None)
        if utility.has_collection(name):
            utility.drop_collection(name)
            logger.warning("KB project_dict Collection 已删除", collection=name, kb_id=str(kb_id))

    async def count_kb(self, kb_id: uuid.UUID) -> int:
        """统计 KB 专属 Collection 的记录数。"""
        col = self._resolve_collection(kb_id)
        return col.num_entities

    async def upsert(
        self, items: list[dict], kb_id: uuid.UUID | None = None
    ) -> int:
        """批量 upsert 基础表向量记录。

        采用「先按 item_id 删除再插入」的 upsert 策略，确保同一项目
        重复同步时更新而非重复插入。

        Args:
            items: 待插入的记录列表，每项包含：
                - item_id: str, 确定性主键
                - canonical_name: str, 标准项目名
                - vector: np.ndarray (1024,), 已归一化的密集向量
                - feature: str, 项目大类
                - aliases: list[str], 别名数组
                - unit: str, 标准单位
                - item_pk: int, sm_item.id
            kb_id: 知识库 ID。None 时写入全局 Collection（向后兼容），
                非 None 时写入该 KB 专属 Collection（KB 覆盖层）。

        Returns:
            int: 实际插入的记录数。
        """
        if not items:
            return 0

        col = self._resolve_collection(kb_id)

        # 构造 item_id 与数据列
        item_ids = [it["item_id"] for it in items]

        # 先删除已存在的 item_id（upsert 语义），分批避免 expr 过长
        delete_batch = 500
        for i in range(0, len(item_ids), delete_batch):
            batch_ids = item_ids[i : i + delete_batch]
            id_list = ",".join(f'"{_id}"' for _id in batch_ids)
            await asyncio.to_thread(
                col.delete, expr=f"item_id in [{id_list}]"
            )

        # 组织插入数据
        data = [
            item_ids,                                              # item_id
            [it["canonical_name"] for it in items],                # canonical_name
            [it["vector"].tolist() for it in items],               # vector
            [it["feature"] for it in items],                       # feature
            [it.get("aliases", []) for it in items],               # aliases
            [it.get("unit") or "" for it in items],                # unit
            [int(it.get("item_pk", 0)) for it in items],            # item_pk
        ]

        result = await asyncio.to_thread(col.insert, data)
        logger.info(
            "project_dict 批量 upsert 完成",
            count=len(items),
            inserted=result.insert_count,
            kb_id=str(kb_id) if kb_id else "global",
        )
        return result.insert_count

    async def search_by_feature(
        self,
        query_vector: np.ndarray,
        feature: str,
        top_k: int = 15,
        ef: int = 64,
        kb_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """在指定大类内做向量最近邻检索（动态白名单生成用）。

        关键优化：通过 ``expr`` 过滤 feature 后再向量检索，避免跨类误匹配
        （如 N 在化学成分和气体分析都有），同时大幅缩小检索范围提升速度。

        知识库隔离（``kb_id`` 非 None 时）：
        1. 先在 KB 专属 Collection 检索 top_k
        2. 不足 top_k 时从全局 Collection 补充（按 ``canonical_name`` 去重，KB 优先）
        3. 合并后按相似度降序取 top_k
        ``kb_id=None`` 时仅检索全局 Collection（向后兼容）。

        Args:
            query_vector: 查询向量 (1024,), 已归一化。
            feature: 限定检索的项目大类（sm_item.FEATURE）。
            top_k: 返回结果数，默认 15。
            ef: HNSW 搜索宽度，需 ≥ top_k。
            kb_id: 知识库 ID。None 时仅检索全局（向后兼容）；
                非 None 时合并 KB 专属 + 全局（KB 覆盖优先）。

        Returns:
            list[dict]: 检索结果，按相似度降序，每项包含：
                - item_id, canonical_name, feature, aliases, unit, item_pk
                - score: 余弦相似度（IP + 归一化）
                - source: "kb" | "global"（KB 专属或全局来源）
        """
        # KB 感知：先查 KB 专属，不足补全局
        if kb_id is not None:
            kb_hits = await self._search_by_feature_in(
                query_vector, feature, top_k, ef, kb_id
            )
            # 已满足 top_k 则直接返回
            if len(kb_hits) >= top_k:
                return kb_hits[:top_k]
            # 不足：从全局补充，按 canonical_name 去重
            global_hits = await self._search_by_feature_in(
                query_vector, feature, top_k, ef, None
            )
            seen = {h["canonical_name"] for h in kb_hits}
            merged = list(kb_hits)
            for h in global_hits:
                if h["canonical_name"] not in seen:
                    merged.append(h)
                    seen.add(h["canonical_name"])
                    if len(merged) >= top_k:
                        break
            merged.sort(key=lambda x: x["score"], reverse=True)
            return merged[:top_k]

        # 全局检索（向后兼容）
        return await self._search_by_feature_in(query_vector, feature, top_k, ef, None)

    async def _search_by_feature_in(
        self,
        query_vector: np.ndarray,
        feature: str,
        top_k: int,
        ef: int,
        kb_id: uuid.UUID | None,
    ) -> list[dict]:
        """在单个 Collection（全局或 KB 专属）内做大类过滤检索。"""
        col = self._resolve_collection(kb_id)
        source = "kb" if kb_id is not None else "global"

        ef_search = max(ef, top_k * 2)
        results = await asyncio.to_thread(
            col.search,
            data=[query_vector.tolist()],
            anns_field="vector",
            param={"metric_type": "IP", "params": {"ef": ef_search}},
            limit=top_k,
            expr=f'feature == "{feature}"',
            output_fields=[
                "item_id",
                "canonical_name",
                "feature",
                "aliases",
                "unit",
                "item_pk",
            ],
        )

        hits = results[0] if results else []
        output: list[dict] = []
        for hit in hits:
            entity = hit.entity.to_dict()["entity"]
            output.append(
                {
                    "item_id": entity.get("item_id", ""),
                    "canonical_name": entity.get("canonical_name", ""),
                    "feature": entity.get("feature", ""),
                    "aliases": entity.get("aliases", []) or [],
                    "unit": entity.get("unit", ""),
                    "item_pk": entity.get("item_pk", 0),
                    "score": float(hit.score),
                    "source": source,
                }
            )

        logger.info(
            "project_dict 大类内检索完成",
            feature=feature,
            top_k=top_k,
            hits=len(output),
            kb_id=str(kb_id) if kb_id else "global",
        )
        return output

    # 旧接口名保留别名，向后兼容（extraction_service 调用）
    search_by_category = search_by_feature

    async def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        kb_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """全表向量检索（不限大类），用于抽取后校验项目归属。

        知识库隔离（``kb_id`` 非 None 时）：
        1. 先在 KB 专属 Collection 检索 top_k
        2. 不足 top_k 时从全局 Collection 补充（按 ``canonical_name`` 去重，KB 优先）
        3. 合并后按相似度降序取 top_k
        ``kb_id=None`` 时仅检索全局 Collection（向后兼容）。

        Args:
            query_vector: 查询向量 (1024,), 已归一化。
            top_k: 返回结果数，默认 5。
            kb_id: 知识库 ID。None 时仅检索全局（向后兼容）；
                非 None 时合并 KB 专属 + 全局（KB 覆盖优先）。

        Returns:
            list[dict]: 检索结果，按相似度降序，字段同 search_by_feature。
        """
        # KB 感知：先查 KB 专属，不足补全局
        if kb_id is not None:
            kb_hits = await self._search_in(query_vector, top_k, kb_id)
            if len(kb_hits) >= top_k:
                return kb_hits[:top_k]
            global_hits = await self._search_in(query_vector, top_k, None)
            seen = {h["canonical_name"] for h in kb_hits}
            merged = list(kb_hits)
            for h in global_hits:
                if h["canonical_name"] not in seen:
                    merged.append(h)
                    seen.add(h["canonical_name"])
                    if len(merged) >= top_k:
                        break
            merged.sort(key=lambda x: x["score"], reverse=True)
            return merged[:top_k]

        # 全局检索（向后兼容）
        return await self._search_in(query_vector, top_k, None)

    async def _search_in(
        self,
        query_vector: np.ndarray,
        top_k: int,
        kb_id: uuid.UUID | None,
    ) -> list[dict]:
        """在单个 Collection（全局或 KB 专属）内做全表检索。"""
        col = self._resolve_collection(kb_id)
        source = "kb" if kb_id is not None else "global"

        results = await asyncio.to_thread(
            col.search,
            data=[query_vector.tolist()],
            anns_field="vector",
            param={"metric_type": "IP", "params": {"ef": max(64, top_k * 2)}},
            limit=top_k,
            output_fields=[
                "item_id",
                "canonical_name",
                "feature",
                "aliases",
                "unit",
                "item_pk",
            ],
        )

        hits = results[0] if results else []
        output: list[dict] = []
        for hit in hits:
            entity = hit.entity.to_dict()["entity"]
            output.append(
                {
                    "item_id": entity.get("item_id", ""),
                    "canonical_name": entity.get("canonical_name", ""),
                    "feature": entity.get("feature", ""),
                    "aliases": entity.get("aliases", []) or [],
                    "unit": entity.get("unit", ""),
                    "item_pk": entity.get("item_pk", 0),
                    "score": float(hit.score),
                    "source": source,
                }
            )
        return output

    async def count(self, kb_id: uuid.UUID | None = None) -> int:
        """统计基础表向量记录总数。

        Args:
            kb_id: 知识库 ID。None 时统计全局 Collection（向后兼容），
                非 None 时统计该 KB 专属 Collection。
        """
        col = self._resolve_collection(kb_id)
        return col.num_entities

    async def delete_all(self, kb_id: uuid.UUID | None = None) -> None:
        """删除集合（用于全量重建前清理）。

        Args:
            kb_id: 知识库 ID。None 时删除全局 Collection（向后兼容），
                非 None 时删除该 KB 专属 Collection。
        """
        try:
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=str(settings.MILVUS_PORT),
            )
        except Exception as exc:  # noqa: BLE001
            if "already connected" not in str(exc).lower():
                raise RuntimeError(f"无法连接 Milvus: {exc}") from exc

        if kb_id is None:
            collection_name = settings.MILVUS_PROJECT_DICT_COLLECTION
            reset_global = True
        else:
            collection_name = _kb_collection_name(kb_id)
            reset_global = False

        def _drop_sync() -> None:
            if utility.has_collection(collection_name):
                utility.drop_collection(collection_name)
                logger.info("project_dict 集合已删除", collection=collection_name)

        await asyncio.to_thread(_drop_sync)

        if reset_global:
            ProjectDictStore._collection = None
            ProjectDictStore._connected = False
        else:
            if self._kb_collections is not None:
                self._kb_collections.pop(kb_id.hex, None)

    async def rebuild(
        self, items: list[dict], kb_id: uuid.UUID | None = None
    ) -> int:
        """全量重建基础表向量库（删后重建）。

        用于定时同步任务：删除旧集合 → 重新创建 → 批量插入新数据。
        分批插入避免单次插入过大。

        Args:
            items: 待插入的记录列表（结构同 ``upsert``，含 item_id）。
            kb_id: 知识库 ID。None 时重建全局 Collection（向后兼容），
                非 None 时重建该 KB 专属 Collection（KB 覆盖层）。

        Returns:
            int: 实际插入的记录数。
        """
        await self.delete_all(kb_id)

        if not items:
            logger.warning(
                "project_dict rebuild: items 为空，仅清理未插入",
                kb_id=str(kb_id) if kb_id else "global",
            )
            return 0

        batch_size = 500
        total_inserted = 0
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            inserted = await self.upsert(batch, kb_id=kb_id)
            total_inserted += inserted

        logger.info(
            "project_dict 全量重建完成",
            total_items=len(items),
            total_inserted=total_inserted,
            kb_id=str(kb_id) if kb_id else "global",
        )
        return total_inserted


# 模块级单例，懒加载
project_dict_store = ProjectDictStore()
