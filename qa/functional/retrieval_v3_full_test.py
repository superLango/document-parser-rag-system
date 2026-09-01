"""V3(语义证据判定+V2L) 全量测试：V1 vs V2L vs V3。

V3 = V2-L(文档感知术语全保留 + 候选放大) + 语义证据判定(方案D)。
对 76 个已向量化文档 × 41 类别,仅检索不做 LLM。
统计:总体 recall、找回类别数、跳过数。
输出: qa/evaluation/results/retrieval_v3/recall_v3.json
"""

import argparse
import asyncio
import copy
import json
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.extraction import category_builder, category_builder_v2, extraction_resolver
from app.services.indexing.bm25 import tokenize_text

KB = uuid.UUID("25e7d8ef-6268-42d7-ba0c-62516ffc93f9")
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_v3")


def _term_in_text(term: str, text: str) -> bool:
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*", term):
        return term in tokenize_text(text)
    return term in text


async def _load_chunks(db: AsyncSession, doc_id: str) -> list[dict]:
    rows = (await db.execute(text(
        "SELECT chunk_id, content, content_for_embedding, has_table FROM document_chunks "
        "WHERE document_id=:d AND deleted_at IS NULL"), {"d": doc_id})).fetchall()
    return [{"chunk_id": r.chunk_id, "content": r.content or "", "embed": r.content_for_embedding or "", "has_table": bool(r.has_table)} for r in rows]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()
    db = AsyncSessionLocal()
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        out_path = RESULTS / "recall_v3.json"
        existing = json.load(open(out_path, encoding="utf-8")) if out_path.exists() else {}
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
        docs = (await db.execute(text(
            "SELECT DISTINCT ON (sha256) id, filename FROM documents "
            "WHERE kb_id=:kb AND index_status='indexed' AND deleted_at IS NULL "
            "ORDER BY sha256, created_at DESC"), {"kb": KB})).fetchall()
        unique = [{"id": str(r.id), "name": r.filename} for r in docs]
        unique = [d for d in unique if d["id"] not in existing]
        if args.offset: unique = unique[args.offset:]
        if args.limit: unique = unique[:args.limit]
        print(f"待跑文档: {len(unique)}", flush=True)

        n = 0
        for doc in unique:
            did = doc["id"]
            chunks = await _load_chunks(db, did)
            tbl = [c for c in chunks if c["has_table"]]
            entries = []
            for t in targets:
                all_terms = []
                for qs in t.query_sources or []:
                    if not qs.get("in_query", False): continue
                    tb = qs.get("term_base_id")
                    if not tb: continue
                    rr = await category_builder.load_term_base(db, KB, uuid.UUID(str(tb)))
                    gf = (qs.get("group_field") or "").strip()
                    if gf:
                        from app.services.extraction.term_base_loader import _read
                        rr = [r for r in rr if str(_read(r, gf) or "").strip() == t.feature]
                    if not rr: continue
                    from app.services.extraction.term_base_loader import distinct_field_values
                    all_terms.extend(distinct_field_values(rr, qs.get("value_field") or "term_name", int(qs.get("query_main_limit") or 30)))
                all_terms = list(dict.fromkeys(all_terms))
                gold_terms = [w for w in all_terms if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for c in chunks)]
                gold_tbl = [c["chunk_id"] for c in tbl if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for w in gold_terms)]
                # 也接受语义证据候选（字面为0但可能为真实内容）——用一个宽松语义来标注
                if not gold_tbl:
                    # 语义兜底判断（复用证据函数,阈值0.60&表格）; 修复: 无 chunk_id 则跳过,不标假目标
                    sem_ev = await category_builder_v2._semantic_evidence_hit(
                        db, KB, did, " ".join([t.feature or "", *all_terms]).strip()[:2000], threshold=0.60,
                    )
                    if sem_ev.get("hit") and sem_ev.get("chunk_id"):
                        gold_tbl = [sem_ev["chunk_id"]]
                if not gold_tbl:
                    continue
                out = {"feature": t.feature, "n_tbl_targets": len(gold_tbl)}
                # V1
                b1, sk1 = await category_builder.build_one(cfg, db, kb_id=KB, document_id=did, target=copy.deepcopy(t))
                # V2L (语义证据关闭)
                off = {**category_builder_v2.LARGE_CANDIDATES}
                off_r = (cfg.global_config.get('retrieval') or {}).get('reranker') or {}
                off_r2 = dict(off_r); off_r2['semantic_evidence_enabled'] = False
                off['reranker'] = off_r2
                b2, sk2 = await category_builder_v2.build_one_v2(cfg, db, kb_id=KB, document_id=did, target=copy.deepcopy(t), retrieval_override=off)
                # V3 = V2L + 语义证据开启
                on = {**category_builder_v2.LARGE_CANDIDATES}
                on_r = dict(off_r); on_r['semantic_evidence_enabled'] = True; on_r['threshold'] = -5.0
                on['reranker'] = on_r
                b3, sk3 = await category_builder_v2.build_one_v2(cfg, db, kb_id=KB, document_id=did, target=copy.deepcopy(t), retrieval_override=on)
                for tag, built, sk in (("V1", b1, sk1), ("V2L", b2, sk2), ("V3", b3, sk3)):
                    if built is None:
                        out[tag] = {"recall": 0.0, "skipped": True, "reason": (sk.reason if sk else "")[:150], "hits": 0}
                    else:
                        ids = {h["chunk_id"] for h in built.hits}
                        rec = [cid for cid in gold_tbl if cid in ids]
                        out[tag] = {"recall": round(len(rec)/len(gold_tbl), 3), "recalled": len(rec), "hits": len(built.hits), "skipped": False}
                entries.append(out)
                print(f"  {t.feature:<10} tbl={len(gold_tbl):>2} V1={out['V1']['recall']:.2f} V2L={out['V2L']['recall']:.2f} V3={out['V3']['recall']:.2f} skip(V1/V2L/V3)={out['V1']['skipped']}/{out['V2L']['skipped']}/{out['V3']['skipped']}", flush=True)
            existing[did] = {"name": doc["name"], "categories": entries}
            n += 1
            out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"文档 {n} 完成: {doc['name'][:45]}", flush=True)
        print(f"\n完成: {n} 文档", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
