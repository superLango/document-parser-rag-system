"""证据剔除验证:对 52 文档 × 全部展开类别统计术语命中与目标块关系。

- hit_terms: 该类别术语(词元/子串)在文档中出现的数量(==V2 文档感知匹配逻辑)
- n_gold_tbl: 含该类别术语的表格块数(内容是否存在的直接证据)
核心问题: hit_terms==0 的实例是否真的没有目标内容?(证据剔除的精确性)
"""

import asyncio
import json
import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.extraction import category_builder, extraction_resolver
from app.services.extraction.term_base_loader import _read, distinct_field_values, load_term_base
from app.services.indexing.bm25 import tokenize_text

KB = uuid.UUID("25e7d8ef-6268-42d7-ba0c-62516ffc93f9")


def _hit(term: str, text: str) -> bool:
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*", term):
        return term in tokenize_text(text)
    return term in text


async def main():
    db = AsyncSessionLocal()
    try:
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
        docs = (await db.execute(text(
            "SELECT id FROM documents WHERE kb_id=:kb AND index_status='indexed' AND deleted_at IS NULL"
        ), {"kb": KB})).fetchall()
        # 只统计 recall_v1_v2l.json 覆盖的 52 文档
        covered = set(json.load(open("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/retrieval_full/recall_v1_v2l.json", encoding="utf-8")).keys())
        docs = [r for r in docs if str(r.id) in covered]
        print(f"文档数: {len(docs)}", flush=True)

        stat = defaultdict(int)  # (hit==0?, gold_tbl==0?) -> count
        per_feat = defaultdict(lambda: {"n": 0, "hit0": 0, "hit0_but_gold": 0})
        examples = []
        for doc in docs:
            did = str(doc.id)
            rows = (await db.execute(text(
                "SELECT content, content_for_embedding, has_table, chunk_id FROM document_chunks "
                "WHERE document_id=:d AND deleted_at IS NULL"), {"d": did})).fetchall()
            chunks = [{"content": r.content or "", "embed": r.content_for_embedding or "", "has_table": bool(r.has_table), "chunk_id": r.chunk_id} for r in rows]
            full = "\n".join(c["content"] for c in chunks) + "\n" + "\n".join(c["embed"] for c in chunks)
            tbl = [c for c in chunks if c["has_table"]]
            for t in targets:
                all_terms = []
                for qs in t.query_sources or []:
                    if not qs.get("in_query", False):
                        continue
                    tb_id = qs.get("term_base_id")
                    if not tb_id:
                        continue
                    rr = await load_term_base(db, KB, uuid.UUID(str(tb_id)))
                    gf = (qs.get("group_field") or "").strip()
                    if gf:
                        rr = [r for r in rr if str(_read(r, gf) or "").strip() == t.feature]
                    all_terms.extend(distinct_field_values(rr, qs.get("value_field") or "term_name", int(qs.get("query_main_limit") or 30)))
                terms = list(dict.fromkeys(all_terms))
                hit_terms = [w for w in terms if _hit(w, full)]
                gold_tbl = [c["chunk_id"] for c in tbl if any(_hit(w, c["content"]) or _hit(w, c["embed"]) for w in hit_terms)]
                key = (len(hit_terms) == 0, len(gold_tbl) == 0)
                stat[key] += 1
                pf = per_feat[t.feature]
                pf["n"] += 1
                if len(hit_terms) == 0:
                    pf["hit0"] += 1
                    if len(gold_tbl) > 0:
                        pf["hit0_but_gold"] += 1
                        if len(examples) < 8:
                            examples.append((did[:8], t.feature))
            print(f"  doc {did[:8]} done", flush=True)

        print("\n=== 矩阵(hit_terms==0, gold_tbl==0) 计数 ===")
        for k, v in sorted(stat.items()):
            print(f"  术语命中0={k[0]}, 目标块空={k[1]}: {v}")
        total = sum(stat.values())
        ok = stat[(True, True)] + stat[(False, False)]
        print(f"证据剔除可正确判定的比例: {ok}/{total} = {ok/total:.3f}")
        print(f"  判定为'无内容'的实例: {stat[(True, True)]} (其中可能误判的: {stat[(True, False)]})")
        print(f"  判定为'有内容'的实例: {stat[(False, False)]} (其中应被剔除却漏掉/弱内容: {stat[(False, True)]})")
        print("\n=== 每类别 hit0 统计 ===")
        for f, v in sorted(per_feat.items(), key=lambda x: -x[1]["hit0"]):
            if v["hit0"] > 0:
                print(f"  {f:<10} n={v['n']:>3} hit0={v['hit0']:>3} hit0_but_gold={v['hit0_but_gold']:>3}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
