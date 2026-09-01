"""k30 vs k40 全量对比(38 份文档 = 76 的一半, 断点续跑)。

对每文档 × 每类别: 用 k30(LARGE_CANDIDATES)与 k40(LARGE_CANDIDATES_K40)
分别跑 V3 检索(语义证据+阈值-5), 统计目标块全数召回(recall)。
输出 qa/evaluation/results/retrieval_k30_k40/compare.json
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
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_k30_k40")


def _hit(term: str, text: str):
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*", term):
        return term in tokenize_text(text)
    return term in text


async def _gold_tbl(db, doc_id, t) -> tuple[list[str], int]:
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
    return gold, len(tbl)


async def main():
    db = AsyncSessionLocal()
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        out_path = RESULTS / "compare.json"
        existing = json.load(open(out_path, encoding="utf-8")) if out_path.exists() else {}
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
        docs = (await db.execute(text(
            "SELECT DISTINCT ON (sha256) id, filename FROM documents "
            "WHERE kb_id=:kb AND index_status='indexed' AND deleted_at IS NULL "
            "ORDER BY sha256, created_at DESC"), {"kb": KB})).fetchall()
        # 一半(38份): 按排序取偶/奇; 已完成的跳过(断点续跑)
        unique = [{"id": str(r.id), "name": r.filename} for r in docs]
        half = unique[: len(unique) // 2]
        todo = [d for d in half if d["id"] not in existing]
        print(f"文档总数: {len(unique)}, 半量: {len(half)}, 待跑: {len(todo)}", flush=True)

        rr = (cfg.global_config.get("retrieval") or {}).get("reranker") or {}
        for doc in todo:
            did = doc["id"]
            entries = []
            for t in targets:
                gold, n_tbl = await _gold_tbl(db, did, t)
                if not gold:
                    continue
                # k40
                over40 = {**category_builder_v2.LARGE_CANDIDATES_K40, "reranker": {**rr, "threshold": -5.0, "semantic_evidence_enabled": True}}
                b40, sk40 = await category_builder_v2.build_one_v2(cfg, db, kb_id=KB, document_id=did, target=copy.deepcopy(t), retrieval_override=over40)
                # k30
                over30 = {**category_builder_v2.LARGE_CANDIDATES, "reranker": {**rr, "threshold": -5.0, "semantic_evidence_enabled": True}}
                b30, sk30 = await category_builder_v2.build_one_v2(cfg, db, kb_id=KB, document_id=did, target=copy.deepcopy(t), retrieval_override=over30)

                def _m(b):
                    if b is None:
                        return {"recall": 0.0, "skipped": True}
                    ids = {h["chunk_id"] for h in b.hits}
                    rec = sum(1 for g in gold if g in ids)
                    return {"recall": round(rec / len(gold), 3), "recalled": rec, "need": len(gold), "hits": len(b.hits), "skipped": False}

                entries.append({"feature": t.feature, "need": len(gold), "tbl": n_tbl, "k40": _m(b40), "k30": _m(b30)})
            existing[did] = {"name": doc["name"], "categories": entries}
            out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            full40 = sum(1 for e in entries if not e["k40"]["skipped"] and e["k40"]["recall"] >= 1.0)
            full30 = sum(1 for e in entries if not e["k30"]["skipped"] and e["k30"]["recall"] >= 1.0)
            print(f"  {doc['name'][:40]} 实例{len(entries)} k40全= {full40} k30全={full30}", flush=True)
        print(f"完成: {len(existing)} 文档", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
