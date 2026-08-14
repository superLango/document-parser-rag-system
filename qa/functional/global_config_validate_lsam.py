"""全局配置调优验证：在 LSAM-JD01-0016 上对比 BASE 与 STRICT 最优候选。"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qa.functional.global_config_tuning import (
    BASE_LLM,
    BASE_RETRIEVAL,
    KB,
    REPORT,
    _deep_merge,
    compute_metrics,
    load_schema_fields,
)

DOC_LSAM = "92f5b301-b65d-4415-a925-94f3d29c704a"
BASE = "http://127.0.0.1:8000/api/v1"
RESULTS_DIR = Path(__file__).resolve().parents[2] / "qa/evaluation/results/validation"

CONFIGS = [
    {
        "name": "LSAM_BASE",
        "desc": "默认（top_k=10, ctx=28k, 混合默认, loose）",
        "retrieval": {},
    },
    {
        "name": "LSAM_STRICT",
        "desc": "严格召回（阈值0.035，无词法兜底）",
        "retrieval": {
            "default_confidence_threshold": 0.035,
            "category_recall": {"mode": "strict", "top_k": 5, "per_dim_top_k": 10},
            "hybrid": {"keyword_min_hits": 999},
        },
    },
]


async def login(client):
    r = await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


async def set_config(client, h, retrieval):
    content = {"retrieval": _deep_merge(BASE_RETRIEVAL, retrieval), "llm": BASE_LLM, "kb_tool": {"script_timeout": 60}}
    r = await client.put(f"/kb/{KB}/extraction-config/global", headers=h, json={"enabled": True, "content": content})
    r.raise_for_status()


async def run_extraction(client, h, name):
    r = await client.post(f"/kb/{KB}/extraction/{DOC_LSAM}", headers=h)
    if r.status_code == 409:
        await asyncio.sleep(3)
        r = await client.post(f"/kb/{KB}/extraction/{DOC_LSAM}", headers=h)
    r.raise_for_status()
    last = None
    for _ in range(360):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/extraction/{DOC_LSAM}/status", headers=h)
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
    r = await client.get(f"/kb/{KB}/extraction/{DOC_LSAM}/result", headers=h)
    return r.json()["data"]


async def main():
    schema_fields = await load_schema_fields()
    results = {}
    async with httpx.AsyncClient(base_url=BASE, timeout=900) as client:
        token = await login(client)
        h = {"Authorization": f"Bearer {token}"}
        for cfg in CONFIGS:
            await set_config(client, h, cfg["retrieval"])
            print(f"\n===== RUN {cfg['name']} =====", flush=True)
            t0 = time.monotonic()
            res = await run_extraction(client, h, cfg["name"])
            dt = time.monotonic() - t0
            if res.get("status") != "completed":
                results[cfg["name"]] = {"status": "failed", "error": str(res.get("error"))[:200]}
                print("FAILED", results[cfg["name"]], flush=True)
                continue
            m = compute_metrics(res, schema_fields)
            m["elapsed_sec"] = round(dt, 1)
            results[cfg["name"]] = m
            print("METRICS:", json.dumps(m, ensure_ascii=False), flush=True)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            (RESULTS_DIR / f"lsam_{cfg['name']}.json").write_text(
                json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (RESULTS_DIR / f"lsam_{cfg['name']}_metrics.json").write_text(
                json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        await set_config(client, h, {})  # 恢复默认

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = REPORT.read_text(encoding="utf-8")
    report += "\n\n## LSAM-JD01-0016 验证（BASE vs STRICT）\n\n"
    report += "| 配置 | 状态 | 保留类别 | 记录数 | 剔除 | 字段填充率 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |\n"
    report += "|---|---|---|---|---|---|---|---|---|---|---|\n"
    for cfg in CONFIGS:
        r = results.get(cfg["name"]) or {}
        if r.get("status") == "failed":
            report += f"| {cfg['name']} | FAIL | - | - | - | - | - | - | - | - | - |\n"
        else:
            report += f"| {cfg['name']} | OK | {r.get('kept')} | {r.get('records')} | {r.get('rejected')} | {r.get('fill_rate')} | {r.get('complete_rate')} | {r.get('usable_rate')} | {r.get('script_rate')} | **{r.get('score')}** | {r.get('elapsed_sec')} |\n"
    REPORT.write_text(report, encoding="utf-8")
    print("\n验证报告已追加：", REPORT)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
