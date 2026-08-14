"""test_doc 全链路验证：GJB3325A-2019 上传→解析→索引→抽取（9.5 演进）。

验证点：
1. 全局配置（召回模式/阈值/top_k）与 Schema 术语集配置（类别展开/Query 注入）是否生效；
2. 9.5 第二版：命中分数、剔除原因、阈值分布统计；
3. 9.5 第三版：strict 与 loose 模式对比。

用法：PYTHONPATH=backend:. backend/.venv/bin/python qa/functional/full_flow_gjb3325a.py
"""

import asyncio
import json
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
KB = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
PDF = Path(__file__).resolve().parents[2] / "test_doc" / "GJB3325A-2019.pdf"
DETECT_TB = "ab03135a-781f-40ff-a2d6-75c9c9941d47"  # 检测项目
CAT_PROJ = "10070867-86de-4cad-9949-dc998a3c331f"   # 项目大类(term_base 展开)
TEMPLATE = "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7"


async def login(client: httpx.AsyncClient) -> str:
    r = await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


async def set_global_config(client, h, mode: str) -> None:
    strict = mode == "strict"
    r = await client.put(f"/kb/{KB}/extraction-config/global", headers=h, json={
        "enabled": True,
        "content": {
            "retrieval": {
                "top_k": 6,
                "default_confidence_threshold": 0.9 if strict else 0.35,
                "category_recall": {"mode": mode, "top_k": 6, "per_dim_top_k": 12},
                # strict 演示：阈值 0.9 + 关闭词法兜底 → 低分类别被剔除
                "hybrid": {"keyword_min_hits": 999 if strict else 1},
            },
            "llm": {
                "engine": "BaseExtract",
                "engines": {
                    "BaseExtract": {
                        "timeout": 600,
                        "concurrency": {"max_concurrency": 8, "cross_category": 8, "within_category": 1},
                    }
                },
            },
        },
    })
    print(f"set global config mode={mode}: {r.status_code}")
    r.raise_for_status()


async def upload_and_parse(client, h) -> tuple[str, str]:
    # 复用已上传且已完成解析+索引的同名 test_doc（避免重复上传/解析）
    import asyncpg

    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/hanson_doc_rag")
    row = await conn.fetchrow(
        "SELECT id FROM documents WHERE kb_id=$1 AND filename=$2 AND deleted_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        KB, PDF.name,
    )
    await conn.close()
    if row:
        r = await client.get(f"/kb/{KB}/documents/{row['id']}", headers=h)
        d = r.json()["data"]
        if d.get("process_status") == "completed" and d.get("index_status") == "indexed":
            print(f"复用已解析文档: {row['id']}")
            return str(row["id"]), ""
    r = await client.post(
        f"/kb/{KB}/documents", headers=h,
        files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
    )
    print("upload:", r.status_code, r.text[:200])
    r.raise_for_status()
    data = r.json()["data"]
    doc_id = data["document"]["id"]
    task_id = data["task"]["task_id"]
    r = await client.post(f"/kb/{KB}/documents/{doc_id}/start", headers=h)
    print("parse start:", r.status_code)
    r.raise_for_status()
    last = None
    for _ in range(600):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/documents/{doc_id}", headers=h)
        d = r.json()["data"]
        line = f"parse: status={d.get('status')} process={d.get('process_status')} pages={d.get('page_count')}"
        if line != last:
            print(line, flush=True)
            last = line
        if d.get("process_status") in ("completed", "failed") or d.get("status") in ("completed", "failed"):
            break
    assert d.get("process_status") == "completed" or d.get("status") == "completed", f"解析未完成: {d}"
    return doc_id, task_id


async def wait_index(client, h, doc_id: str) -> None:
    last = None
    for _ in range(300):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/index/tasks?page=1&page_size=10", headers=h)
        items = r.json()["data"]["items"]
        mine = [i for i in items if i.get("document_id") == doc_id]
        if not mine:
            continue
        it = mine[0]
        line = f"index: {it.get('status')} cp={json.dumps(it.get('checkpoint'), ensure_ascii=False)[:100]}"
        if line != last:
            print(line, flush=True)
            last = line
        if it.get("status") in ("completed", "failed"):
            break
    assert it.get("status") == "completed", f"索引未完成: {it}"


async def probe_recall_and_prompt(client, h, doc_id: str) -> None:
    """只读探针（不触发嵌入/检索，避免额外进程加载模型）：类别展开与 Query 注入。"""
    from app.core.database import AsyncSessionLocal
    from app.services.extraction import extraction_resolver, prompt_renderer
    from app.services.extraction.extraction_models import ExtractionTarget
    from app.services.extraction.term_base_loader import load_term_base
    from sqlalchemy import text as sa_text

    async with AsyncSessionLocal() as db:
        await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
        cfg = await extraction_resolver.resolve(db, KB)
        tpl = next(t for t in cfg.schema_templates if t.get("id") == TEMPLATE)
        cats = tpl.get("categories") or []
        tb_rows = await load_term_base(db, KB, uuid.UUID(DETECT_TB))
        names = await load_term_base(db, KB, uuid.UUID("50c8936c-d5d4-46dd-9ae2-0059f7aad48d"))
        method_rows = await load_term_base(db, KB, uuid.UUID("a2970518-dca6-4ef8-b59c-bb597535007b"))
        print(f"probe: Schema 类别数={len(cats)}，项目大类术语数={len(names)}（期望展开 39）")
        cat = next(c for c in cats if c.get("id") == CAT_PROJ)
        target = ExtractionTarget(
            feature="室温拉伸", category_id=CAT_PROJ, template_id=TEMPLATE,
            return_type=cat.get("return_type") or "array",
            fields=cat.get("fields") or [],
            query_sources=cat.get("query_sources") or [],
            schema={"type": cat.get("return_type") or "array", "properties": {
                f["name"]: {"type": f.get("type") or "string"} for f in (cat.get("fields") or [])
            }},
            term_data={"检测项目": tb_rows, "试验方法": method_rows},
        )
        _, user = prompt_renderer.render_category(cfg, target, "上下文占位")
        assert "抗拉强度(Rm)" in user, "Query 术语集（检测项目.NAME）未注入 Prompt"
        assert "GB/T 228" in user or "GB/T 4338" in user, "Query 术语集（试验方法.METHOD_CODE）未注入 Prompt"
        print("PASS: Schema Query 术语集（检测项目/试验方法）已注入 Prompt")


async def run_extraction(client, h, doc_id: str, mode: str) -> dict:
    r = await client.post(f"/kb/{KB}/extraction/{doc_id}", headers=h)
    print(f"extract start ({mode}):", r.status_code)
    r.raise_for_status()
    last = None
    for _ in range(420):
        await asyncio.sleep(5)
        r = await client.get(f"/kb/{KB}/extraction/{doc_id}/status", headers=h)
        data = r.json()["data"]
        err = data.get("error")
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err, ensure_ascii=False)
        line = f"extract({mode}): task={data.get('task_status')} status={data.get('status')} progress={data.get('progress')} err={err}"
        if line != last:
            print(line, flush=True)
            last = line
        if data.get("status") in ("completed", "failed") or data.get("task_status") == "failed":
            break
    r = await client.get(f"/kb/{KB}/extraction/{doc_id}/result", headers=h)
    res = r.json()["data"]
    assert res.get("status") == "completed", f"抽取未完成: {res.get('error')}"
    return res


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=600) as client:
        token = await login(client)
        h = {"Authorization": f"Bearer {token}"}

        await set_global_config(client, h, "strict")
        doc_id, task_id = await upload_and_parse(client, h)
        print("doc_id:", doc_id, "task:", task_id)
        await wait_index(client, h, doc_id)
        await probe_recall_and_prompt(client, h, doc_id)

        res_strict = await run_extraction(client, h, doc_id, "strict")
        summary = res_strict["summary"]
        print("\nRESULT(strict):", json.dumps({
            "schema": res_strict.get("schema_name"),
            "total_records": summary.get("total_records"),
            "kept_categories": summary.get("kept_categories"),
            "recall": summary.get("recall"),
            "skipped_count": len(summary.get("skipped") or []),
            "skipped_sample": (summary.get("skipped") or [])[:6],
        }, ensure_ascii=False, indent=2))
        assert summary["recall"]["mode"] == "strict"
        reasons = " ".join(s.get("reason", "") for s in summary.get("skipped") or [])
        assert "置信度低于阈值" in reasons, "严格模式未按阈值剔除类别"
        assert set(summary["recall"]["score_bands"].keys()) == {"0-0.3", "0.3-0.5", "0.5-0.7", "0.7-0.9", "0.9-1.0"}

        await set_global_config(client, h, "loose")
        res_loose = await run_extraction(client, h, doc_id, "loose")
        s2 = res_loose["summary"]
        print("\nRESULT(loose):", json.dumps({
            "total_records": s2.get("total_records"),
            "kept_categories": s2.get("kept_categories"),
            "recall": s2.get("recall"),
        }, ensure_ascii=False, indent=2))
        assert s2["recall"]["mode"] == "loose"
        assert s2["recall"]["kept"] >= summary["recall"]["kept"], "宽松模式保留类别应不少于严格模式"

        # 恢复默认（等价默认值）
        await set_global_config(client, h, "loose")
        print("\nALL PASS: 解析→索引→抽取（strict/loose）+ 配置生效 + 9.5 演进")


if __name__ == "__main__":
    asyncio.run(main())
