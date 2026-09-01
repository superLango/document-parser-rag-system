"""语义证据 vs 字面证据 全量对比测试（全部已索引文档）。

对每个文档 × 每个展开类别：
  - 字面证据：术语(符号词元/中文子串)在文档中的命中数 hit_terms、命中表格块数 literal_tbl
  - 语义证据：类别 query(BGE-M3) 对文档全部块 content_vector 的最大余弦 sem_max_sim、
    sem_top_table(是否表格块)、sem_top_chunk
输出 JSON：每实例 {doc, feature, hit_terms, literal_tbl, sem_max_sim, sem_top_table, ...}
供阈值扫描与方案对比（寻找字面漏检但语义命中的"碳vs C"场景）。
"""

import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.extraction import category_builder, category_builder_v2, extraction_resolver
from app.services.extraction.term_base_loader import _read, distinct_field_values, load_term_base
from app.services.embedding.embedding_service import embedding_service
from app.services.indexing.bm25 import tokenize_text

KB = uuid.UUID("25e7d8ef-6268-42d7-ba0c-62516ffc93f9")
RESULTS = Path("/home/grainuser/hansonDoc_RAG/qa/evaluation/results/semantic_evidence")


def _hit(term: str, text: str) -> bool:
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*", term):
        return term in tokenize_text(text)
    return term in text


async def main():
    db = AsyncSessionLocal()
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        cfg = await extraction_resolver.resolve(db, KB)
        targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)

        # 全部已索引文档（按 sha256 去重取最新）
        docs = (await db.execute(text(
            "SELECT DISTINCT ON (sha256) id, filename, sha256 FROM documents "
            "WHERE kb_id=:kb AND index_status='indexed' AND deleted_at IS NULL "
            "ORDER BY sha256, created_at DESC"
        ), {"kb": KB})).fetchall()
        print(f"唯一已索引文档: {len(docs)}", flush=True)

        # 预构建类别 query（batch embed 一次，与文档无关）
        qlist, qmeta = [], []
        for t in targets:
            # 用「特征名 + 术语集全量」作为语义 query（不依赖具体文档，
            # 与文档感知专用 query 的语义等价：文档感知只做子集选择，词表不变）
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
            q = " ".join([t.feature or "", *list(dict.fromkeys(all_terms))]).strip()[:2000]
            qlist.append(q)
            qmeta.append({"feature": t.feature, "query": q})
        qvecs = await embedding_service.embed(qlist)
        print(f"类别 query 编码完成: {len(qmeta)}", flush=True)

        all_data = []
        for di, doc in enumerate(docs):
            did = str(doc.id)
            rows = (await db.execute(text(
                "SELECT chunk_id, content, content_for_embedding, has_table, content_vector "
                "FROM document_chunks WHERE document_id=:d AND deleted_at IS NULL AND content_vector IS NOT NULL"
            ), {"d": did})).fetchall()
            if not rows:
                continue
            # 向量矩阵（DB 返回 pgvector 字符串 "[...]"）
            def _parse_vec(s):
                if isinstance(s, (bytes, bytearray)):
                    return np.frombuffer(s, dtype=np.float32)
                return np.array([float(x) for x in s.strip("[]").split(",")], dtype=np.float32)
            mat = np.array([_parse_vec(r.content_vector) for r in rows])
            has_tbl = np.array([bool(r.has_table) for r in rows])
            chunk_ids = [r.chunk_id for r in rows]
            content_txt = [((r.content or "") + " " + (r.content_for_embedding or "")) for r in rows]

            for t, qv, qm in zip(targets, qvecs, qmeta):
                # 字面证据
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
                terms = list(dict.fromkeys(all_terms))
                hit_terms = [w for w in terms if any(_hit(w, c) for c in content_txt)]
                lit_tbl = sum(
                    1 for idx in range(len(rows))
                    if rows[idx].has_table and any(_hit(w, content_txt[idx]) for w in terms)
                )
                # 语义证据（content_vector 已 L2 归一化，点积即余弦）
                sims = mat.dot(qv)
                top_idx = int(np.argmax(sims))
                sem_max = float(sims[top_idx])
                all_data.append({
                    "doc": did, "name": doc.filename[:80], "feature": t.feature,
                    "hit_terms": len(hit_terms), "literal_tbl": int(lit_tbl),
                    "sem_max_sim": round(sem_max, 4),
                    "sem_top_table": bool(has_tbl[top_idx]),
                    "sem_top_chunk": chunk_ids[top_idx],
                })
            if di % 10 == 0:
                print(f"  doc {di}/{len(docs)} done", flush=True)

        (RESULTS / "evidence_all.json").write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完成: {len(all_data)} 实例 -> {RESULTS/'evidence_all.json'}", flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
