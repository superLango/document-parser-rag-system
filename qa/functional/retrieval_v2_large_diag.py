"""V1 vs V2(默认) vs V2-L(候选放大) 三路线检索对比（不触发抽取）。

候选放大（V2-L，LARGE_CANDIDATES）：
  top_k 15→40, candidate_mult 2→4, category_recall.top_k 8→25,
  per_dim_top_k 10→40, data_route_top_k 10→40, meta_route_top_k 5→20,
  context_top_k 30→60。128k 上下文，候选宽度只受文档块数自然约束。
"""

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
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_v2_large")


def _term_in_text(term: str, text: str) -> bool:
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*", term):
        return term in tokenize_text(text)
    return term in text


async def _load_chunks(db: AsyncSession, doc_id: str) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT chunk_id, content, content_for_embedding, has_table, source_pages "
                "FROM document_chunks WHERE document_id=:d AND deleted_at IS NULL"
            ),
            {"d": doc_id},
        )
    ).fetchall()
    chunks = []
    for r in rows:
        chunks.append({
            "chunk_id": r.chunk_id,
            "content": r.content or "",
            "embed": r.content_for_embedding or "",
            "has_table": bool(r.has_table),
        })
    return chunks


async def main():
    db = AsyncSessionLocal()
    try:
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
        docs = (
            await db.execute(
                text(
                    "SELECT id, filename FROM documents WHERE kb_id=:kb AND index_status='indexed' "
                    "AND deleted_at IS NULL ORDER BY filename"
                ),
                {"kb": KB},
            )
        ).fetchall()
        print(f"类别 {len(targets)} / 文档 {len(docs)}", flush=True)

        all_results = {}
        for did in docs:
            doc_id = str(did.id)
            chunks = await _load_chunks(db, doc_id)
            tbl_chunks = [c for c in chunks if c["has_table"]]
            print(f"\n===== {did.filename} ({doc_id}) chunks={len(chunks)} tbl={len(tbl_chunks)} =====", flush=True)
            entries = []
            for t in targets:
                all_terms = []
                for qs in t.query_sources or []:
                    if not qs.get("in_query", False):
                        continue
                    tb_id = qs.get("term_base_id")
                    if not tb_id:
                        continue
                    rows = await category_builder.load_term_base(db, KB, uuid.UUID(str(tb_id)))
                    gf = (qs.get("group_field") or "").strip()
                    if gf:
                        from app.services.extraction.term_base_loader import _read
                        rows = [r for r in rows if str(_read(r, gf) or "").strip() == t.feature]
                    field = qs.get("value_field") or "term_name"
                    from app.services.extraction.term_base_loader import distinct_field_values
                    vals = distinct_field_values(rows, field, int(qs.get("query_main_limit") or 30))
                    all_terms.extend(vals)
                all_terms = list(dict.fromkeys(all_terms))
                gold_terms = [w for w in all_terms if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for c in chunks)]
                gold_tbl = [c["chunk_id"] for c in tbl_chunks if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for w in gold_terms)]
                if not gold_tbl:
                    continue

                t1 = copy.deepcopy(t); t2 = copy.deepcopy(t); t3 = copy.deepcopy(t)
                out = {"feature": t.feature, "n_gold_terms": len(gold_terms), "n_tbl_targets": len(gold_tbl)}
                for tag, target, override in (
                    ("V1", t1, None),
                    ("V2", t2, None),
                    ("V2L", t3, category_builder_v2.LARGE_CANDIDATES),
                ):
                    t0 = time.monotonic()
                    if tag == "V1":
                        built, sk = await category_builder.build_one(cfg, db, kb_id=KB, document_id=doc_id, target=target)
                    else:
                        built, sk = await category_builder_v2.build_one_v2(
                            cfg, db, kb_id=KB, document_id=doc_id, target=target,
                            retrieval_override=override,
                        )
                    sec = time.monotonic() - t0
                    if built is None:
                        out[tag] = {"recall": 0.0, "skipped": True, "reason": sk.reason if sk else None, "sec": round(sec, 2)}
                    else:
                        ids = {h["chunk_id"] for h in built.hits}
                        recalled = [cid for cid in gold_tbl if cid in ids]
                        out[tag] = {
                            "recall": round(len(recalled) / len(gold_tbl), 3),
                            "recalled": len(recalled),
                            "hits": len(built.hits),
                            "skipped": False,
                            "sec": round(sec, 2),
                        }
                print(
                    f"  {t.feature:<10} tbl={len(gold_tbl):>2} "
                    f"V1={out['V1']['recall']:.2f} V2={out['V2']['recall']:.2f} V2L={out['V2L']['recall']:.2f} "
                    f"(hits V1={out['V1']['hits'] if not out['V1']['skipped'] else 0}"
                    f"/V2={out['V2']['hits'] if not out['V2']['skipped'] else 0}"
                    f"/V2L={out['V2L']['hits'] if not out['V2L']['skipped'] else 0})",
                    flush=True,
                )
                entries.append(out)
            all_results[doc_id] = {"name": did.filename, "categories": entries}

        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "recall_three_route.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n结果:", RESULTS / "recall_three_route.json", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
