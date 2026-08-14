"""抽取引擎对比：BaseExtract vs LangExtract（同一文档、同一检索配置）。"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qa.functional.global_config_tuning import (
    KB,
    REPORT,
    _deep_merge,
    compute_metrics,
    load_schema_fields,
)

DOC = "427fcb66-87f0-4e9b-904f-e8dbeaf4b2ab"  # GJB3325A-2019
BASE = "http://127.0.0.1:8000/api/v1"
RESULTS_DIR = Path(__file__).resolve().parents[2] / "qa/evaluation/results"

ENGINES = [
    {
        "name": "BE_default",
        "engine": "BaseExtract",
        "desc": "BaseExtract 默认（temp0/top_p0.1/top_k20，批 8k/6k）",
        "params": {},
    },
    {
        "name": "BE_batch",
        "engine": "BaseExtract",
        "desc": "BaseExtract 小批（单阈值4k/批3k/重叠300/截断16k）",
        "params": {
            "batch": {"single_threshold": 4000, "batch_chars": 3000, "overlap": 300, "context_truncate": 16000},
        },
    },
    {
        "name": "LE_default",
        "engine": "LangExtract",
        "desc": "LangExtract 默认（passes2/示例3/窗口28k）",
        "params": {
            "format_type": "JSON", "fence_output": False, "max_examples": 3,
            "passes": 2, "context_window_chars": 28000, "max_char_buffer": 40000,
        },
    },
    {
        "name": "LE_strong",
        "engine": "LangExtract",
        "desc": "LangExtract 强约束（passes3/示例5/围栏/窗口16k/类内并发2）",
        "params": {
            "format_type": "JSON", "fence_output": True, "max_examples": 5,
            "passes": 3, "context_window_chars": 16000, "max_char_buffer": 20000,
            "concurrency": {"max_concurrency": 4, "cross_category": 4, "within_category": 2},
        },
    },
]


LLM_COMMON = {
    "temperature": 0.0, "top_p": 0.1, "top_k": 20, "max_tokens": 32768,
    "timeout": 600, "enable_thinking": False,
    "concurrency": {"max_concurrency": 8, "cross_category": 8, "within_category": 1},
    "batch": {"single_threshold": 8000, "batch_chars": 6000, "overlap": 500, "context_truncate": 32000},
}


async def login(client):
    r = await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


async def set_engine(client, h, engine: str, params: dict):
    r = await client.get(f"/kb/{KB}/extraction-config/global", headers=h)
    r.raise_for_status()
    content = r.json()["data"]["content"]
    engines = {
        "BaseExtract": _deep_merge(LLM_COMMON, content.get("llm", {}).get("engines", {}).get("BaseExtract") or {}),
        "LangExtract": _deep_merge(LLM_COMMON, content.get("llm", {}).get("engines", {}).get("LangExtract") or {}),
    }
    engines["LangExtract"].update({
        "format_type": "JSON", "fence_output": False, "max_examples": 3,
        "passes": 2, "context_window_chars": 28000, "max_char_buffer": 40000,
    })
    engines[engine] = _deep_merge(engines[engine], params)
    payload = {
        "enabled": True,
        "content": {**content, "llm": {"engine": engine, "engines": engines}},
    }
    r = await client.put(f"/kb/{KB}/extraction-config/global", headers=h, json=payload)
    r.raise_for_status()


async def run_extraction(client, h, name):
    r = await client.post(f"/kb/{KB}/extraction/{DOC}", headers=h)
    if r.status_code == 409:
        await asyncio.sleep(3)
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
        for eng in ENGINES:
            await set_engine(client, h, eng["engine"], eng["params"])
            print(f"\n===== ENGINE {eng['name']} | {eng['desc']} =====", flush=True)
            t0 = time.monotonic()
            res = await run_extraction(client, h, eng["name"])
            dt = time.monotonic() - t0
            if res.get("status") != "completed":
                results[eng["name"]] = {"status": "failed", "error": str(res.get("error"))[:300]}
                print("FAILED", results[eng["name"]], flush=True)
                continue
            m = compute_metrics(res, schema_fields)
            m["elapsed_sec"] = round(dt, 1)
            results[eng["name"]] = m
            print("METRICS:", json.dumps(m, ensure_ascii=False), flush=True)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            (RESULTS_DIR / f"engine_{eng['name']}.json").write_text(
                json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = REPORT.read_text(encoding="utf-8")
    report += "\n\n## 抽取引擎对比（BaseExtract vs LangExtract，GJB3325A-2019）\n\n"
    report += "| 引擎 | 状态 | 记录数 | 剔除 | 字段填充率 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |\n"
    report += "|---|---|---|---|---|---|---|---|---|---|\n"
    for eng in ENGINES:
        r = results.get(eng["name"]) or {}
        if r.get("status") == "failed":
            report += f"| {eng['name']} | FAIL | - | - | - | - | - | - | - | - |\n"
        else:
            report += f"| {eng['name']} | OK | {r.get('records')} | {r.get('rejected')} | {r.get('fill_rate')} | {r.get('complete_rate')} | {r.get('usable_rate')} | {r.get('script_rate')} | **{r.get('score')}** | {r.get('elapsed_sec')} |\n"
    report += "\n> 说明：当前两个引擎共用 llm_extractor.extract_category 同一实现，LangExtract 专属参数（passes/max_examples/fence_output/format_type/context_window_chars/max_char_buffer）未被消费，差异仅来自 LLM 输出随机性与并发参数。\n"
    REPORT.write_text(report, encoding="utf-8")
    print("\n对比报告已追加：", REPORT)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
