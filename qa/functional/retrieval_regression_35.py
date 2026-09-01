"""V3 最新逻辑(去重排+完整候选) 35 文档回归。

35 个不同文档(sha256 去重) × 全部展开类别:
  证据判定 → 3路检索(skip_rerank 完整 top_k) → 合并去重 → 无重排 → hits
统计: 全数召回率 / avg recall / 平均 hits / 跳过
输出: qa/evaluation/results/retrieval_regression_35/regression.json
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
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_regression_35")


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
    return [c.chunk_id for c in tbl if any(_hit(w, c.content or "") or _hit(w, c.content_for_embedding or "") for w in terms)]


async def main():
    db = AsyncSessionLocal()
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
        docs = (await db.execute(text(
            "SELECT DISTINCT ON (sha256) id, filename FROM documents "
            "WHERE kb_id=:kb AND index_status='indexed' AND deleted_at IS NULL "
            "ORDER BY sha256, created_at DESC"), {"kb": KB})).fetchall()
        # 35 个不同文档(按 sha256 去重后取前 35)
        uniq = [{"id": str(r.id), "name": r.filename} for r in docs]
        pick = uniq[:35]
        print(f"文档总数(去重): {len(uniq)}, 选取: {len(pick)}", flush=True)

        rr = (cfg.global_config.get("retrieval") or {}).get("reranker") or {}
        v3 = {**category_builder_v2.LARGE_CANDIDATES, "reranker": {**rr, "threshold": -5.0, "semantic_evidence_enabled": True}}
        out = {}
        for doc in pick:
            did = doc["id"]
            entries = []
            for t in targets:
                gold = await _gold_tbl(db, did, t)
                if not gold:
                    continue
                b, sk = await category_builder_v2.build_one_v2(
                    cfg, db, kb_id=KB, document_id=did,
                    target=copy.deepcopy(t), retrieval_override=v3,
                )
                if b is None:
                    entries.append({"feature": t.feature, "need": len(gold), "recall": 0.0, "skipped": True, "reason": (sk.reason if sk else "")[:150], "hits": 0})
                    continue
                ids = {h["chunk_id"] for h in b.hits}
                rec = sum(1 for g in gold if g in ids) / len(gold)
                entries.append({"feature": t.feature, "need": len(gold), "recall": round(rec, 3), "recalled": sum(1 for g in gold if g in ids), "skipped": False, "hits": len(b.hits)})
            out[did] = {"name": doc["name"], "categories": entries}
            tot = len(entries)
            full = sum(1 for e in entries if not e["skipped"] and e["recall"] >= 1.0)
            print(f"  {doc['name'][:45]} 实例={tot} 全数={full}", flush=True)
        (RESULTS / "regression.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        # 汇总
        all_e = [e for d in out.values() for e in d["categories"]]
        full_n = sum(1 for e in all_e if not e["skipped"] and e["recall"] >= 1.0)
        skip_n = sum(1 for e in all_e if e["skipped"])
        avg = sum(e["recall"] for e in all_e) / max(1, len(all_e))
        print(f"\nFINAL 35文档: 实例={len(all_e)} 全数召回={full_n} ({full_n/len(all_e):.3f}) 跳过={skip_n} avg_recall={avg:.3f}", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
