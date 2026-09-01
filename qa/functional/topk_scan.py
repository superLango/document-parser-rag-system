"""top_k 扫描: 找能全数召回目标块的最小 top_k。

对多份文档 × 全部类别, 用不同 top_k/candidate 配置跑 V3 检索, 统计
「所有目标块全数召回」所需的最小 top_k。目标: 验证降 top_k 不丢数据。

用法: PYTHONPATH=. python qa/functional/topk_scan.py
输出: qa/evaluation/results/topk_scan/scan.json
"""

import asyncio
import copy
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.extraction import category_builder, category_builder_v2, extraction_resolver
from app.services.indexing.bm25 import tokenize_text

KB = uuid.UUID("25e7d8ef-6268-42d7-ba0c-62516ffc93f9")
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/topk_scan")

# 扫描配置: 保持 per_dim/candidate 与 top_k 同步缩放
CONFIGS = {
    "k40":  {"top_k": 40, "candidate_mult": 4, "category_recall": {"mode": "loose", "top_k": 25, "per_dim_top_k": 40},
             "data_route_top_k": 40, "meta_route_top_k": 20, "context_top_k": 60},
    "k30":  {"top_k": 30, "candidate_mult": 3, "category_recall": {"mode": "loose", "top_k": 20, "per_dim_top_k": 30},
             "data_route_top_k": 30, "meta_route_top_k": 15, "context_top_k": 50},
    "k25":  {"top_k": 25, "candidate_mult": 3, "category_recall": {"mode": "loose", "top_k": 16, "per_dim_top_k": 25},
             "data_route_top_k": 25, "meta_route_top_k": 12, "context_top_k": 40},
    "k20":  {"top_k": 20, "candidate_mult": 2, "category_recall": {"mode": "loose", "top_k": 12, "per_dim_top_k": 20},
             "data_route_top_k": 20, "meta_route_top_k": 10, "context_top_k": 30},
    "k15":  {"top_k": 15, "candidate_mult": 2, "category_recall": {"mode": "loose", "top_k": 8, "per_dim_top_k": 15},
             "data_route_top_k": 15, "meta_route_top_k": 8, "context_top_k": 25},
}


def _hit(term: str, text: str):
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*", term):
        return term in tokenize_text(text)
    return term in text


async def _gold_tbl(db, doc_id, t) -> list[str]:
    chunks = (await db.execute(text(
        "SELECT chunk_id, content, content_for_embedding, has_table FROM document_chunks "
        "WHERE document_id=:d AND deleted_at IS NULL"), {"d": doc_id})).fetchall()
    tbl = [c for c in chunks if c.has_table]
    terms = []
    for qs in t.query_sources or []:
        if not qs.get("in_query", False):
            continue
        tb = qs.get("term_base_id")
        if not tb:
            continue
        rr = await category_builder.load_term_base(db, KB, uuid.UUID(str(tb)))
        gf = (qs.get("group_field") or "").strip()
        if gf:
            from app.services.extraction.term_base_loader import _read
            rr = [r for r in rr if str(_read(r, gf) or "").strip() == t.feature]
        from app.services.extraction.term_base_loader import distinct_field_values
        terms.extend(distinct_field_values(rr, qs.get("value_field") or "term_name", int(qs.get("query_main_limit") or 30)))
    gold = [c.chunk_id for c in tbl if any(_hit(w, c.content or "") or _hit(w, c.content_for_embedding or "") for w in terms)]
    return gold


async def main():
    db = AsyncSessionLocal()
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
        # 选多份文档: 不同规模(含大表/多表)
        docs = (await db.execute(text(
            "SELECT DISTINCT ON (sha256) id, filename FROM documents "
            "WHERE kb_id=:kb AND index_status='indexed' AND deleted_at IS NULL "
            "ORDER BY sha256, created_at DESC"), {"kb": KB})).fetchall()
        # 挑 8 份: GB-T1220(29表), JBT7030, DFHM, GH4169, SA-508, + 几份
        pick = [r for r in docs if any(k in (r.filename or "") for k in
            ("GB-T1220", "JBT7030", "000885", "GH4169", "SA-508", "2744", "GH3044", "TA15"))]
        doc_ids = [str(r.id) for r in pick[:3]]
        print(f"选定文档: {len(doc_ids)}", flush=True)

        out = {}
        for did in doc_ids:
            entry = {}
            for cfg_name, override in CONFIGS.items():
                over = {**override}
                rr = (cfg.global_config.get("retrieval") or {}).get("reranker") or {}
                over["reranker"] = {**rr, "threshold": -5.0, "semantic_evidence_enabled": True}
                # 对每个类别检索并统计 gold 全数召回
                for t in targets:
                    gold = await _gold_tbl(db, did, t)
                    if not gold:
                        continue
                    built, sk = await category_builder_v2.build_one_v2(
                        cfg, db, kb_id=KB, document_id=did,
                        target=copy.deepcopy(t), retrieval_override=over,
                    )
                    if built is None:
                        continue
                    ids = {h["chunk_id"] for h in built.hits}
                    rec = sum(1 for g in gold if g in ids)
                    key = f"{t.feature}__{len(gold)}"
                    entry.setdefault(key, {})[cfg_name] = {"recall": round(rec/len(gold), 3), "recalled": rec, "need": len(gold)}
            out[did] = {"name": next(r.filename for r in pick if str(r.id)==did), "results": entry}
            print(f"  doc {did[:8]} done ({len(entry)} 类别)", flush=True)
        (RESULTS / "scan.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果: {RESULTS/'scan.json'}", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
