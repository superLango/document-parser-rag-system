"""V1 vs V2 检索路线对比诊断（不触发抽取）。

对 KB=25e7d8ef 全部 indexed 文档 × 展开类别：
  - V1 路线：category_builder.build_one（现状：术语集内部语义去重精简）
  - V2 路线：category_builder_v2.build_one_v2（新：文档感知术语精选）
  对比同一类别的 query 内容、gold 术语覆盖、目标表格块 Recall@15、
  类别跳过情况。输出 recall_v2_vs_v1.json。
"""

import asyncio
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
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_v2_vs_v1")
TOPK = 15


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
            "pages": r.source_pages if isinstance(r.source_pages, list) else (json.loads(r.source_pages) if r.source_pages else []),
        })
    return chunks


async def main():
    db = AsyncSessionLocal()
    try:
        cfg = await extraction_resolver.resolve(db, KB)
        targets, skipped = await category_builder.build_targets(cfg, db, kb_id=KB)
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
                # 全量术语（用于 gold 判定）
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

                # V1 路线
                t1_start = time.monotonic()
                built1, sk1 = await category_builder.build_one(
                    cfg, db, kb_id=KB, document_id=doc_id, target=t,
                )
                sec_v1 = time.monotonic() - t1_start
                # V2 路线（独立 target，深拷贝 t 的字段）
                import copy
                t2 = copy.deepcopy(t)
                t2_start = time.monotonic()
                built2, sk2 = await category_builder_v2.build_one_v2(
                    cfg, db, kb_id=KB, document_id=doc_id, target=t2,
                )
                sec_v2 = time.monotonic() - t2_start

                def _metrics(built):
                    if built is None:
                        return {"skipped": True, "recall": 0.0, "hit_ids": []}
                    ids = {h["chunk_id"] for h in built.hits}
                    recalled = [cid for cid in gold_tbl if cid in ids]
                    return {
                        "skipped": False,
                        "recall": round(len(recalled) / len(gold_tbl), 3),
                        "recalled": len(recalled),
                        "hits": len(built.hits),
                        "hit_score": round(built.hit_score or 0, 4),
                        "query_terms": built.query_terms if built.query_terms else [],
                        "hit_ids": sorted(ids),
                    }

                m1 = _metrics(built1)
                m2 = _metrics(built2)
                # V1 精简集的 lost_gold
                v1_terms = set(m1.get("query_terms") or [])
                lost_v1 = len([w for w in gold_terms if w not in v1_terms])
                v2_terms = set(m2.get("query_terms") or [])
                lost_v2 = len([w for w in gold_terms if w not in v2_terms])

                entries.append({
                    "feature": t.feature,
                    "strategy": t.extraction_strategy,
                    "n_gold_terms": len(gold_terms),
                    "n_tbl_targets": len(gold_tbl),
                    "v1": {**m1, "skipped_reason": sk1.reason if sk1 else None, "sec": round(sec_v1, 2), "lost_gold": lost_v1},
                    "v2": {**m2, "skipped_reason": sk2.reason if sk2 else None, "sec": round(sec_v2, 2), "lost_gold": lost_v2},
                })
                print(
                    f"  {t.feature:<10} tbl={len(gold_tbl):>2} "
                    f"V1: r={m1['recall']:.2f} lost={lost_v1:>2} skip={m1['skipped']} terms={m1.get('query_terms') or '-'[:0]}? ",
                    end="", flush=True,
                )
                print(
                    f"V2: r={m2['recall']:.2f} lost={lost_v2:>2} skip={m2['skipped']} "
                    f"q=({','.join(m2.get('query_terms') or [])})", flush=True,
                )
            all_results[doc_id] = {"name": did.filename, "categories": entries}

        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "recall_v2_vs_v1.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n结果:", RESULTS / "recall_v2_vs_v1.json", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
