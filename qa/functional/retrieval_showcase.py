"""展示脚本: 对选定文档, 输出全部类别的保留/剔除判定明细。

判定(用户确认口径):
  - 字面命中(任意块) > 0  -> 保留(文档中出现了该类型的词)
  - 否则 语义证据命中(≥0.60 且表格块) -> 保留
  - 两者皆无 -> 剔除
输出每类: features | hit_any(任意块) | hit_tbl(表格块) | sem_max | sem_hit | 保留/剔除
"""

import asyncio
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.extraction import category_builder, extraction_resolver
from app.services.extraction.term_base_loader import _read, distinct_field_values, load_term_base
from app.services.indexing.bm25 import tokenize_text

KB = uuid.UUID("25e7d8ef-6268-42d7-ba0c-62516ffc93f9")
DOC_IDS = [
    "09a79bb1-1c17-44bc-bb02-57eab2e25580",   # GB-T1220-2007 不锈钢棒.pdf (含化学成分/力学性能表)
    "dd41b52e-fcf7-419e-bfee-e42f557fdc49",   # JBT7030-2014.pdf (含持久性能表)
    "b5d0a8f0-0795-4104-a0c8-79c1eeb49a0a",   # DFHM-QCD-0706-000885.pdf (锻件规范,无持久)
]


def _hit(term: str, text: str):
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
        # 预建每类术语(与文档无关)
        term_map = {}
        for t in targets:
            all_terms = []
            for qs in t.query_sources or []:
                if not qs.get("in_query", False):
                    continue
                tb = qs.get("term_base_id")
                if not tb:
                    continue
                rr = await load_term_base(db, KB, uuid.UUID(str(tb)))
                gf = (qs.get("group_field") or "").strip()
                if gf:
                    rr = [r for r in rr if str(_read(r, gf) or "").strip() == t.feature]
                all_terms.extend(distinct_field_values(rr, qs.get("value_field") or "term_name", int(qs.get("query_main_limit") or 30)))
            term_map[t.feature] = list(dict.fromkeys(all_terms))
        # 类别 query 一次编码
        from app.services.embedding.embedding_service import embedding_service
        from app.services.extraction import category_builder_v2
        qlist = []
        for f in term_map:
            q = " ".join([f, *term_map[f]]).strip()[:2000]
            qlist.append(q)
        qvecs = await embedding_service.embed(qlist)

        for did in DOC_IDS:
            r = await db.execute(text(
                "SELECT filename FROM documents WHERE kb_id=:kb AND id=:d AND deleted_at IS NULL"
            ), {"kb": KB, "d": did})
            row = r.fetchone()
            if not row:
                print(f"\n未找到文档: {did}")
                continue
            fname_real = row[0]
            chunks = (await db.execute(text(
                "SELECT content, content_for_embedding, has_table FROM document_chunks WHERE document_id=:d AND deleted_at IS NULL"
            ), {"d": did})).fetchall()
            full_texts = [((c.content or "") + " " + (c.content_for_embedding or "")) for c in chunks]
            full = "\n".join(full_texts)
            tbl_texts = [t for t, c in zip(full_texts, chunks) if c.has_table]

            print(f"\n{'='*90}\n文档: {fname_real} (doc={did})\n{'='*90}")
            print(f"{'类别':<10} {'字面任意':>6} {'字面表格':>6} {'语义max':>8} {'语义命中':>6}  判定")
            for i, t in enumerate(targets):
                f = t.feature
                terms = term_map[f]
                hit_any = any(_hit(w, full) for w in terms)
                hit_tbl = any(_hit(w, " ".join(tbl_texts)) if tbl_texts else False for w in terms)

                # 用 _semantic_evidence_hit 拿语义证据
                from app.services.extraction import category_builder_v2
                ev = await category_builder_v2._semantic_evidence_hit(db, KB, did, " ".join([f, *terms]).strip()[:2000], threshold=0.60)
                # 生产口径: 字面任意 OR 语义≥0.60(不强制表格); always 无条件保留
                if t.extraction_strategy == "always":
                    verdict = "保留"; reason = ["always无条件"]
                elif hit_any or ev.get("max_sim", 0) >= 0.60:
                    verdict = "保留"
                    reason = ["字面任意"] if hit_any else []
                    if ev.get("max_sim", 0) >= 0.60: reason.append("语义≥0.60")
                else:
                    verdict = "剔除"; reason = ["无证据"]
                print(f"{f:<10} {str(hit_any):>6} {str(hit_tbl):>6} {ev.get('max_sim', 0):>8.3f} {verdict}({'/'.join(reason) if reason else '无证据'})")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
