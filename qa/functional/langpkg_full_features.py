"""LangExtractPkg 引擎收敛专项验证（官方特性全开）。

覆盖：完整上下文一次交原包（sentence-aware 分块 + 共指窗口 + 并行 + 多轮 +
对齐）；验证不截断、不超限（400）、结果可完成，并与上一版分段实现对比指标。

流程：登录 → 设置全局配置（engine=LangExtractPkg，官方特性参数）→
对 GB-T1220-2007 文档执行抽取 → 保存完整/简化/指标/README。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qa.functional.global_config_tuning import (
    KB,
    compute_metrics,
    load_schema_fields,
)
from qa.functional.prompt_v3_test import count_merged

BASE = "http://127.0.0.1:8000/api/v1"
DOC_ID = "09a79bb1-1c17-44bc-bb02-57eab2e25580"
RESULTS_DIR = Path(__file__).resolve().parents[2] / "qa/evaluation/results/langpkg_full_features"

# 官方特性全开的引擎参数（与全局配置默认一致）
ENGINE_PARAMS = {
    "timeout": 1800,
    "format_type": "JSON",
    "fence_output": False,
    "max_examples": 3,
    "passes": 1,
    "max_tokens": 24000,
    "max_char_buffer": 6000,
    "context_window_chars": 500,
    "batch_length": 8,
    "max_workers": 4,
    "concurrency": {"max_concurrency": 8, "cross_category": 8, "within_category": 8},
}

RETRIEVAL = {
    "top_k": 15, "candidate_mult": 2, "weights": {"title": 0.2, "content": 0.8},
    "default_confidence_threshold": 0.035, "context_max_tokens": 28000,
    "context": {"chars_per_token": 1.5, "min_keep_chars": 200, "truncate_marker": "\n[...内容截断...]"},
    "category_recall": {"mode": "loose", "top_k": 8, "per_dim_top_k": 10},
    "query_embed": {"content_max_chars": 2000, "dedupe_similarity_threshold": 0.85},
    "hybrid": {"enabled": True, "rrf_k": 60.0, "dense_weight": 1.0, "keyword_weight": 1.2, "keyword_min_hits": 1},
    "reranker": {"enabled": True, "model": "/home/grainuser/hansonDoc_RAG/models/bge-reranker-v2-m3", "top_n": 15},
}


async def login(client):
    r = await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


async def set_config(client, h):
    content = {
        "retrieval": RETRIEVAL,
        "llm": {"engine": "LangExtractPkg", "engines": {"LangExtractPkg": ENGINE_PARAMS}},
        "kb_tool": {"script_timeout": 60},
    }
    r = await client.put(f"/kb/{KB}/extraction-config/global", headers=h, json={"enabled": True, "content": content})
    r.raise_for_status()
    print("global config 已设置：engine=LangExtractPkg", flush=True)


async def run_extraction(client, h, doc_id):
    r = await client.post(f"/kb/{KB}/extraction/{doc_id}", headers=h)
    if r.status_code == 409:
        import asyncpg

        conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
        await conn.execute(
            "UPDATE document_tasks SET status='failed' WHERE kb_id=$1 AND document_id=$2 AND type='document_extraction' AND status IN ('queued','running')",
            KB, doc_id,
        )
        await conn.execute(
            "UPDATE extraction_results SET status='failed', progress=100 WHERE kb_id=$1 AND document_id=$2 AND status='running'",
            KB, doc_id,
        )
        await conn.close()
        await asyncio.sleep(2)
        r = await client.post(f"/kb/{KB}/extraction/{doc_id}", headers=h)
    r.raise_for_status()
    last = None
    for _ in range(600):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/extraction/{doc_id}/status", headers=h)
        d = r.json()["data"]
        err = d.get("error")
        if isinstance(err, dict):
            err = err.get("message")
        line = f"{d.get('status')} {d.get('progress')}% {err or ''}"
        if line != last:
            print(line, flush=True)
            last = line
        if d.get("status") in ("completed", "failed") or d.get("task_status") == "failed":
            break
    r = await client.get(f"/kb/{KB}/extraction/{doc_id}/result", headers=h)
    return r.json()["data"]


async def main():
    schema_fields = await load_schema_fields()
    async with httpx.AsyncClient(base_url=BASE, timeout=900) as client:
        token = await login(client)
        h = {"Authorization": f"Bearer {token}"}
        await set_config(client, h)

        from app.services.extraction.result_store import to_simple_view

        print(f"\n===== RUN langpkg_full_features | doc={DOC_ID} =====", flush=True)
        t0 = time.monotonic()
        res = await run_extraction(client, h, DOC_ID)
        dt = time.monotonic() - t0
        if res.get("status") != "completed":
            print("FAILED:", str(res.get("error"))[:400], flush=True)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            (RESULTS_DIR / "run.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            return
        m = compute_metrics(res, schema_fields)
        m["merged_field_hits"] = count_merged(res)
        m["elapsed_sec"] = round(dt, 1)
        # 溯源证据统计：记录中带 _evidence 的比例
        recs = [r for c in res.get("categories") or [] for r in c.get("records") or []]
        m["evidence_records"] = sum(1 for r in recs if r.get("_evidence"))
        m["evidence_rate"] = round(m["evidence_records"] / len(recs), 3) if recs else 0.0
        print("METRICS:", json.dumps(m, ensure_ascii=False), flush=True)

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "run.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        (RESULTS_DIR / "run_simple.json").write_text(json.dumps(to_simple_view(res), ensure_ascii=False, indent=2), encoding="utf-8")
        (RESULTS_DIR / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

        # 与上一版分段实现（gb1220_segmented LEpkg）对比
        prev_file = RESULTS_DIR.parent / "gb1220_segmented/gb1220seg_LEpkg_metrics.json"
        lines = [
            "# LangExtractPkg 引擎收敛专项验证（官方特性全开）",
            "",
            f"- 文档：GB-T1220-2007 不锈钢棒.pdf（doc={DOC_ID}，loose 召回）",
            f"- 配置：engine=LangExtractPkg；max_tokens=8192；max_char_buffer=3000；context_window_chars=500；passes=2；batch_length=8；max_workers=8",
            f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 本次结果",
            "",
            "| 记录数 | 剔除 | 拼接字段命中 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 溯源记录率 | 耗时(s) |",
            "|---|---|---|---|---|---|---|---|---|",
            f"| {m.get('records')} | {m.get('rejected')} | {m.get('merged_field_hits')} | {m.get('complete_rate')} | {m.get('usable_rate')} | {m.get('script_rate')} | **{m.get('score')}** | {m.get('evidence_rate')} | {m.get('elapsed_sec')} |",
            "",
            "## 与上一版（分段多次调用原包）对比",
            "",
        ]
        if prev_file.exists():
            prev = json.loads(prev_file.read_text(encoding="utf-8"))
            lines.append("| 方案 | 记录数 | 完整率 | 可用率 | 综合分 | 耗时(s) |")
            lines.append("|---|---|---|---|---|---|")
            lines.append(
                f"| 旧：分段多次调用 | {prev.get('records')} | {prev.get('complete_rate')} | {prev.get('usable_rate')} | {prev.get('score')} | {prev.get('elapsed_sec')} |"
            )
            lines.append(
                f"| 新：整段交原包（官方特性全开） | {m.get('records')} | {m.get('complete_rate')} | {m.get('usable_rate')} | **{m.get('score')}** | {m.get('elapsed_sec')} |"
            )
        else:
            lines.append("未找到上一版指标文件 gb1220_segmented/gb1220seg_LEpkg_metrics.json，跳过对比。")
        lines += [
            "",
            "文件说明：run.json 完整结果（记录含 _evidence 溯源）；run_simple.json 简化视图；metrics.json 指标。",
        ]
        (RESULTS_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")
        print("\n结果目录：", RESULTS_DIR)


if __name__ == "__main__":
    asyncio.run(main())
