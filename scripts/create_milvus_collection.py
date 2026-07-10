#!/usr/bin/env python
"""Milvus Collection 初始化脚本

按方案 8.3 节创建 doc_chunks Collection：
- dense_vector: FLOAT_VECTOR(1024) + IVF_PQ 索引（nlist=1024, m=16）
- sparse_vector: SPARSE_FLOAT_VECTOR + SPARSE_INVERTED_INDEX 索引
- 混合检索支持 RRF 融合

运行方式：
    python scripts/create_milvus_collection.py

注意：
    执行前请确保 Milvus 2.4.x（含 GPU 支持）服务已启动，
    并在 backend/.env 中正确配置 MILVUS_HOST / MILVUS_PORT。
"""

import sys
import os

# 将 backend 目录加入 sys.path，以便导入 app.core 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Collection 名称统一从配置读取，保证与业务代码一致
COLLECTION_NAME = settings.MILVUS_COLLECTION


def _build_schema() -> CollectionSchema:
    """构建 doc_chunks 的 Collection Schema。

    字段说明：
        - id            主键，INT64 自增
        - chunk_id      分块唯一标识（业务侧生成）
        - text          分块原文，用于检索结果展示
        - dense_vector  稠密向量（BGE-M3 默认 1024 维）
        - sparse_vector 稀疏向量（BGE-M3 稀疏编码，用于词项级匹配）
        - doc_id        所属文档 ID，便于过滤
        - title_chain   文档标题层级链（如 "卷 > 章 > 节"）
        - metadata      扩展元信息（页码、坐标等），JSON 类型

    Returns:
        CollectionSchema: 已定义全部字段的 schema。
    """
    return CollectionSchema(
        fields=[
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=1024),
            FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="title_chain", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="metadata", dtype=DataType.JSON),
        ],
        description="文档分块向量库 - Dense+Sparse 混合检索",
    )


def _create_dense_index(collection: Collection) -> None:
    """为 dense_vector 创建 IVF_PQ 索引。

    采用 IVF_PQ 以在显存占用与召回率间取得平衡：
        - nlist=1024: 聚类中心数
        - m=16: PQ 子量化器数（1024 / 16 = 64 维/段）
        - metric_type=IP: 内积，配合归一化后的向量等价于余弦相似度
    """
    collection.create_index(
        field_name="dense_vector",
        index_params={
            "index_type": "IVF_PQ",
            "metric_type": "IP",
            "params": {"nlist": 1024, "m": 16},
        },
    )
    logger.info("dense_vector 索引创建完成: IVF_PQ, nlist=1024, m=16, metric=IP")


def _create_sparse_index(collection: Collection) -> None:
    """为 sparse_vector 创建 SPARSE_INVERTED_INDEX 索引。

    稀疏倒排索引适合 BGE-M3 输出的稀疏编码，可在保留词项权重的同时
    提供亚线性检索复杂度；metric_type=IP 用于对齐稠密侧度量。
    """
    collection.create_index(
        field_name="sparse_vector",
        index_params={
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "IP",
        },
    )
    logger.info("sparse_vector 索引创建完成: SPARSE_INVERTED_INDEX, metric=IP")


def init_collection() -> Collection:
    """创建并加载 doc_chunks Collection。

    流程：
        1. 连接 Milvus（连接失败时抛出明确异常并退出）
        2. 若 Collection 已存在则删除重建（幂等）
        3. 创建 Schema 与索引
        4. load 到内存以支持检索

    Returns:
        Collection: 已创建并加载完成的 Collection 对象。

    Raises:
        RuntimeError: Milvus 连接失败时抛出。
    """
    # 1. 连接 Milvus
    try:
        connections.connect(
            alias="default",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
        )
    except Exception as exc:  # noqa: BLE001 - 顶层脚本需统一捕获连接类异常
        logger.error(
            "连接 Milvus 失败，请确认服务已启动",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            error=str(exc),
        )
        raise RuntimeError(f"无法连接 Milvus({settings.MILVUS_HOST}:{settings.MILVUS_PORT}): {exc}") from exc

    logger.info(
        "已连接 Milvus",
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
    )

    # 2. 幂等处理：已存在则删除重建
    if utility.has_collection(COLLECTION_NAME):
        logger.warning("Collection 已存在，将删除并重建", collection=COLLECTION_NAME)
        utility.drop_collection(COLLECTION_NAME)

    # 3. 创建 Collection
    schema = _build_schema()
    collection = Collection(name=COLLECTION_NAME, schema=schema)
    logger.info("Collection 创建成功", collection=COLLECTION_NAME)

    # 4. 创建索引
    _create_dense_index(collection)
    _create_sparse_index(collection)

    # 5. 加载到内存
    collection.load()
    logger.info(
        "Collection 已加载到内存",
        collection=COLLECTION_NAME,
        num_entities=collection.num_entities,
    )

    return collection


def _print_summary() -> None:
    """打印 Collection 初始化结果摘要。"""
    print(f"\n✅ Collection '{COLLECTION_NAME}' 初始化完成")
    print("   字段: id, chunk_id, text, dense_vector(1024), sparse_vector, doc_id, title_chain, metadata")
    print("   索引: IVF_PQ(dense, nlist=1024, m=16) + SPARSE_INVERTED_INDEX(sparse)")
    print(f"   度量: IP（内积，适用于归一化后的稠密向量）")


if __name__ == "__main__":
    try:
        init_collection()
        _print_summary()
    except RuntimeError as err:
        # init_collection 中已记录日志，这里仅给出可读提示并退出
        print(f"\n❌ 初始化失败: {err}", file=sys.stderr)
        sys.exit(1)
