"""v3 结构化抽取端到端测试脚本。

使用已有的五维向量数据，执行完整的 v3 抽取流程（Phase 2-4），
验证功能正确性并统计各阶段耗时。

使用方法：
    cd backend && python test_v3_extraction.py
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# 抑制 SQL 和调试日志
logging.disable(logging.INFO)

# 添加 backend 目录到 path
sys.path.insert(0, str(Path(__file__).parent))


async def main():
    """执行 v3 抽取端到端测试。"""
    from app.services.extraction.pipeline import extraction_pipeline

    # 使用已有的五维向量数据
    task_id = "0HrsR68jRANoFpQREXPxiv"
    doc_id = task_id

    print(f"=== v3 结构化抽取端到端测试 ===")
    print(f"task_id: {task_id}")
    print(f"doc_id:  {doc_id}")
    print()

    start = time.time()
    try:
        result = await extraction_pipeline.run(task_id=task_id, doc_id=doc_id)
    except Exception as err:
        print(f"❌ 抽取流程异常: {err}")
        import traceback
        traceback.print_exc()
        return

    elapsed = time.time() - start

    # 打印结果摘要
    print(f"=== 抽取结果摘要 ===")
    print(f"总耗时: {elapsed:.1f}s")
    print()

    # Timing
    print(f"=== 各阶段耗时 ===")
    for phase, t in result.timing.items():
        print(f"  {phase}: {t}s")
    print()

    # Doc info
    print(f"=== 标准基本信息 ===")
    for key, val in result.doc_info.items():
        print(f"  {key}: {val}")
    print()

    # Categories
    print(f"=== 类别抽取结果 ({len(result.categories)} 个类别) ===")
    for cat in result.categories:
        print(f"  [{cat.feature}] 记录数: {len(cat.records)}, 剔除: {len(cat.rejected)}")
        if cat.timing:
            print(f"    耗时: retrieval={cat.timing.get('retrieval', '?')}s, "
                  f"extraction={cat.timing.get('extraction', '?')}s, "
                  f"total={cat.timing.get('total', '?')}s")
        # 打印前3条记录
        for i, record in enumerate(cat.records[:3]):
            brand = record.get("材料牌号", "")
            item = record.get("项目名称", "")
            req = record.get("标准要求", "")[:50]
            print(f"    [{i+1}] 牌号={brand}, 项目={item}, 要求={req}")
        if len(cat.records) > 3:
            print(f"    ... 还有 {len(cat.records) - 3} 条记录")
    print()

    # Heat treatment
    print(f"=== 热处理制度 ({len(result.heat_treatment.records)} 条) ===")
    for i, record in enumerate(result.heat_treatment.records[:3]):
        brand = record.get("材料牌号", "")
        process = record.get("工艺名称", "")
        print(f"  [{i+1}] 牌号={brand}, 工艺={process}")
    print()

    # Summary
    print(f"=== 汇总 ===")
    print(f"  总记录数: {result.summary.get('total_records', 0)}")
    print(f"  总剔除数: {result.summary.get('total_rejected', 0)}")
    print(f"  活跃类别: {result.summary.get('active_features', [])}")

    # Check result file
    result_path = Path(f"data/ocr_data/{task_id}/extract_result.json")
    if result_path.exists():
        print(f"\n✅ 结果文件已保存: {result_path}")
        print(f"   文件大小: {result_path.stat().st_size} bytes")
    else:
        print(f"\n❌ 结果文件未找到: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
