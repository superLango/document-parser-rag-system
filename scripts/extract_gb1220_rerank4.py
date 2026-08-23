"""4 个 0 条类别用重排分数排序重跑（自研直调），验证排序策略是否是根因。

用法（能访问内网 + 项目 DB）：
    cd /home/grainuser/hansonDoc_RAG/backend
    PYTHONPATH=. .venv/bin/python ../scripts/extract_gb1220_rerank4.py
输出：qa/evaluation/results/gb1220_builtin_all/rerank4_<类别>.json + rerank4_meta.json
"""

import asyncio
import json
import re
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
DOC = "09a79bb1-1c17-44bc-bb02-57eab2e25580"
OUT = Path(__file__).resolve().parents[1] / "qa/evaluation/results/gb1220_builtin_all"
FEATURES = ["热处理制度", "洛氏硬度", "晶粒度", "标准信息"]
MAX_TOKENS = 100000


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


async def extract_one(client, cfg, target):
    db = target._db
    built, sk = await category_builder.build_one(cfg, db, kb_id=KB, document_id=DOC, target=target)
    if built is None:
        return {"feature": target.feature, "status": "skipped", "reason": sk.reason if sk else ""}
    retrieval_cfg = cfg.global_config.get("retrieval") or {}
    ctx_top_k = min(built.top_k or int(retrieval_cfg.get("top_k") or 10),
                    int(retrieval_cfg.get("context_top_k") or 30))
    # 重排分数降序（产品默认），非页码
    context = context_assembler.assemble_full_sorted(built.hits or [], top_k=ctx_top_k)
    if not context.strip():
        return {"feature": target.feature, "status": "no_context"}
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
    r = await client.post(cfg._llm_url, json=body, headers=cfg._headers, timeout=None)
    r.raise_for_status()
    data = r.json()
    dt = time.monotonic() - t0
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    usage = data.get("usage") or {}
    recs, perr = parse_records(content, target.return_type)
    ct = usage.get("completion_tokens") or 0
    (OUT / f"rerank4_{target.feature}.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "feature": target.feature,
        "status": "done",
        "records": len(recs),
        "context_chars": len(context),
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": ct,
        "elapsed_sec": round(dt, 1),
        "tokens_per_sec": round(ct / dt, 1) if dt > 0 else 0,
        "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
        "parse_error": perr or None,
    }


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = AsyncSessionLocal()
    await db.execute(text("SELECT set_config('app.current_kb', :k, true)"), {"k": KB})
    await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": "10d34ab7-d543-4a8c-97da-2aeb78209df7"})
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
    cfg = await extraction_resolver.resolve(db, KB)
    targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
    targets = [t for t in targets if t.feature in FEATURES]
    llm = await kb_resource_service.get_llm_resource_raw(db, KB)
    cfg._llm_url = (llm.get("api_base") or "").rstrip("/") + "/chat/completions"
    cfg._model = llm.get("model")
    cfg._headers = {"Authorization": f"Bearer {llm.get('api_key') or ''}", "Content-Type": "application/json"}
    for t in targets:
        t._db = db
    print("重排排序（产品默认）抽取类别:", [t.feature for t in targets], flush=True)
    async with httpx.AsyncClient(timeout=None) as client:
        t_all = time.monotonic()
        results = await asyncio.gather(*(extract_one(client, cfg, t) for t in targets))
        total_sec = time.monotonic() - t_all
    meta = {"wall_clock_sec": round(total_sec, 1), "categories": results}
    (OUT / "rerank4_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n===== 结果（重排分数排序）=====")
    for r in sorted(results, key=lambda x: x.get("feature", "")):
        print(f"  {r.get('feature')}: {r.get('records')} 条 | {r.get('completion_tokens')} tok | {r.get('elapsed_sec')}s | {r.get('tokens_per_sec')} tok/s | fin={r.get('finish_reason')}")
    print("\n对比（页码排序原结果）：热处理 0 / 洛氏 0 / 晶粒度 0 / 标准信息 0")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
