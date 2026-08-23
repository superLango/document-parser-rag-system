"""诊断标准信息类别：检索上下文内容 + prompt 渲染 + 是否含关键块。

用法：
    cd /home/grainuser/hansonDoc_RAG/backend
    PYTHONPATH=. .venv/bin/python ../scripts/diag_standard_info.py
"""
import asyncio
import json
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.extraction import category_builder, context_assembler, extraction_resolver, prompt_renderer

KB = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
DOC = "09a79bb1-1c17-44bc-bb02-57eab2e25580"


async def main():
    db = AsyncSessionLocal()
    await db.execute(text("SELECT set_config('app.current_kb', :k, true)"), {"k": KB})
    await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": "10d34ab7-d543-4a8c-97da-2aeb78209df7"})
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
    cfg = await extraction_resolver.resolve(db, KB)
    targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
    tgt = next(t for t in targets if t.feature == "标准信息")
    print("类别:", tgt.feature, "| query_sources:", tgt.query_sources, "| fixed_query:", tgt.fixed_query, flush=True)
    built, sk = await category_builder.build_one(cfg, db, kb_id=KB, document_id=DOC, target=tgt)
    if built is None:
        print("skipped:", sk.reason if sk else ""); return
    hits = built.hits or []
    print(f"\nhits: {len(hits)}")
    for h in hits:
        pages = h.get("source_pages") or []
        content = (h.get("content") or "")[:90].replace("\n", " ")
        print(f"  p{pages} rerank={h.get('rerank_score') and round(h.get('rerank_score'),2)} | {content}")
    ctx = context_assembler.assemble_full_sorted(hits, top_k=20)
    print(f"\n上下文: {len(ctx)} 字符")
    print("含 'GB/T 1220':", "GB/T 1220" in ctx)
    print("含 '代替':", "代替" in ctx)
    print("含 '不锈钢棒':", "不锈钢棒" in ctx)
    print("含 '中华人民共和国国家标准':", "中华人民共和国国家标准" in ctx)
    print("\n上下文开头 600 字:")
    print(ctx[:600])
    system, user = prompt_renderer.render_category(cfg, built, ctx)
    print("\n=== system ===")
    print(system[:400])
    print("\n=== user 前 400 字 ===")
    print(user[:400])
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
