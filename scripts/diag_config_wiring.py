"""配置生效诊断：验证 前端可配置项 → 后端读取 → 送模型前链路（不调用 LLM）。

覆盖：全局配置解析 / LLM 资源 / Schema 类别展开（特殊要求）/ 两路检索 query /
检索与重排 hits / 类别过滤 / 上下文组装排序 / Prompt 完整渲染。

用法（不依赖内网 LLM）：
    cd /home/grainuser/hansonDoc_RAG/backend
    PYTHONPATH=. .venv/bin/python ../scripts/diag_config_wiring.py
"""

import asyncio
import json
from pathlib import Path

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
# 代表性类别（覆盖 数据路/元信息路/附录类/object 类）
SAMPLES = ["室温拉伸", "化学成分", "热处理制度", "标准信息", "晶粒度", "热膨胀"]
OUT = Path(__file__).resolve().parents[1] / "qa/evaluation/results/config_wiring_diag"


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = AsyncSessionLocal()
    await db.execute(text("SELECT set_config('app.current_kb', :k, true)"), {"k": KB})
    await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": "10d34ab7-d543-4a8c-97da-2aeb78209df7"})
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
    report: dict = {}

    # ============ 1) 全局配置解析（默认合并 + KB 覆盖） ============
    cfg = await extraction_resolver.resolve(db, KB)
    g = cfg.global_config
    retrieval = g.get("retrieval") or {}
    llm = g.get("llm") or {}
    report["retrieval"] = {
        "top_k": retrieval.get("top_k"),
        "candidate_mult": retrieval.get("candidate_mult"),
        "weights": retrieval.get("weights"),
        "default_confidence_threshold": retrieval.get("default_confidence_threshold"),
        "context_top_k": retrieval.get("context_top_k"),
        "context": retrieval.get("context"),
        "category_recall": retrieval.get("category_recall"),
        "data_route_top_k": retrieval.get("data_route_top_k"),
        "meta_route_top_k": retrieval.get("meta_route_top_k"),
        "query_embed": retrieval.get("query_embed"),
        "hybrid": retrieval.get("hybrid"),
        "reranker": retrieval.get("reranker"),
    }
    report["llm_engine"] = llm.get("engine")
    report["llm_engine_params"] = (llm.get("engines") or {}).get(llm.get("engine"))

    # ============ 2) LLM 资源（只读配置，不调用） ============
    llm_res = await kb_resource_service.get_llm_resource_raw(db, KB)
    report["llm_resource"] = {
        "enabled": llm_res.get("enabled"),
        "api_base": llm_res.get("api_base"),
        "model": llm_res.get("model"),
        "api_key_len": len(llm_res.get("api_key") or ""),
        "timeout": llm_res.get("timeout"),
    }

    # ============ 3) 类别展开（含特殊要求挂载） ============
    targets, skipped = await category_builder.build_targets(cfg, db, kb_id=KB)
    report["targets"] = {
        "total": len(targets),
        "skipped": [(s.feature, s.reason) for s in skipped],
        "special_requirement_samples": {
            t.feature: t.special_requirement
            for t in targets if t.special_requirement
        },
    }

    # ============ 4) 代表性类别：检索/重排/过滤/上下文/Prompt（不调 LLM） ============
    details: dict[str, dict] = {}
    for name in SAMPLES:
        t = next((x for x in targets if x.feature == name), None)
        if t is None:
            details[name] = {"status": "未在展开类别中"}
            continue
        built, sk = await category_builder.build_one(
            cfg, db, kb_id=KB, document_id=DOC, target=t,
        )
        if built is None:
            details[name] = {"status": "skipped", "reason": sk.reason if sk else ""}
            continue
        hits = built.hits or []
        rerank_scores = [round(h.get("rerank_score") or 0, 3) for h in hits if h.get("rerank_score") is not None]
        ctx_top_k = min(
            built.top_k or int((retrieval.get("top_k") or 10)),
            int((retrieval.get("context_top_k") or 30)),
        )
        context = context_assembler.assemble_page_order(hits, top_k=ctx_top_k)
        system, user = prompt_renderer.render_category(cfg, built, context)
        details[name] = {
            "status": "ready(送模型前)",
            "query_chars": len(built.query_terms or []),
            "hits": len(hits),
            "rerank_scores_range": (min(rerank_scores), max(rerank_scores)) if rerank_scores else None,
            "context_chars": len(context),
            "sort_first_block": (context or "").split("\n\n")[0][:80],
            "special_requirement": built.special_requirement,
            "prompt_user_head": user[:260].replace("\n", " | "),
        }
    report["sample_categories"] = details

    (OUT / "config_wiring_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # ============ 打印 ============
    print("===== 1) 全局配置（默认合并后） =====")
    print(json.dumps(report["retrieval"], ensure_ascii=False, indent=1))
    print("llm.engine:", report["llm_engine"])
    print("\n===== 2) LLM 资源（不调用） =====")
    print(json.dumps(report["llm_resource"], ensure_ascii=False))
    print("\n===== 3) 类别展开 =====")
    print("总类别:", report["targets"]["total"], "| 特殊要求:", report["targets"]["special_requirement_samples"])
    print("\n===== 4) 代表性类别（送模型前） =====")
    for name, d in details.items():
        print(f"\n--- {name} ---")
        print(json.dumps(d, ensure_ascii=False, indent=1))
    print("\n报告已保存:", OUT / "config_wiring_report.json")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
