"""GB-T1220 全量抽取（自研直调引擎，绕开 LangExtract）。

流程：build_one 检索/重排 → 页码排序+类型标签组装 → render_category prompt
     → httpx 直调内网模型（enable_thinking=false, max_tokens 动态）→ 解析记录
并发 32；记录每类别与全程 tokens 吞吐。

用法（能访问内网 + 项目 DB 的环境）：
    cd /home/grainuser/hansonDoc_RAG/backend
    PYTHONPATH=. .venv/bin/python ../scripts/extract_gb1220_builtin.py
输出：qa/evaluation/results/gb1220_builtin_all/（每类别 run_<类别>.json + meta.json）
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services import kb_resource_service
from app.services.extraction import (
    category_builder,
    context_assembler,
    extraction_resolver,
    prompt_renderer,
)

KB = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
DOC = "09a79bb1-1c17-44bc-bb02-57eab2e25580"  # GB-T1220-2007 不锈钢棒
OUT = Path(__file__).resolve().parents[1] / "qa/evaluation/results/gb1220_builtin_all"
MAX_TOKENS = 100000
CONCURRENCY = 32
# 主排序模式：page=页码排序（按正常文档顺序抽取）
# 某类别抽取结果为 0 条时，自动用 rerank（重排分数降序）再抽一次，
# 解决热处理制度/晶粒度等附录类内容在页码排序下漏抽的问题。
SORT_MODE = "page"
RETRY_RERANK_ON_EMPTY = True
# 表号映射（GB1220 已知页；其他页按通用标签）
TABLE_TAG = {
    8: "表1 奥氏体型化学成分", 9: "表1(续) 奥氏体型化学成分",
    10: "表2 奥氏体-铁素体型化学成分", 11: "表4 马氏体型化学成分",
    12: "表5 沉淀硬化型化学成分", 13: "力学性能表(续)", 14: "力学性能表",
    15: "力学性能表(续)", 16: "力学性能表(续)",
    17: "耐腐蚀/晶间腐蚀表", 19: "表16 检验项目/试验方法/取样",
    21: "附录A 热处理制度", 22: "附录A 热处理制度",
}


def block_tag(h):
    pages = h.get("source_pages") or []
    pno = int(pages[0]) if pages else 0
    tag = TABLE_TAG.get(pno, "")
    kind = "表格" if h.get("has_table") else "正文"
    if tag:
        return f"{tag}"
    return f"{kind}(第{pno}页)"


def assemble_ordered(hits, top_k):
    ordered = sorted(hits, key=lambda h: (int((h.get("source_pages") or [0])[0]), h.get("chunk_id", "")))[:top_k]
    parts = []
    for h in ordered:
        pages = h.get("source_pages") or []
        tag = block_tag(h)
        page_txt = f"[{tag}][第 {pages[0]} 页]" if pages else f"[{tag}]"
        parts.append(f"{page_txt}\n{h.get('content') or ''}")
    return "\n\n".join(parts), ordered


def parse_records(content, return_type="array"):
    t = content.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        data = json.loads(t)
    except Exception:
        for m in re.finditer(r"\[.*?\]", t, re.S):
            try:
                data = json.loads(m.group(0))
                break
            except Exception:
                continue
        else:
            return [], t[:200]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)], ""
    if isinstance(data, dict):
        # 兼容 {"records": [...]} 包装
        if isinstance(data.get("records"), list):
            return [r for r in data["records"] if isinstance(r, dict)], ""
        # 兼容旧版 {"items": [...]} 等单数组包装
        arrs = [v for v in data.values() if isinstance(v, list)]
        if arrs:
            return [r for r in arrs[0] if isinstance(r, dict)], ""
        # object 返回类型（如标准信息）：字典本身就是一条记录
        if return_type == "object" or data:
            return [data], ""
    return [], ""


async def _call_llm(client, sem, cfg, built, context, target):
    """组装 prompt 并调用一次模型，返回 (records, parse_err, usage, dt, finish_reason)。"""
    system, user = prompt_renderer.render_category(cfg, built, context)
    user = user.replace("${prev_brands}", "")
    body = {
        "model": cfg._model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.monotonic()
    async with sem:
        r = await client.post(cfg._llm_url, json=body, headers=cfg._headers, timeout=None)
        r.raise_for_status()
        data = r.json()
    dt = time.monotonic() - t0
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    usage = data.get("usage") or {}
    recs, perr = parse_records(content, target.return_type)
    return recs, perr, usage, dt, (data.get("choices") or [{}])[0].get("finish_reason")


async def extract_one(client, sem, cfg, target):
    """单类别：检索 → 页码排序抽取 → 0 条时重排重试。返回统计。"""
    db = target._db
    built, sk = await category_builder.build_one(cfg, db, kb_id=KB, document_id=DOC, target=target)
    if built is None:
        return {"feature": target.feature, "status": "skipped", "reason": sk.reason if sk else ""}
    retrieval_cfg = cfg.global_config.get("retrieval") or {}
    ctx_top_k = min(built.top_k or int(retrieval_cfg.get("top_k") or 10),
                    int(retrieval_cfg.get("context_top_k") or 30))
    hits = built.hits or []

    def make_context(mode):
        if mode == "page":
            return assemble_ordered(hits, ctx_top_k)
        return context_assembler.assemble_full_sorted(hits, top_k=ctx_top_k), hits

    primary_mode = SORT_MODE
    context1, ordered1 = make_context(primary_mode)
    # 首轮上下文为空时，若允许重试则直接切重排
    if not context1.strip() and RETRY_RERANK_ON_EMPTY and primary_mode != "rerank":
        primary_mode = "rerank"
        context1, ordered1 = make_context(primary_mode)
    if not context1.strip():
        return {"feature": target.feature, "status": "no_context"}

    recs1, perr1, usage1, dt1, fin1 = await _call_llm(client, sem, cfg, built, context1, target)
    retried = False
    retry_stat = None
    if not recs1 and RETRY_RERANK_ON_EMPTY and primary_mode != "rerank":
        context2, ordered2 = make_context("rerank")
        if context2.strip():
            recs2, perr2, usage2, dt2, fin2 = await _call_llm(client, sem, cfg, built, context2, target)
            retried = True
            retry_stat = {
                "mode": "rerank",
                "records": len(recs2),
                "context_chars": len(context2),
                "hits": len(ordered2),
                "prompt_tokens": usage2.get("prompt_tokens") or 0,
                "completion_tokens": usage2.get("completion_tokens") or 0,
                "elapsed_sec": round(dt2, 1),
                "finish_reason": fin2,
                "parse_error": perr2 or None,
            }
            if recs2:
                # 重排出数则采用重排结果；仍为空则保留首轮（空）结果
                recs1, perr1, usage1, dt1, fin1 = recs2, perr2, usage2, dt2, fin2

    total_pt = (usage1.get("prompt_tokens") or 0) + ((retry_stat or {}).get("prompt_tokens") or 0)
    total_ct = (usage1.get("completion_tokens") or 0) + ((retry_stat or {}).get("completion_tokens") or 0)
    total_dt = dt1 + ((retry_stat or {}).get("elapsed_sec") or 0)
    speed = (total_ct / total_dt) if total_dt > 0 else 0
    (OUT / f"run_{target.feature}.json").write_text(
        json.dumps(recs1, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "feature": target.feature,
        "status": "done",
        "records": len(recs1),
        "mode": primary_mode,
        "retried": retried,
        "retry": retry_stat,
        "context_chars": len(context1),
        "hits": len(ordered1),
        "prompt_tokens": total_pt,
        "completion_tokens": total_ct,
        "total_tokens": total_pt + total_ct,
        "elapsed_sec": round(total_dt, 1),
        "tokens_per_sec": round(speed, 1),
        "finish_reason": fin1,
        "parse_error": perr1 or None,
    }


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = AsyncSessionLocal()
    await db.execute(text("SELECT set_config('app.current_kb', :k, true)"), {"k": KB})
    await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": "10d34ab7-d543-4a8c-97da-2aeb78209df7"})
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
    cfg = await extraction_resolver.resolve(db, KB)
    targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
    print(f"类别总数: {len(targets)} | 上下文排序: {SORT_MODE}", flush=True)

    llm = await kb_resource_service.get_llm_resource_raw(db, KB)
    cfg._llm_url = (llm.get("api_base") or "").rstrip("/") + "/chat/completions"
    cfg._model = llm.get("model")
    cfg._headers = {"Authorization": f"Bearer {llm.get('api_key') or ''}", "Content-Type": "application/json"}
    for t in targets:
        t._db = db
    print("LLM:", cfg._llm_url, "| model:", cfg._model, flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=None) as client:
        t_all = time.monotonic()
        results = await asyncio.gather(*(extract_one(client, sem, cfg, t) for t in targets))
        total_sec = time.monotonic() - t_all

    done = [r for r in results if r.get("status") == "done"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    tot_records = sum(r["records"] for r in done)
    tot_pt = sum(r["prompt_tokens"] for r in done)
    tot_ct = sum(r["completion_tokens"] for r in done)
    sum_sec = sum(r["elapsed_sec"] for r in done)
    meta = {
        "categories_total": len(targets),
        "done": len(done),
        "skipped": [(r.get("feature"), r.get("reason")) for r in skipped],
        "total_records": tot_records,
        "total_prompt_tokens": tot_pt,
        "total_completion_tokens": tot_ct,
        "total_tokens": tot_pt + tot_ct,
        "wall_clock_sec": round(total_sec, 1),
        "sum_extract_sec": round(sum_sec, 1),
        "avg_completion_tokens_per_sec": round(tot_ct / total_sec, 1),
        "avg_total_tokens_per_sec": round((tot_pt + tot_ct) / total_sec, 1),
        "categories": results,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n===== 汇总 =====")
    print(f"类别: {len(done)} 成功 / {len(skipped)} 跳过 | 记录: {tot_records}")
    print(f"总 tokens: {tot_pt + tot_ct} (prompt {tot_pt} + completion {tot_ct})")
    print(f"墙钟耗时: {total_sec:.0f}s | 抽取合计: {sum_sec:.0f}s")
    print(f"吞吐: 输出 {tot_ct/total_sec:.1f} tokens/s | 总 { (tot_pt+tot_ct)/total_sec:.1f} tokens/s")
    print("\n每类别:")
    for r in sorted(done, key=lambda x: -x.get("completion_tokens", 0)):
        print(f"  {r['feature']}: {r['records']} 条 | {r['completion_tokens']} tok | {r['elapsed_sec']}s | {r['tokens_per_sec']} tok/s")
    for r in skipped:
        print(f"  SKIP {r['feature']}: {r['reason']}")
    print("\n结果目录:", OUT)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
