"""小实验：V2-L + 阈值修正（reranker.threshold=0.0 -> -2.0）找回被误剔类别。

仅跑 recall_three_route.json 中被跳过的类别实例（V1/V2L 均 skip=True），
对比 threshold=0.0（现状）与 -2.0（修正）的召回差异。
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
                "SELECT chunk_id, content, content_for_embedding, has_table FROM document_chunks "
                "WHERE document_id=:d AND deleted_at IS NULL"
            ),
            {"d": doc_id},
        )
    ).fetchall()
    return [{
        "chunk_id": r.chunk_id, "content": r.content or "",
        "embed": r.content_for_embedding or "", "has_table": bool(r.has_table),
    } for r in rows]


async def main():
    db = AsyncSessionLocal()
    try:
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
        by_feat = {t.feature: t for t in targets}

        # 找被跳过的实例 (doc_id, feature)
        base = json.load(open(RESULTS / "recall_three_route.json"))
        skip_instances = []
        for doc_id, d in base.items():
            for c in d["categories"]:
                if c.get("V1", {}).get("skipped") or c.get("V2L", {}).get("skipped"):
                    skip_instances.append((doc_id, c["feature"]))
        print(f"跳过实例数: {len(skip_instances)}", flush=True)

        n_recovered = 0
        n_recall = 0
        out = []
        for doc_id, feat in skip_instances:
            chunks = await _load_chunks(db, doc_id)
            tbl = [c for c in chunks if c["has_table"]]
            t0 = by_feat.get(feat)
            if t0 is None:
                continue
            # gold
            all_terms = []
            for qs in t0.query_sources or []:
                if not qs.get("in_query", False):
                    continue
                tb_id = qs.get("term_base_id")
                if not tb_id:
                    continue
                rows = await category_builder.load_term_base(db, KB, uuid.UUID(str(tb_id)))
                gf = (qs.get("group_field") or "").strip()
                if gf:
                    from app.services.extraction.term_base_loader import _read
                    rows = [r for r in rows if str(_read(r, gf) or "").strip() == t0.feature]
                field = qs.get("value_field") or "term_name"
                from app.services.extraction.term_base_loader import distinct_field_values
                all_terms.extend(distinct_field_values(rows, field, int(qs.get("query_main_limit") or 30)))
            gold_terms = [w for w in set(all_terms) if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for c in chunks)]
            gold_tbl = [c["chunk_id"] for c in tbl if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for w in gold_terms)]

            # 修正阈值:读取全局 reranker 配置,threshold -> -2.0
            base_reranker = (cfg.global_config.get("retrieval") or {}).get("reranker") or {}
            override = {**category_builder_v2.LARGE_CANDIDATES}
            override["reranker"] = {**base_reranker, "threshold": -2.0}

            built, sk = await category_builder_v2.build_one_v2(
                cfg, db, kb_id=KB, document_id=doc_id,
                target=copy.deepcopy(t0), retrieval_override=override,
            )
            if built is None:
                print(f"  仍跳过 {feat} ({doc_id[:8]}): {sk.reason}", flush=True)
                continue
            ids = {h["chunk_id"] for h in built.hits}
            recalled = [cid for cid in gold_tbl if cid in ids]
            ratio = round(len(recalled) / len(gold_tbl), 3)
            n_recovered += 1
            n_recall += ratio
            print(f"  [找回] {feat} ({doc_id[:8]}) tbl={len(gold_tbl)} recall={ratio} hits={len(built.hits)}", flush=True)
            out.append({"doc_id": doc_id, "feature": feat, "recall": ratio, "hits": len(built.hits)})

        print(f"\n找回类别: {n_recovered}/{len(skip_instances)}, 平均召回: {n_recall / max(1, n_recovered):.3f}", flush=True)
        (RESULTS / "threshold_fix_recovered.json").write_text(json.dumps({"recovered": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
