"""对 retrieval_full 中被跳过的实例做阈值修正(-2.0)补充测试。

读 recall_v1_v2l.json 中 V2L skipped=True 的实例，用 V2L+threshold=-2.0 重跑。
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
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_full")


def _term_in_text(term: str, text: str) -> bool:
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*", term):
        return term in tokenize_text(text)
    return term in text


async def _load_chunks(db, doc_id):
    rows = (await db.execute(text(
        "SELECT chunk_id, content, content_for_embedding, has_table FROM document_chunks "
        "WHERE document_id=:d AND deleted_at IS NULL"), {"d": doc_id})).fetchall()
    return [{"chunk_id": r.chunk_id, "content": r.content or "", "embed": r.content_for_embedding or "", "has_table": bool(r.has_table)} for r in rows]


async def main():
    db = AsyncSessionLocal()
    try:
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
        by_feat = {t.feature: t for t in targets}
        base = json.load(open(RESULTS / "recall_v1_v2l.json", encoding="utf-8"))
        base_reranker = (cfg.global_config.get("retrieval") or {}).get("reranker") or {}
        override = {**category_builder_v2.LARGE_CANDIDATES, "reranker": {**base_reranker, "threshold": -2.0}}

        out = []
        n = 0
        for doc_id, d in base.items():
            for c in d["categories"]:
                if not c.get("V2L", {}).get("skipped"):
                    continue
                feat = c["feature"]
                t0 = by_feat.get(feat)
                if t0 is None:
                    continue
                chunks = await _load_chunks(db, doc_id)
                tbl = [x for x in chunks if x["has_table"]]
                gold_terms = c.get("n_gold_terms") or []
                # 用全部术语判定 gold_tbl
                all_terms = []
                for qs in t0.query_sources or []:
                    if not qs.get("in_query", False):
                        continue
                    tb = qs.get("term_base_id")
                    if not tb:
                        continue
                    rows = await category_builder.load_term_base(db, KB, uuid.UUID(str(tb)))
                    gf = (qs.get("group_field") or "").strip()
                    if gf:
                        from app.services.extraction.term_base_loader import _read
                        rows = [r for r in rows if str(_read(r, gf) or "").strip() == t0.feature]
                    if not rows:
                        continue
                    field = qs.get("value_field") or "term_name"
                    from app.services.extraction.term_base_loader import distinct_field_values
                    all_terms.extend(distinct_field_values(rows, field, int(qs.get("query_main_limit") or 30)))
                gold_terms = [w for w in set(all_terms) if any(_term_in_text(w, x["content"]) or _term_in_text(w, x["embed"]) for x in chunks)]
                gold_tbl = [x["chunk_id"] for x in tbl if any(_term_in_text(w, x["content"]) or _term_in_text(w, x["embed"]) for w in gold_terms)]
                if not gold_tbl:
                    continue
                built, sk = await category_builder_v2.build_one_v2(
                    cfg, db, kb_id=KB, document_id=doc_id, target=copy.deepcopy(t0),
                    retrieval_override=override,
                )
                n += 1
                if built is None:
                    print(f"  仍跳过 {feat} ({doc_id[:8]}): {sk.reason[:80]}", flush=True)
                    continue
                ids = {h["chunk_id"] for h in built.hits}
                recalled = [cid for cid in gold_tbl if cid in ids]
                ratio = round(len(recalled) / len(gold_tbl), 3)
                print(f"  [找回] {d['name'][:35]:<35} {feat:<10} tbl={len(gold_tbl)} recall={ratio}", flush=True)
                out.append({"doc_id": doc_id, "feature": feat, "recall": ratio})
        print(f"\n找回: {len(out)}", flush=True)
        (RESULTS / "threshold_fix_full.json").write_text(json.dumps({"recovered": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
