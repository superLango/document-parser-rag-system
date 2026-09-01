"""检索召回诊断 v2：验证「术语精简丢失」与多种 query 方案的召回差异（不触发抽取）。

对 KB=25e7d8ef 的已索引文档，逐文档逐类别：
  - gold_terms：术语集 NAME 中「实际出现在该文档」的术语（词元/子串匹配）
  - gold_tbl_chunks：包含任一 gold_terms 的表格块（目标块）
  - query 方案 A/B/C/E 分别检索，统计 Recall@k（目标表格块命中）与术语覆盖
  - 输出 query_refined 丢失 gold_terms 的统计（用户关注场景）
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
from app.services.extraction import category_builder, extraction_resolver
from app.services.indexing.bm25 import tokenize_text
from app.services.indexing.retrieval import SearchFilters, retrieval_service

KB = uuid.UUID("25e7d8ef-6268-42d7-ba0c-62516ffc93f9")
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_recall_diag")

RETRIEVAL_TOPK = 15
RERANK_ON = False  # 先测纯检索；后续再开重排对比


def _term_in_text(term: str, text: str) -> bool:
    """术语命中：纯 ASCII 词元用 tokenize 匹配（避免 C 匹配到 Cl），中文用子串。"""
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*", term):
        toks = tokenize_text(text)
        return term in toks
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
        rcfg = ((cfg.global_config or {}).get("retrieval") or {})
        print("retrieval 配置:", json.dumps(rcfg, ensure_ascii=False)[:600], flush=True)

        targets, skipped = await category_builder.build_targets(cfg, db, kb_id=KB)
        print(f"展开类别: {len(targets)} (skipped: {len(skipped)})", flush=True)

        docs = (
            await db.execute(
                text(
                    "SELECT id, filename FROM documents WHERE kb_id=:kb AND index_status='indexed' "
                    "AND deleted_at IS NULL ORDER BY filename"
                ),
                {"kb": KB},
            )
        ).fetchall()
        doc_ids = [r.id for r in docs]
        print(f"已索引文档: {len(docs)}", flush=True)

        all_results = {}
        for did in doc_ids:
            doc_name = next(r.filename for r in docs if r.id == did)
            chunks = await _load_chunks(db, str(did))
            tbl_chunks = [c for c in chunks if c["has_table"]]
            print(f"\n===== 文档: {doc_name} (doc={did}) chunks={len(chunks)} tbl={len(tbl_chunks)} =====", flush=True)

            entries = []
            for t in targets:
                # 全量术语集（in_query 的 query_sources）
                all_terms = []
                refined_terms = []
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
                    main_limit = int(qs.get("query_main_limit") or 30)
                    refined_limit = int(qs.get("query_refined_limit") or 8)
                    vals = distinct_field_values(rows, field, main_limit)
                    all_terms.extend(vals)
                    if qs.get("dedupe") and refined_limit > 0:
                        refined = await category_builder._build_refined_terms(
                            rows, field, refined_limit,
                            float(rcfg.get("query_embed", {}).get("dedupe_similarity_threshold") or 0.85),
                        )
                        refined_terms.extend(refined or vals)
                    else:
                        refined_terms.extend(vals)
                all_terms = list(dict.fromkeys(all_terms))
                refined_terms = list(dict.fromkeys(refined_terms))

                # gold：文档实际出现的术语（在 content 或 embed 中命中）
                gold_terms = [w for w in all_terms if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for c in chunks)]
                # 目标表格块：包含任一 gold 术语的表格块
                gold_tbl = [c["chunk_id"] for c in tbl_chunks if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for w in gold_terms)]

                if not gold_tbl:
                    continue

                # 方案 A：线上（refined 精简集）
                a_terms = refined_terms if refined_terms else all_terms
                q_a = " ".join([t.feature or "", *a_terms]).strip()[:2000]
                # 方案 B：全量术语集
                q_b = " ".join([t.feature or "", *all_terms]).strip()[:2000]
                # 方案 C：文档频率精选（_build_rerank_query 逻辑）
                q_c = await category_builder._build_rerank_query(cfg, db, KB, t)
                # 方案 E：gold 全覆盖（理想上界）
                q_e = " ".join([t.feature or "", *gold_terms]).strip()[:2000]

                row = {
                    "feature": t.feature,
                    "strategy": t.extraction_strategy,
                    "n_all_terms": len(all_terms),
                    "n_refined_terms": len(refined_terms),
                    "n_gold_terms": len(gold_terms),
                    "n_tbl_targets": len(gold_tbl),
                    "refined_gold_lost": len([w for w in gold_terms if w not in refined_terms]),
                    "gold_in_refined": len([w for w in gold_terms if w in refined_terms]),
                    "queries": {},
                }
                for tag, q in (("A_refined", q_a), ("B_full", q_b), ("C_docfreq", q_c), ("E_gold", q_e)):
                    if not q.strip():
                        continue
                    t0 = time.monotonic()
                    hits = await retrieval_service.search(
                        db, KB, q, top_k=RETRIEVAL_TOPK,
                        filters=SearchFilters(document_id=did),
                        retrieval_config=rcfg,
                    )
                    dt = time.monotonic() - t0
                    hit_ids = {h.chunk_id for h in hits}
                    recalled = [cid for cid in gold_tbl if cid in hit_ids]
                    row["queries"][tag] = {
                        "qlen": len(q),
                        "n_terms": len(q.split()),
                        "recall": round(len(recalled) / len(gold_tbl), 3),
                        "recalled": len(recalled),
                        "tbl_in_hits": sum(1 for h in hits if getattr(h, "has_table", False)),
                        "first_target_rank": next((i + 1 for i, h in enumerate(hits) if h.chunk_id in set(gold_tbl)), None),
                        "sec": round(dt, 2),
                    }
                entries.append(row)
                flag = "LOST" if row["refined_gold_lost"] > 0 else "ok"
                print(f"  {t.feature:<10} all={row['n_all_terms']:>3} refined={row['n_refined_terms']:>2} "
                      f"gold={row['n_gold_terms']:>3} tbl={row['n_tbl_targets']:>2} lost_gold={row['refined_gold_lost']:>2} [{flag}] "
                      + " ".join(f"{k}:r={v['recall']:.2f}" for k, v in row["queries"].items()), flush=True)
            all_results[str(did)] = {"name": doc_name, "categories": entries}

        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "recall_diag.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n结果写入:", RESULTS / "recall_diag.json", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
