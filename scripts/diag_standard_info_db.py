"""纯 DB 诊断：GB1220 标准信息相关内容在哪些 chunk（不加载模型/不检索）。

用法：
    cd /home/grainuser/hansonDoc_RAG/backend
    .venv/bin/python ../scripts/diag_standard_info_db.py
"""
import asyncio
import re
import asyncpg

KB = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
DOC = "09a79bb1-1c17-44bc-bb02-57eab2e25580"


def page_no(sp):
    m = re.search(r"\d+", str(sp))
    return int(m.group()) if m else 0


async def main():
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
    rows = await conn.fetch("""
        SELECT chunk_id, source_pages, has_table, length(content) AS clen, content
        FROM document_chunks
        WHERE kb_id=$1 AND document_id=$2 AND deleted_at IS NULL
        ORDER BY source_pages
    """, KB, DOC)
    print(f"总 chunk: {len(rows)}")
    # 含标准信息关键内容
    keys = ["GB/T 1220", "中华人民共和国国家标准", "代替 GB/T", "不锈钢棒", "发布", "实施", "ICS"]
    print("\n=== 含标准信息关键内容的 chunk ===")
    for r in rows:
        c = r["content"] or ""
        hit = [k for k in keys if k in c]
        if hit:
            p = page_no(r["source_pages"])
            print(f"p{p} has_table={r['has_table']} {r['clen']}字符 | 命中{hit} | {c[:100]!r}")
    # 前几页（封面/前言区域）全部块
    print("\n=== 前 6 页所有块 ===")
    for r in rows:
        p = page_no(r["source_pages"])
        if p <= 6:
            c = (r["content"] or "")[:120].replace("\n", " ")
            print(f"  p{p} has_table={r['has_table']} {r['clen']}字符 | {c!r}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
