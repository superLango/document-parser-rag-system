"""检索召回与重排诊断（不触发抽取）。

目标：定位抽取质量差的根因——是"召回候选缺失"还是"排序/重排不足"。

- A. 全部 41 个类别：hybrid 检索 top15，统计 query 长度、命中分数分布、
  目标内容块（按页面范围推断的表格块）是否进入候选；
- B. 关键 7 个类别：叠加 bge-reranker-v2-m3 重排，统计目标块排名变化与重排耗时；
- C. 向量余弦直接验证：query 与目标块的 BGE-M3 相似度。
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.database import AsyncSessionLocal
from app.services.extraction.category_builder import _build_query_terms
from app.services.extraction.extraction_models import ExtractionTarget
from app.services.indexing.retrieval import SearchFilters, retrieval_service

KB = uuid.UUID("25e7d8ef-6268-42d7-ba0c-62516ffc93f9")
DOC = uuid.UUID("09a79bb1-1c17-44bc-bb02-57eab2e25580")
RERANKER_MODEL = "/home/grainuser/hansonDoc_RAG/models/bge-reranker-v2-m3"
RESULTS_DIR = Path(__file__).resolve().parents[2] / "qa/evaluation/results/retrieval_diag"

RETRIEVAL = {
    "top_k": 15, "candidate_mult": 2, "weights": {"title": 0.2, "content": 0.8},
    "default_confidence_threshold": 0.035, "context_top_k": 30,
    "category_recall": {"mode": "loose", "top_k": 8, "per_dim_top_k": 10},
    "hybrid": {"enabled": True, "rrf_k": 60.0, "dense_weight": 1.0, "keyword_weight": 1.2, "keyword_min_hits": 1},
    "reranker": {"enabled": False, "model": "", "top_n": 15},
}

# 关键类别 → 目标内容所在页面范围（表格块；依据 OCR md 的章节/表位置）
KEY_TARGETS = {
    "布氏硬度": (12, 16),   # 表7/8/9/10 力学性能表的硬度列
    "室温拉伸": (12, 16),   # 表6/7/8/9/10 力学性能表
    "化学成分": (8, 12),    # 表1~表5 化学成分表
    "低倍": (18, 19),       # 表13 低倍组织 + 表16 检验规则
    "塔形": (18, 19),       # 表16 检验规则（塔形取样）
    "晶间腐蚀": (17, 17),   # 表12 晶间腐蚀
    "热处理制度": (21, 23), # 附录A 表A.1~A.5
}


def _target(chunks, lo: int, hi: int) -> list[dict]:
    return [
        c for c in chunks
        if c["has_table"] and any(lo <= int(p) <= hi for p in c["pages"])
    ]


async def build_query_target(feature: str) -> ExtractionTarget:
    return ExtractionTarget(
        feature=feature,
        category_id="10070867-86de-4cad-9949-dc998a3c331f",
        template_id="6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
        description="",
        return_type="array",
        extraction_strategy="auto",
        fixed_query="",
        query_sources=[
            {"label": "检测项目", "dedupe": True, "in_query": True, "group_field": "FEATURE",
             "value_field": "NAME", "term_base_id": "ab03135a-781f-40ff-a2d6-75c9c9941d47",
             "query_main_limit": 30, "query_refined_limit": 8},
            {"label": "试验方法", "dedupe": True, "in_query": True, "group_field": "FEATURE",
             "value_field": "METHOD_CODE", "term_base_id": "a2970518-dca6-4ef8-b59c-bb597535007b",
             "query_main_limit": 30, "query_refined_limit": 8},
        ],
        fields=[],
    )


async def main():
    import asyncpg

    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
    rows = await conn.fetch(
        "SELECT chunk_id, source_pages, has_table, length(content) AS clen FROM document_chunks "
        "WHERE kb_id=$1 AND document_id=$2 AND deleted_at IS NULL",
        KB, DOC,
    )
    chunks = [
        {
            "chunk_id": r["chunk_id"],
            "pages": (
                json.loads(r["source_pages"]) if isinstance(r["source_pages"], str) else (r["source_pages"] or [])
            ),
            "has_table": bool(r["has_table"]),
            "clen": r["clen"],
        }
        for r in rows
    ]
    await conn.close()

    # 41 个展开类别
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
    tb = "50c8936c-d5d4-46dd-9ae2-0059f7aad48d"
    trows = await conn.fetch(
        "SELECT extras FROM terms WHERE kb_id=$1 AND term_base_id=$2 AND deleted_at IS NULL", KB, tb
    )
    features = []
    for r in trows:
        ex = r["extras"] or {}
        if isinstance(ex, str):
            try:
                ex = json.loads(ex)
            except Exception:
                ex = {}
        name = ex.get("NAME") or ex.get("name")
        if name:
            features.append(name)
    await conn.close()
    features = sorted(set(features))
    print(f"展开类别数: {len(features)}", flush=True)

    db = AsyncSessionLocal()
    diag: dict = {"categories": []}
    for feature in features:
        target = await build_query_target(feature)
        terms = await _build_query_terms(db, KB, target, {}, 0.85)
        query = " ".join([feature, *terms]).strip() or feature
        hits = await retrieval_service.search(
            db, KB, query, top_k=15, per_dim_top_k=10,
            filters=SearchFilters(document_id=DOC),
            retrieval_config=RETRIEVAL,
        )
        scores = [h.score for h in hits]
        tbl_hits = [h for h in hits if getattr(h, "has_table", False)]
        entry = {
            "feature": feature,
            "query_len": len(query),
            "term_count": len(terms),
            "hits": len(hits),
            "score_min": round(min(scores), 4) if scores else None,
            "score_max": round(max(scores), 4) if scores else None,
            "table_hits": len(tbl_hits),
            "hit_pages": [h.source_pages for h in hits[:8]],
        }
        if feature in KEY_TARGETS:
            lo, hi = KEY_TARGETS[feature]
            targets = _target(chunks, lo, hi)
            target_ids = {t["chunk_id"] for t in targets}
            in_top = [i for i, h in enumerate(hits) if h.chunk_id in target_ids]
            entry["target_count"] = len(target_ids)
            entry["target_in_top15"] = bool(in_top)
            entry["target_ranks"] = in_top
        diag["categories"].append(entry)
        print(
            f"{feature:<10} q={entry['query_len']:>4} terms={entry['term_count']:>3} "
            f"hits={entry['hits']:>2} score[{entry['score_min']},{entry['score_max']}] "
            f"tbl={entry['table_hits']:>2} target_in_top15={entry.get('target_in_top15')} "
            f"ranks={entry.get('target_ranks')}",
            flush=True,
        )

    # B. 关键类别 + reranker 重排
    rerank_diag = []
    RETRIEVAL_RR = {**RETRIEVAL, "reranker": {"enabled": True, "model": RERANKER_MODEL, "top_n": 15}}
    for feature in KEY_TARGETS:
        target = await build_query_target(feature)
        terms = await _build_query_terms(db, KB, target, {}, 0.85)
        query = " ".join([feature, *terms]).strip() or feature
        t0 = time.monotonic()
        hits = await retrieval_service.search(
            db, KB, query, top_k=15, per_dim_top_k=10,
            filters=SearchFilters(document_id=DOC),
            retrieval_config=RETRIEVAL_RR,
        )
        dt = round(time.monotonic() - t0, 2)
        lo, hi = KEY_TARGETS[feature]
        target_ids = {t["chunk_id"] for t in _target(chunks, lo, hi)}
        in_top = [i for i, h in enumerate(hits) if h.chunk_id in target_ids]
        rerank_diag.append({
            "feature": feature,
            "rerank_sec": dt,
            "target_in_top15": bool(in_top),
            "target_ranks": in_top,
            "hit_pages": [h.source_pages for h in hits[:8]],
        })
        print(f"[rerank] {feature:<8} {dt}s target_in_top15={bool(in_top)} ranks={in_top}", flush=True)

    # C. 余弦相似度：query vs 目标块
    from app.services.embedding.embedding_service import embedding_service

    cosine_diag = []
    for feature, (lo, hi) in KEY_TARGETS.items():
        target = await build_query_target(feature)
        terms = await _build_query_terms(db, KB, target, {}, 0.85)
        query = " ".join([feature, *terms]).strip() or feature
        targets = _target(chunks, lo, hi)
        if not targets:
            continue
        # 取前 3 个目标块内容
        conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
        trows = await conn.fetch(
            "SELECT content FROM document_chunks WHERE chunk_id = ANY($1::text[])",
            [t["chunk_id"] for t in targets[:3]],
        )
        await conn.close()
        vecs = await embedding_service.embed([query] + [r["content"] for r in trows])
        qv = vecs[0]
        sims = []
        for v in vecs[1:]:
            sims.append(round(sum(a * b for a, b in zip(qv, v)), 4))
        cosine_diag.append({"feature": feature, "cosine_vs_targets": sims})
        print(f"[cosine] {feature:<8} query={query[:20]}... sims={sims}", flush=True)
    await db.close()

    diag["rerank"] = rerank_diag
    diag["cosine"] = cosine_diag
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "diag.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS_DIR / "README.md").write_text(
        "# 检索召回与重排诊断\n\n"
        f"- 文档：GB-T1220-2007（doc={DOC}）\n"
        "- target_in_top15=false 表示目标内容块未进入候选，属召回缺失（reranker 无法解决）\n"
        "- 详见 diag.json\n",
        encoding="utf-8",
    )
    print("\n结果目录：", RESULTS_DIR)


if __name__ == "__main__":
    asyncio.run(main())
