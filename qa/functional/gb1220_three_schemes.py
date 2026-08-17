"""GB-T1220-2007 三抽取方案对照：BaseExtract / LangExtract / LangExtractPkg（严格模式）。

流程：上传 → 解析 → 索引 → 三套抽取；结果保存完整/简化/指标三份。
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
PDF = Path(__file__).resolve().parents[2] / "test_doc" / "GB-T1220-2007 不锈钢棒.pdf"
RESULTS_DIR = Path(__file__).resolve().parents[2] / "qa/evaluation/results/gb1220_promptv3"

RUNS = [
    {
        "name": "gb1220_BE_strict",
        "engine": "BaseExtract",
        "params": {"timeout": 600, "concurrency": {"max_concurrency": 4, "cross_category": 4, "within_category": 1}},
    },
    {
        "name": "gb1220_LE_strict",
        "engine": "LangExtract",
        "params": {
            "timeout": 600, "format_type": "JSON", "fence_output": False, "max_examples": 3,
            "passes": 2, "context_window_chars": 28000, "max_char_buffer": 40000,
            "concurrency": {"max_concurrency": 4, "cross_category": 4, "within_category": 1},
        },
    },
    {
        "name": "gb1220_LEpkg_strict",
        "engine": "LangExtractPkg",
        "params": {
            "timeout": 600, "format_type": "JSON", "fence_output": False, "max_examples": 3,
            "passes": 2, "context_window_chars": 28000, "max_char_buffer": 40000,
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


async def login(client):
    r = await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


async def upload_and_parse(client, h):
    r = await client.post(f"/kb/{KB}/documents", headers=h,
                          files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")})
    r.raise_for_status()
    doc_id = r.json()["data"]["document"]["id"]
    r = await client.post(f"/kb/{KB}/documents/{doc_id}/start", headers=h)
    r.raise_for_status()
    last = None
    for _ in range(600):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/documents/{doc_id}", headers=h)
        d = r.json()["data"]
        line = f"parse {d.get('process_status')} {d.get('progress_page')}/{d.get('progress_total')}"
        if line != last:
            print(line, flush=True)
            last = line
        if d.get("process_status") in ("completed", "failed") or d.get("status") in ("completed", "failed"):
            break
    assert d.get("process_status") == "completed", f"解析未完成: {d}"
    return doc_id


async def wait_index(client, h, doc_id):
    last = None
    for _ in range(360):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/index/tasks?page=1&page_size=10", headers=h)
        items = r.json()["data"]["items"]
        mine = [i for i in items if i.get("document_id") == doc_id]
        if not mine:
            continue
        it = mine[0]
        line = f"index {it.get('status')} {json.dumps(it.get('checkpoint'), ensure_ascii=False)[:80]}"
        if line != last:
            print(line, flush=True)
            last = line
        if it.get("status") in ("completed", "failed"):
            break
    assert it.get("status") == "completed", f"索引未完成: {it}"


async def set_config(client, h, engine, params):
    content = {"retrieval": RETRIEVAL, "llm": {"engine": engine, "engines": {engine: params}}, "kb_tool": {"script_timeout": 60}}
    r = await client.put(f"/kb/{KB}/extraction-config/global", headers=h, json={"enabled": True, "content": content})
    r.raise_for_status()


async def run_extraction(client, h, doc_id, name):
    r = await client.post(f"/kb/{KB}/extraction/{doc_id}", headers=h)
    if r.status_code == 409:
        import asyncpg

        conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
        await conn.execute("UPDATE document_tasks SET status='failed' WHERE kb_id=$1 AND document_id=$2 AND type='document_extraction' AND status IN ('queued','running')", KB, doc_id)
        await conn.execute("UPDATE extraction_results SET status='failed', progress=100 WHERE kb_id=$1 AND document_id=$2 AND status='running'", KB, doc_id)
        await conn.close()
        await asyncio.sleep(2)
        r = await client.post(f"/kb/{KB}/extraction/{doc_id}", headers=h)
    r.raise_for_status()
    last = None
    for _ in range(360):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/extraction/{doc_id}/status", headers=h)
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
    r = await client.get(f"/kb/{KB}/extraction/{doc_id}/result", headers=h)
    return r.json()["data"]


async def main():
    schema_fields = await load_schema_fields()
    async with httpx.AsyncClient(base_url=BASE, timeout=900) as client:
        token = await login(client)
        h = {"Authorization": f"Bearer {token}"}
        doc_id = await upload_and_parse(client, h)
        print("doc_id:", doc_id, flush=True)
        await wait_index(client, h, doc_id)

        from app.services.extraction.result_store import to_simple_view

        results = {}
        for run in RUNS:
            await set_config(client, h, run["engine"], run["params"])
            print(f"\n===== RUN {run['name']} | engine={run['engine']} =====", flush=True)
            t0 = time.monotonic()
            res = await run_extraction(client, h, doc_id, run["name"])
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
            (RESULTS_DIR / f"{run['name']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            (RESULTS_DIR / f"{run['name']}_simple.json").write_text(json.dumps(to_simple_view(res), ensure_ascii=False, indent=2), encoding="utf-8")
            (RESULTS_DIR / f"{run['name']}_metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

    # 汇总 README
    lines = ["# GB-T1220-2007 三抽取方案对照（严格模式，Prompt v3 / few-shot v3）", "", f"- 文档：{PDF.name}（doc={doc_id}）", f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    lines.append("| 方案 | 状态 | 记录数 | 剔除 | 拼接字段命中 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for run in RUNS:
        r = results.get(run["name"]) or {}
        if r.get("status") == "failed":
            lines.append(f"| {run['name']} | FAIL | - | - | - | - | - | - | - | - |")
        else:
            lines.append(f"| {run['name']} | OK | {r.get('records')} | {r.get('rejected')} | {r.get('merged_field_hits')} | {r.get('complete_rate')} | {r.get('usable_rate')} | {r.get('script_rate')} | **{r.get('score')}** | {r.get('elapsed_sec')} |")
    lines.append("")
    lines.append("文件说明：{方案}.json 完整结果；{方案}_simple.json 简化视图（categories 仅 feature+result）；{方案}_metrics.json 指标。")
    (RESULTS_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\nALL:", json.dumps(results, ensure_ascii=False, indent=2))
    print("结果目录：", RESULTS_DIR)


if __name__ == "__main__":
    asyncio.run(main())
