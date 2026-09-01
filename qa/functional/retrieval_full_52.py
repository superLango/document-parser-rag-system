"""全量 50+ 文档 V1 vs V2L 召回诊断（断点续跑，仅检索不抽取）。

用法: .venv/bin/python qa/functional/retrieval_full_52.py [--limit N] [--offset M]
输出: qa/evaluation/results/retrieval_full/recall_v1_v2l.json
每类输出 V1/V2L recall + hits + skipped reason。
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
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_full")


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()

    db = AsyncSessionLocal()
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        out_path = RESULTS / "recall_v1_v2l.json"
        existing = {}
        if out_path.exists():
            existing = json.load(open(out_path, encoding="utf-8"))
            print(f"已存在 {len(existing)} 个文档结果，将续跑", flush=True)

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
        all_docs = [{"id": str(r.id), "name": r.filename} for r in docs]
        # 去重文件名，优先未完成的
        seen = set()
        unique_docs = []
        for d in all_docs:
            if d["name"] in seen:
                continue
            seen.add(d["name"])
            unique_docs.append(d)
        unique_docs = [d for d in unique_docs if d["id"] not in existing]
        if args.offset:
            unique_docs = unique_docs[args.offset:]
        if args.limit:
            unique_docs = unique_docs[: args.limit]
        print(f"待跑文档: {len(unique_docs)} (唯一文件名去重后)", flush=True)

        n_done = 0
        for doc in unique_docs:
            doc_id = doc["id"]
            chunks = await _load_chunks(db, doc_id)
            tbl = [c for c in chunks if c["has_table"]]
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
                    all_terms.extend(distinct_field_values(rows, field, int(qs.get("query_main_limit") or 30)))
                all_terms = list(dict.fromkeys(all_terms))
                gold_terms = [w for w in all_terms if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for c in chunks)]
                gold_tbl = [c["chunk_id"] for c in tbl if any(_term_in_text(w, c["content"]) or _term_in_text(w, c["embed"]) for w in gold_terms)]
                if not gold_tbl:
                    continue

                out = {"feature": t.feature, "n_gold_terms": len(gold_terms), "n_tbl_targets": len(gold_tbl)}
                for tag, target, override in (
                    ("V1", copy.deepcopy(t), None),
                    ("V2L", copy.deepcopy(t), category_builder_v2.LARGE_CANDIDATES),
                ):
                    t0 = time.monotonic()
                    if tag == "V1":
                        built, sk = await category_builder.build_one(cfg, db, kb_id=KB, document_id=doc_id, target=target)
                    else:
                        built, sk = await category_builder_v2.build_one_v2(
                            cfg, db, kb_id=KB, document_id=doc_id, target=target,
                            retrieval_override=override,
                        )
                    if built is None:
                        out[tag] = {"recall": 0.0, "skipped": True, "reason": (sk.reason if sk else None)[:200], "hits": 0}
                    else:
                        ids = {h["chunk_id"] for h in built.hits}
                        recalled = [cid for cid in gold_tbl if cid in ids]
                        out[tag] = {
                            "recall": round(len(recalled) / len(gold_tbl), 3),
                            "recalled": len(recalled),
                            "hits": len(built.hits),
                            "skipped": False,
                        }
                entries.append(out)
                print(
                    f"  {t.feature:<10} tbl={len(gold_tbl):>2} V1={out['V1']['recall']:.2f} V2L={out['V2L']['recall']:.2f} "
                    f"hits={out['V1']['hits']}/{out['V2L']['hits']}",
                    flush=True,
                )
            existing[doc_id] = {"name": doc["name"], "categories": entries}
            n_done += 1
            (out_path).write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"文档 {n_done}/{len(unique_docs)} 完成并写入 {doc['name'][:50]}", flush=True)

        print(f"\n完成: 新增 {n_done} 个文档", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
