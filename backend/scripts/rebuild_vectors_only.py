"""跳过 Popo，直接从已有 source.json 重建五维向量入库。

流程：
1. 删除损坏的 doc_five_dim Collection（断电后 load 卡住）
2. 加载 popo_output/source.json → PopoAdapter 适配 → 表格清洗 → 题注关联 → 父子块切分 → 五维向量化 → 入库

使用任务 ID ``0HrsR68jRANoFpQREXPxiv``（已有 source.json）。

运行::

    cd backend && python scripts/rebuild_vectors_only.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# 确保 backend 目录在 sys.path 中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from pymilvus import connections, utility

from app.core.config import settings
from app.services.vector.chunker import hierarchy_chunker
from app.services.vector.caption_linker import table_caption_linker
from app.services.vector.five_dim_embedder import five_dim_embedder
from app.services.vector.popo_adapter import PopoAdapter
from app.services.vector.table_cleaner import table_cleaner
from app.services.vector.vector_store import five_dim_vector_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rebuild_vectors")

TASK_ID = "0HrsR68jRANoFpQREXPxiv"
DOC_ID = TASK_ID


async def drop_collection() -> None:
    """删除损坏的 Collection。"""
    host = settings.MILVUS_HOST
    port = settings.MILVUS_PORT
    coll_name = settings.FIVE_DIM_VECTOR_COLLECTION

    connections.connect(alias="drop_conn", host=host, port=port)
    if utility.has_collection(coll_name, using="drop_conn"):
        utility.drop_collection(coll_name, using="drop_conn")
        logger.info("已删除旧 Collection: %s", coll_name)
    else:
        logger.info("Collection 不存在: %s", coll_name)
    connections.disconnect("drop_conn")


async def main() -> None:
    """主流程：从 source.json 直接入库。"""
    task_dir = Path(settings.OCR_OUTPUT_DIR) / TASK_ID
    source_json = task_dir / "popo_output" / "source.json"

    if not source_json.exists():
        raise FileNotFoundError(f"source.json 不存在: {source_json}")

    t_total = time.time()

    # 1. 删除损坏的 Collection
    logger.info("=" * 60)
    logger.info("步骤 1: 删除损坏的 Collection")
    logger.info("=" * 60)
    await drop_collection()

    # 2. 加载 source.json
    logger.info("=" * 60)
    logger.info("步骤 2: 加载 source.json")
    logger.info("=" * 60)
    with source_json.open("r", encoding="utf-8") as f:
        doc_blocks = json.load(f)
    logger.info("加载完成: %d 个 blocks", len(doc_blocks))

    # 3. PopoAdapter 适配转换
    logger.info("=" * 60)
    logger.info("步骤 3: PopoAdapter 适配转换")
    logger.info("=" * 60)
    t0 = time.time()
    elements = PopoAdapter.adapt(doc_blocks)
    logger.info("适配完成: %d 元素, %.2fs", len(elements), time.time() - t0)

    # 4. 表格清洗
    logger.info("=" * 60)
    logger.info("步骤 4: 表格清洗")
    logger.info("=" * 60)
    t1 = time.time()
    cleaned = 0
    for elem in elements:
        if elem.type == "table" and table_cleaner.is_table(elem.content):
            elem.content = table_cleaner.clean(elem.content)
            cleaned += 1
    logger.info("表格清洗: %d 张, %.2fs", cleaned, time.time() - t1)

    # 5. 题注关联
    logger.info("=" * 60)
    logger.info("步骤 5: 题注关联")
    logger.info("=" * 60)
    t2 = time.time()
    caption_count = table_caption_linker.link(elements)
    logger.info("题注关联: %d 个, %.2fs", caption_count, time.time() - t2)

    # 6. 父子块切分
    logger.info("=" * 60)
    logger.info("步骤 6: 父子块切分")
    logger.info("=" * 60)
    t3 = time.time()
    parent_chunks, child_chunks = hierarchy_chunker.chunk(elements, DOC_ID)
    logger.info(
        "切分完成: %d 父块, %d 子块, %.2fs",
        len(parent_chunks), len(child_chunks), time.time() - t3,
    )

    # 7. 五维向量编码 + 入库
    logger.info("=" * 60)
    logger.info("步骤 7: 五维向量编码 + 入库")
    logger.info("=" * 60)

    # 7.1 删除旧数据（Collection 已重建，此步安全）
    t4a = time.time()
    await five_dim_vector_store.delete_by_doc_id(DOC_ID)
    logger.info("  [7.1] 删除旧向量: %.2fs", time.time() - t4a)

    # 7.2 编码五维向量
    t4b = time.time()
    await five_dim_embedder.encode_batch(child_chunks)
    logger.info("  [7.2] 五维向量编码: %.2fs", time.time() - t4b)

    # 7.3 入库
    t4c = time.time()
    vector_count = await five_dim_vector_store.insert_chunks(child_chunks, DOC_ID)
    logger.info("  [7.3] Milvus 插入: %d 条, %.2fs", vector_count, time.time() - t4c)

    logger.info("=" * 60)
    logger.info("重建完成! 总耗时: %.2fs, 向量 %d 条", time.time() - t_total, vector_count)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
