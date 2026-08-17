"""Prompt v2 验证：BaseExtract 严格模式 vs LangExtract(自研) 严格模式。

核心指标：字段拼接命中数（记录粒度约束是否生效）+ 原有质量指标。
文档：GJB3325A-2019（KB 25e7d8ef...）
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qa.functional.global_config_tuning import (
    KB,
    _deep_merge,
    compute_metrics,
    load_schema_fields,
)

DOC = "427fcb66-87f0-4e9b-904f-e8dbeaf4b2ab"
BASE = "http://127.0.0.1:8000/api/v1"
RESULTS_DIR = Path(__file__).resolve().parents[2] / "qa/evaluation/results/prompt_v2"

TARGET_FIELDS = ["材料牌号", "项目名称", "单位", "标准要求", "试验方法", "位置", "方向", "尺寸厚度",
                 "试样状态", "取样数量", "取样说明", "锻件类型", "温度", "试验温度",
                 "工艺名称", "工序名称", "保温温度", "保温时间", "介质温度", "项目大类"]
MERGE_RE = re.compile(r"[、,，;；/|]|\n|和|及|既|分别|或另")

RUNS = [
    {
        "name": "BE_strict_promptv2",
        "engine": "BaseExtract",
        "params": {
            "timeout": 600,
            "concurrency": {"max_concurrency": 4, "cross_category": 4, "within_category": 1},
        },
    },
    {
        "name": "LE_strict_promptv2",
        "engine": "LangExtract",
        "params": {
            "timeout": 600, "format_type": "JSON", "fence_output": False,
            "max_examples": 3, "passes": 2, "context_window_chars": 28000,
            "max_char_buffer": 40000,
            "concurrency": {"max_concurrency": 4, "cross_category": 4, "within_category": 1},
        },
    },
    {
        "name": "LEpkg_strict_promptv2",
        "engine": "LangExtractPkg",
        "params": {
            "timeout": 600, "format_type": "JSON", "fence_output": False,
            "max_examples": 3, "passes": 2, "context_window_chars": 28000,
            "max_char_buffer": 40000,
            "concurrency": {"max_concurrency": 4, "cross_category": 4, "within_category": 1},
        },
    },
]

RETRIEVAL = {
    "top_k": 10, "candidate_mult": 2, "weights": {"title": 0.2, "content": 0.8},
    "default_confidence_threshold": 0.035, "context_max_tokens": 28000,
    "category_recall": {"mode": "strict", "top_k": 5, "per_dim_top_k": 10},
    "hybrid": {"enabled": True, "rrf_k": 60.0, "dense_weight": 1.0, "keyword_weight": 1.2, "keyword_min_hits": 999},
    "reranker": {"enabled": False, "model": "", "top_n": 15},
}


def count_merged(result: dict) -> int:
    hits = 0
    for cat in result.get("categories") or []:
        for rec in cat.get("records") or []:
            for f in TARGET_FIELDS:
                v = rec.get(f)
                if isinstance(v, str) and v.strip() and MERGE_RE.search(v):
                    hits += 1
    return hits


async def login(client):
    r = await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


async def set_config(client, h, engine, params):
    content = {
        "retrieval": RETRIEVAL,
        "llm": {"engine": engine, "engines": {engine: _deep_merge(params, {})}},
        "kb_tool": {"script_timeout": 60},
    }
    r = await client.put(f"/kb/{KB}/extraction-config/global", headers=h,
                         json={"enabled": True, "content": content})
    r.raise_for_status()


async def run_extraction(client, h, name):
    r = await client.post(f"/kb/{KB}/extraction/{DOC}", headers=h)
    if r.status_code == 409:
        import asyncpg

        conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
        await conn.execute("UPDATE document_tasks SET status='failed' WHERE kb_id=$1 AND document_id=$2 AND type='document_extraction' AND status IN ('queued','running')", KB, DOC)
        await conn.execute("UPDATE extraction_results SET status='failed', progress=100 WHERE kb_id=$1 AND document_id=$2 AND status='running'", KB, DOC)
        await conn.close()
        await asyncio.sleep(2)
        r = await client.post(f"/kb/{KB}/extraction/{DOC}", headers=h)
    r.raise_for_status()
    last = None
    for _ in range(360):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/extraction/{DOC}/status", headers=h)
        d = r.json()["data"]
        err = d.get("error")
        if isinstance(err, dict):
            err = err.get("message")
        line = f"[{name}] {d.get('status')} {d.get('progress')}% {err or ''}"
        if line != last:
            print(line, flush=True)
            last = line
        if d.get("status") in ("completed", "failed") or d.get("task_status") == "failed":
            break
    r = await client.get(f"/kb/{KB}/extraction/{DOC}/result", headers=h)
    return r.json()["data"]


async def main():
    schema_fields = await load_schema_fields()
    results = {}
    async with httpx.AsyncClient(base_url=BASE, timeout=900) as client:
        token = await login(client)
        h = {"Authorization": f"Bearer {token}"}
        for run in RUNS:
            result_file = RESULTS_DIR / f"{run['name']}.json"
            if result_file.exists():
                print(f"[{run['name']}] 已存在结果，跳过", flush=True)
                continue
            await set_config(client, h, run["engine"], run["params"])
            print(f"\n===== RUN {run['name']} | engine={run['engine']} =====", flush=True)
            t0 = time.monotonic()
            res = await run_extraction(client, h, run["name"])
            dt = time.monotonic() - t0
            if res.get("status") != "completed":
                results[run["name"]] = {"status": "failed", "error": str(res.get("error"))[:300]}
                print("FAILED", results[run["name"]], flush=True)
                continue
            m = compute_metrics(res, schema_fields)
            m["merged_field_hits"] = count_merged(res)
            m["elapsed_sec"] = round(dt, 1)
            results[run["name"]] = m
            print("METRICS:", json.dumps(m, ensure_ascii=False), flush=True)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            (RESULTS_DIR / f"{run['name']}.json").write_text(
                json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (RESULTS_DIR / f"{run['name']}_metrics.json").write_text(
                json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    print("\nALL:", json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
