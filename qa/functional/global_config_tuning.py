"""全局配置调优：在 GJB3325A-2019（已解析+已索引）上执行 6 组配置对比。

用法：PYTHONPATH=backend:. backend/.venv/bin/python qa/functional/global_config_tuning.py
输出：qa/evaluation/reports/global_config_tuning.md（含指标对比与建议）
"""

import asyncio
import json
import time
from pathlib import Path

import asyncpg
import httpx

BASE = "http://127.0.0.1:8000/api/v1"
KB = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
DOC = "427fcb66-87f0-4e9b-904f-e8dbeaf4b2ab"  # GJB3325A-2019
REPORT = Path(__file__).resolve().parents[2] / "qa/evaluation/reports/global_config_tuning.md"

BASE_RETRIEVAL = {
    "top_k": 10,
    "candidate_mult": 2,
    "weights": {"title": 0.2, "content": 0.8},
    "default_confidence_threshold": 0.35,
    "context_max_tokens": 28000,
    "category_recall": {"mode": "loose", "top_k": 5, "per_dim_top_k": 10},
    "hybrid": {"enabled": True, "rrf_k": 60.0, "dense_weight": 1.0, "keyword_weight": 1.2, "keyword_min_hits": 1},
}
RESULTS_DIR = Path(__file__).resolve().parents[2] / "qa/evaluation/results/global_config_tuning"


async def reset_stuck_extraction() -> None:
    """调优中断/失败后，若任务仍处于 running，复位为 failed（保证可重新发起）。"""
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
    await conn.execute(
        "UPDATE document_tasks SET status='failed', error=jsonb_build_object('message','调优脚本复位') "
        "WHERE kb_id=$1 AND document_id=$2 AND type='document_extraction' AND status='running'",
        KB, DOC,
    )
    await conn.execute(
        "UPDATE extraction_results SET status='failed', progress=100, "
        "error=jsonb_build_object('message','调优脚本复位') "
        "WHERE kb_id=$1 AND document_id=$2 AND status='running'",
        KB, DOC,
    )
    await conn.close()


BASE_LLM = {
    "engine": "BaseExtract",
    "engines": {"BaseExtract": {
        "temperature": 0.0, "max_tokens": 32768, "timeout": 600,
        "concurrency": {"max_concurrency": 4, "cross_category": 4, "within_category": 1},
    }},
}

CONFIGS = [
    {"name": "BASE", "desc": "当前默认（top_k=10, ctx=28k, 混合默认）", "retrieval": {}},
    {"name": "CTX_SMALL", "desc": "小上下文（top_k=6, ctx=16k）", "retrieval": {"top_k": 6, "context_max_tokens": 16000}},
    {"name": "CTX_LARGE", "desc": "大上下文（top_k=12, ctx=40k）", "retrieval": {"top_k": 12, "context_max_tokens": 40000}},
    {"name": "KW_HEAVY", "desc": "词法权重高（kw=2.4, dense=0.8）", "retrieval": {"hybrid": {"rrf_k": 60.0, "dense_weight": 0.8, "keyword_weight": 2.4}}},
    {"name": "DENSE_HEAVY", "desc": "语义权重高（kw=0.6, dense=1.6）", "retrieval": {"hybrid": {"rrf_k": 60.0, "dense_weight": 1.6, "keyword_weight": 0.6}}},
    {"name": "STRICT", "desc": "严格召回（阈值0.035，无词法兜底）", "retrieval": {
        "default_confidence_threshold": 0.035,
        "category_recall": {"mode": "strict", "top_k": 5, "per_dim_top_k": 10},
        "hybrid": {"keyword_min_hits": 999},
    }},
]

CORE_FIELDS = {
    "标准信息": ["标准名称", "标准编号"],
    "热处理制度": ["材料牌号", "工艺名称", "工序名称"],
    "_project": ["材料牌号", "项目名称", "标准要求"],
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


async def login(client: httpx.AsyncClient) -> str:
    r = await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


async def set_config(client, h, retrieval: dict) -> None:
    content = {
        "retrieval": _deep_merge(BASE_RETRIEVAL, retrieval),
        "llm": BASE_LLM,
        "kb_tool": {"script_timeout": 60},
    }
    r = await client.put(f"/kb/{KB}/extraction-config/global", headers=h,
                         json={"enabled": True, "content": content})
    r.raise_for_status()


async def run_extraction(client, h, name: str) -> dict:
    r = await client.post(f"/kb/{KB}/extraction/{DOC}", headers=h)
    if r.status_code == 409:
        print(f"[{name}] 409 检测到残留运行任务，复位后重试", flush=True)
        await reset_stuck_extraction()
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


async def load_schema_fields() -> dict:
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
    rows = await conn.fetch("""
        SELECT c.name AS cat, f.name, f.required
        FROM schema_fields f JOIN schema_categories c ON c.id=f.category_id
        WHERE f.kb_id=$1 ORDER BY c.name, f.sort_order
    """, KB)
    await conn.close()
    fields: dict[str, list[str]] = {}
    for r in rows:
        key = r["cat"] or "_project"  # term_base 展开类别在 Schema 中名为空
        fields.setdefault(key, []).append(r["name"])
    return fields


def _cat_fields(feature: str, schema_fields: dict) -> list[str]:
    if feature in schema_fields:
        return schema_fields[feature]
    return schema_fields.get("_project") or []  # term_base 展开类别共用项目大类字段


def compute_metrics(result: dict, schema_fields: dict) -> dict:
    cats = result.get("categories") or []
    total_records = 0
    total_required_cells = 0
    filled_cells = 0
    complete_records = 0
    usable_records = 0
    script_marked = 0
    rejected = 0
    for cat in cats:
        fields = _cat_fields(cat.get("feature", ""), schema_fields)
        core = CORE_FIELDS.get(cat.get("feature", ""), CORE_FIELDS["_project"])
        for rec in cat.get("records") or []:
            total_records += 1
            missing = 0
            for f in fields:
                total_required_cells += 1
                if rec.get(f) not in (None, ""):
                    filled_cells += 1
                else:
                    missing += 1
            if missing == 0:
                complete_records += 1
            if all(rec.get(f) not in (None, "") for f in core):
                usable_records += 1
            if rec.get("_normalize_type") or rec.get("_method_year_filled"):
                script_marked += 1
        rejected += len(cat.get("rejected") or [])
    fill_rate = filled_cells / total_required_cells if total_required_cells else 0.0
    complete_rate = complete_records / total_records if total_records else 0.0
    usable_rate = usable_records / total_records if total_records else 0.0
    script_rate = script_marked / total_records if total_records else 0.0
    composite = 0.35 * fill_rate + 0.25 * complete_rate + 0.25 * usable_rate + 0.15 * script_rate
    return {
        "kept": len(cats),
        "records": total_records,
        "rejected": rejected,
        "fill_rate": round(fill_rate, 4),
        "complete_rate": round(complete_rate, 4),
        "usable_rate": round(usable_rate, 4),
        "script_rate": round(script_rate, 4),
        "score": round(composite, 4),
        "elapsed_sec": round((result.get("timing") or {}).get("total_sec") or 0, 1),
    }


async def main() -> None:
    schema_fields = await load_schema_fields()
    results: dict[str, dict] = {}
    async with httpx.AsyncClient(base_url=BASE, timeout=900) as client:
        token = await login(client)
        h = {"Authorization": f"Bearer {token}"}
        for cfg in CONFIGS:
            await set_config(client, h, cfg["retrieval"])
            print(f"\n===== RUN {cfg['name']} | {cfg['desc']} =====", flush=True)
            result_file = RESULTS_DIR / f"tuning_{cfg['name']}.json"
            if result_file.exists():
                print(f"[{cfg['name']}] 已存在结果，跳过（{result_file.name}）", flush=True)
                res = json.loads(result_file.read_text(encoding="utf-8"))
                results[cfg["name"]] = compute_metrics(res, schema_fields)
                results[cfg["name"]]["elapsed_sec"] = round((res.get("timing") or {}).get("total_sec") or 0, 1)
                continue
            t0 = time.monotonic()
            res = await run_extraction(client, h, cfg["name"])
            dt = time.monotonic() - t0
            if res.get("status") != "completed":
                results[cfg["name"]] = {"status": "failed", "error": (res.get("error") or {}).get("message", "未知")[:300], "elapsed_sec": round(dt, 1)}
                print("FAILED:", results[cfg["name"]]["error"], flush=True)
                continue
            m = compute_metrics(res, schema_fields)
            m["elapsed_sec"] = round(dt, 1)
            results[cfg["name"]] = m
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            result_file.write_text(
                json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("METRICS:", json.dumps(m, ensure_ascii=False), flush=True)
        await set_config(client, h, {})  # 恢复默认

    # 报告
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 全局配置调优报告（结构化抽取）", "", f"- 文档：GJB3325A-2019（doc={DOC}）", f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    lines.append("| 配置 | 说明 | 状态 | 保留类别 | 记录数 | 剔除 | 字段填充率 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for cfg in CONFIGS:
        name = cfg["name"]
        r = results.get(name) or {}
        if r.get("status") == "failed":
            lines.append(f"| {name} | {cfg['desc']} | FAIL | - | - | - | - | - | - | - | - | {r.get('elapsed_sec')} |")
            continue
        lines.append(f"| {name} | {cfg['desc']} | OK | {r.get('kept')} | {r.get('records')} | {r.get('rejected')} | {r.get('fill_rate')} | {r.get('complete_rate')} | {r.get('usable_rate')} | {r.get('script_rate')} | **{r.get('score')}** | {r.get('elapsed_sec')} |")
    lines.append("")
    lines.append("综合分 = 0.35×字段填充率 + 0.25×完整率 + 0.25×可用率 + 0.15×脚本命中率")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已输出：{REPORT}")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
