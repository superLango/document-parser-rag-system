"""合并脚本：重新入库 + 立即执行 v3 抽取测试。

解决 Milvus load 卡住问题：
- rebuild_vectors_only.py 入库时 load 成功（新创建 Collection）
- 但测试脚本重新 load 时卡住
- 合并方案：在同一个进程中先入库（load 成功），再立即抽取（Collection 已 loaded）

运行::

    cd backend && python scripts/rebuild_and_extract.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from pymilvus import connections, utility

from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# 抑制 pymilvus 弃用警告
logging.getLogger("pymilvus").setLevel(logging.WARNING)

logger = logging.getLogger("rebuild_and_extract")

TASK_ID = "0HrsR68jRANoFpQREXPxiv"
DOC_ID = TASK_ID


async def rebuild_vectors() -> int:
    """重建五维向量入库，返回入库条数。"""
    from app.services.vector.chunker import hierarchy_chunker
    from app.services.vector.caption_linker import table_caption_linker
    from app.services.vector.five_dim_embedder import five_dim_embedder
    from app.services.vector.popo_adapter import PopoAdapter
    from app.services.vector.table_cleaner import table_cleaner
    from app.services.vector.vector_store import five_dim_vector_store

    task_dir = Path(settings.OCR_OUTPUT_DIR) / TASK_ID
    source_json = task_dir / "popo_output" / "source.json"

    # 1. 删除旧 Collection
    host = settings.MILVUS_HOST
    port = settings.MILVUS_PORT
    coll_name = settings.FIVE_DIM_VECTOR_COLLECTION
    connections.connect(alias="drop_conn", host=host, port=port)
    if utility.has_collection(coll_name, using="drop_conn"):
        utility.drop_collection(coll_name, using="drop_conn")
        logger.info("已删除旧 Collection: %s", coll_name)
    connections.disconnect("drop_conn")

    # 2. 加载 source.json
    with source_json.open("r", encoding="utf-8") as f:
        doc_blocks = json.load(f)
    logger.info("加载 source.json: %d blocks", len(doc_blocks))

    # 3. 适配 + 清洗 + 题注 + 切分
    elements = PopoAdapter.adapt(doc_blocks)
    for elem in elements:
        if elem.type == "table" and table_cleaner.is_table(elem.content):
            elem.content = table_cleaner.clean(elem.content)
    table_caption_linker.link(elements)
    parent_chunks, child_chunks = hierarchy_chunker.chunk(elements, DOC_ID)
    logger.info("切分: %d 父块, %d 子块", len(parent_chunks), len(child_chunks))

    # 4. 五维向量编码 + 入库
    await five_dim_vector_store.delete_by_doc_id(DOC_ID)
    await five_dim_embedder.encode_batch(child_chunks)
    vector_count = await five_dim_vector_store.insert_chunks(child_chunks, DOC_ID)
    logger.info("入库完成: %d 条向量", vector_count)

    # 关键：不释放 Collection，保持 loaded 状态供抽取使用
    return vector_count


async def run_extraction() -> None:
    """执行 v3 抽取测试。"""
    from app.services.extraction.pipeline import extraction_pipeline

    logger.info("=" * 60)
    logger.info("开始 v3 抽取测试")
    logger.info("=" * 60)

    start = time.time()
    result = await extraction_pipeline.run(task_id=TASK_ID, doc_id=DOC_ID)
    elapsed = time.time() - start

    logger.info("=" * 60)
    logger.info("v3 抽取测试完成! 总耗时: %.1fs", elapsed)
    logger.info("=" * 60)

    # 打印结果摘要
    print(f"\n{'='*60}")
    print(f"v3 抽取结果摘要")
    print(f"{'='*60}")
    print(f"总耗时: {elapsed:.1f}s")
    print(f"timing: {result.timing}")

    if result.doc_info:
        print(f"\n标准基本信息: {result.doc_info}")

    total_records = 0
    cats = result.categories
    if isinstance(cats, dict):
        for cat_name, cat_data in cats.items():
            records = cat_data.get("records", []) if isinstance(cat_data, dict) else []
            status = "✅" if records else "❌"
            print(f"  {status} {cat_name}: {len(records)} 条")
            total_records += len(records)
    elif isinstance(cats, list):
        for cat_data in cats:
            if isinstance(cat_data, dict):
                cat_name = cat_data.get("feature", cat_data.get("name", "?"))
                records = cat_data.get("records", [])
                status = "✅" if records else "❌"
                print(f"  {status} {cat_name}: {len(records)} 条")
                total_records += len(records)

    print(f"\n总记录数: {total_records}")

    if result.heat_treatment:
        ht_records = result.heat_treatment.get("records", []) if isinstance(result.heat_treatment, dict) else []
        print(f"热处理制度: {len(ht_records)} 条")
    else:
        print("热处理制度: 0 条")

    print(f"\n结果文件: {Path(settings.OCR_OUTPUT_DIR) / TASK_ID / 'extraction_v3.json'}")


async def main() -> None:
    """主流程：先入库再抽取。"""
    t_total = time.time()

    # Phase 0: 重建向量入库
    logger.info("=" * 60)
    logger.info("Phase 0: 重建五维向量入库")
    logger.info("=" * 60)
    vector_count = await rebuild_vectors()
    logger.info("向量入库完成: %d 条, 耗时 %.1fs", vector_count, time.time() - t_total)

    # Phase 1-4: v3 抽取
    await run_extraction()

    logger.info("全流程完成! 总耗时: %.1fs", time.time() - t_total)


if __name__ == "__main__":
    asyncio.run(main())
