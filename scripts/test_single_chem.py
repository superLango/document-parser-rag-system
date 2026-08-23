"""化学成分单类别抽取测试（排除并发竞争）。

走完整产品代码：build_one 检索/重排 → assemble_full_sorted → LangExtractPkg(内网模型)。
用法（能访问内网的环境）：
    cd /home/grainuser/hansonDoc_RAG/backend
    PYTHONPATH=. .venv/bin/python ../scripts/test_single_chem.py
输出保存到 qa/evaluation/results/gb1220_single_chem/run.json + meta.json
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services import kb_resource_service
from app.services.extraction import (
    category_builder,
    context_assembler,
    extraction_resolver,
    lang_pkg_extractor,
)

KB = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
DOC = "09a79bb1-1c17-44bc-bb02-57eab2e25580"  # GB-T1220-2007 不锈钢棒
FEATURE = "化学成分"
OUT = Path(__file__).resolve().parents[1] / "qa/evaluation/results/gb1220_single_chem"


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = AsyncSessionLocal()
    await db.execute(text("SELECT set_config('app.current_kb', :k, true)"), {"k": KB})
    await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": "10d34ab7-d543-4a8c-97da-2aeb78209df7"})
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))

    cfg = await extraction_resolver.resolve(db, KB)
    targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
    tgt = next(t for t in targets if t.feature == FEATURE)
    print(f"目标类别: {FEATURE}", flush=True)

    # 1) 检索/重排（与产品 build_one 一致）
    t0 = time.monotonic()
    built, sk = await category_builder.build_one(cfg, db, kb_id=KB, document_id=DOC, target=tgt)
    if built is None:
        print("检索被跳过:", sk.reason if sk else "未知", flush=True)
        await db.close()
        return
    hits = built.hits or []
    print(f"检索完成: hits={len(hits)}，耗时 {time.monotonic()-t0:.0f}s", flush=True)

    # 2) 上下文组装（实验1：按页码排序 + 表号/类型标签，不用重排分数）
    retrieval_cfg = cfg.global_config.get("retrieval") or {}
    ctx_top_k = min(built.top_k or int(retrieval_cfg.get("top_k") or 10),
                    int(retrieval_cfg.get("context_top_k") or 30))

    # 表号/类型标签（GB1220 化学成分类别按页码映射；其他块按内容标记）
    TABLE_TAG = {
        8: "表1 奥氏体型不锈钢化学成分",
        9: "表1(续) 奥氏体型不锈钢化学成分",
        10: "表2 奥氏体-铁素体型不锈钢化学成分",
        11: "表4 马氏体型不锈钢化学成分",
        12: "表5 沉淀硬化型不锈钢化学成分",
        19: "表16 钢棒检验项目/试验方法/取样",
    }
    def block_tag(h):
        pages = h.get("source_pages") or []
        pno = int(pages[0]) if pages else 0
        if h.get("has_table"):
            return TABLE_TAG.get(pno, f"表格(第{pno}页)")
        if pno == 7:
            return "7.1 牌号及化学成分条款"
        if pno == 19:
            return "取样/试验方法条款"
        return f"正文(第{pno}页)"

    ordered = sorted(hits, key=lambda h: (int((h.get("source_pages") or [0])[0]), h.get("chunk_id", "")))[:ctx_top_k]
    parts = []
    for h in ordered:
        pages = h.get("source_pages") or []
        tag = block_tag(h)
        page_txt = f"[{tag}][第 {pages[0]} 页]" if pages else f"[{tag}]"
        parts.append(f"{page_txt}\n{h.get('content') or ''}")
    context = "\n\n".join(parts)
    print(f"上下文: {len(context)} 字符, 块数={len(ordered)}（按页码排序+表标签）", flush=True)
    for h in ordered:
        print(f"  {block_tag(h)} | {len(h.get('content') or '')} 字符", flush=True)
    segments = [{"type": "text", "content": context}]

    # 3) LangExtractPkg 抽取（内网模型）
    engine = (cfg.global_config.get("llm") or {}).get("engine") or "LangExtractPkg"
    engine_params = ((cfg.global_config.get("llm") or {}).get("engines") or {}).get(engine) or {}
    # 实验 B：关闭 XGrammar 输出约束（纯 prompt JSON）
    engine_params = dict(engine_params)
    engine_params["output_schema_enabled"] = False
    llm_endpoint = await kb_resource_service.get_llm_resource_raw(db, KB)
    print("LLM 端点:", llm_endpoint.get("api_base"), "| model:", llm_endpoint.get("model"), flush=True)
    print("engine_params max_tokens:", engine_params.get("max_tokens"), "| concurrency:", engine_params.get("concurrency"), flush=True)

    t1 = time.monotonic()
    records = await lang_pkg_extractor.extract_category_pkg(
        kb_id=KB, cfg=cfg, target=built, context=context, segments=segments,
        engine_params=engine_params, llm_endpoint=llm_endpoint or {},
    )
    elapsed = time.monotonic() - t1
    print(f"抽取完成: {len(records)} 条, 耗时 {elapsed:.0f}s", flush=True)

    # 4) 保存 + 统计
    (OUT / "run.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    brands = {}
    for r in records:
        brands.setdefault(r.get("材料牌号") or "", []).append(r)
    fields = ["材料牌号", "项目名称", "单位", "标准要求", "试验方法", "位置", "方向",
              "尺寸厚度", "试样状态", "取样数量", "取样说明", "锻件类型", "试验温度"]
    fill = {f: sum(1 for r in records if r.get(f) not in (None, "")) for f in fields}
    meta = {
        "records": len(records),
        "brands": len(brands),
        "field_fill": {k: round(v / len(records), 3) if records else 0 for k, v in fill.items()},
        "context_chars": len(context),
        "hits": len(hits),
        "search_sec": round(time.monotonic() - t0, 1),
        "extract_sec": round(elapsed, 1),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n牌号数:", len(brands))
    for f in fields:
        print(f"  {f}: {fill[f]}/{len(records)}")
    print("\n结果保存:", OUT)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
