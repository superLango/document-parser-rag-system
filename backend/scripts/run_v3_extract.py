#!/usr/bin/env python3
"""仅运行 v3 抽取（跳过 OCR 和重建），使用已有 doc_id。

用法: python scripts/run_v3_extract.py [doc_id]
默认 doc_id: 0Httardy1pz5QJ1DolaupG (GH4169)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))
os.chdir(_BACKEND_DIR)

import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


async def main():
    doc_id = sys.argv[1] if len(sys.argv) > 1 else "0Httardy1pz5QJ1DolaupG"

    print("=" * 70)
    print(f"v3 抽取（doc_id={doc_id}）")
    print("=" * 70)

    from app.services.extraction.pipeline import extraction_pipeline

    t0 = time.time()
    result = await extraction_pipeline.run(task_id=doc_id, doc_id=doc_id)
    elapsed = time.time() - t0

    print(f"\n{'=' * 70}")
    print(f"抽取完成，总耗时: {elapsed:.1f}s")
    print(f"{'=' * 70}")

    # 输出摘要
    summary = result.summary
    print(f"\n总记录数: {summary.get('total_records', 0)}")
    print(f"总剔除数: {summary.get('total_rejected', 0)}")

    print(f"\n活跃 features ({len(summary.get('active_features', []))}):")
    for c in result.categories:
        rec_count = len(c.records)
        rej_count = len(c.rejected)
        if rec_count > 0 or rej_count > 0:
            print(f"  {c.feature}: records={rec_count}, rejected={rej_count}")

    # 保存结果（紧凑 JSON，与 result_writer 一致）
    output_path = Path(f"data/ocr_data/{doc_id}/extract_result.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n结果已保存: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
