"""标准信息类别修复：固定注入封面块 + 检索 hits（重排排序），自研直调抽取。

用法（能访问内网 + 项目 DB）：
    cd /home/grainuser/hansonDoc_RAG/backend
    PYTHONPATH=. .venv/bin/python ../scripts/extract_standard_info_fix.py
输出：qa/evaluation/results/gb1220_builtin_all/standard_info_fix.json + standard_info_fix_meta.json
"""
import asyncio
import json
import re
import time
from pathlib import Path

import httpx
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services import kb_resource_service
from app.services.extraction import category_builder, context_assembler, extraction_resolver, prompt_renderer

KB = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
DOC = "09a79bb1-1c17-44bc-bb02-57eab2e25580"
OUT = Path(__file__).resolve().parents[1] / "qa/evaluation/results/gb1220_builtin_all"
MAX_TOKENS = 100000
# 标准信息关键块匹配（封面/编号/代替）
STD_PAT = re.compile(r"中华人民共和国国家标准|GB/T\s*1220")


def page_no(sp):
    m = re.search(r"\d+", str(sp))
    return int(m.group()) if m else 0


def parse_records(content, return_type="array"):
    t = content.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        data = json.loads(t)
    except Exception:
        for m in re.finditer(r"\[.*?\]", t, re.S):
            try:
                data = json.loads(m.group(0))
                break
            except Exception:
                continue
        else:
            return [], t[:200]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)], ""
    if isinstance(data, dict):
        # 兼容 {"records": [...]} 包装
        if isinstance(data.get("records"), list):
            return [r for r in data["records"] if isinstance(r, dict)], ""
        # 兼容旧版 {"items": [...]} 等单数组包装
        arrs = [v for v in data.values() if isinstance(v, list)]
        if arrs:
            return [r for r in arrs[0] if isinstance(r, dict)], ""
        # object 返回类型（如标准信息）：字典本身就是一条记录
        if return_type == "object" or data:
            return [data], ""
    return [], ""


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = AsyncSessionLocal()
    await db.execute(text("SELECT set_config('app.current_kb', :k, true)"), {"k": KB})
    await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": "10d34ab7-d543-4a8c-97da-2aeb78209df7"})
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
    cfg = await extraction_resolver.resolve(db, KB)

    # 先取 LLM 资源（与 extract_gb1220_builtin.py 一致），再组装请求体
    llm = await kb_resource_service.get_llm_resource_raw(db, KB)
    llm_url = (llm.get("api_base") or "").rstrip("/") + "/chat/completions"
    llm_model = (llm.get("model") or "").strip()
    llm_headers = {"Authorization": f"Bearer {llm.get('api_key') or ''}", "Content-Type": "application/json"}
    if not llm.get("api_base") or not llm_model:
        msg = "LLM 资源未配置 api_base/model，请先在 KB 资源与配置中配置"
        (OUT / "standard_info_fix_error.txt").write_text(msg + "\n", encoding="utf-8")
        print(msg)
        await db.close()
        return
    print(f"LLM: {llm_url} | model: {llm_model}", flush=True)

    targets, _ = await category_builder.build_targets(cfg, db, kb_id=KB)
    tgt = next(t for t in targets if t.feature == "标准信息")

    # 1) 固定封面块（DB 提取，不依赖检索）
    rows = (await db.execute(text("""
        SELECT source_pages, content FROM document_chunks
        WHERE kb_id=:kb AND document_id=:doc AND deleted_at IS NULL ORDER BY source_pages
    """), {"kb": KB, "doc": DOC})).fetchall()
    fixed = []
    for r in rows:
        c = r[1] or ""
        if STD_PAT.search(c):
            p = page_no(r[0])
            fixed.append((p, f"[标准信息][第{p}页]\n{c}"))
    fixed.sort(key=lambda x: x[0])
    fixed_context = "\n\n".join(b for _, b in fixed)
    print(f"固定封面块: {len(fixed)} 个 | {fixed_context[:200]!r}", flush=True)

    # 2) 检索 hits（重排排序）
    built, sk = await category_builder.build_one(cfg, db, kb_id=KB, document_id=DOC, target=tgt)
    if built is None:
        msg = f"标准信息类别未构建成功（skip reason: {sk.reason if sk else '未知'}）"
        (OUT / "standard_info_fix_error.txt").write_text(msg + "\n", encoding="utf-8")
        print(msg)
        await db.close()
        return
    retrieval_cfg = cfg.global_config.get("retrieval") or {}
    ctx_top_k = min(built.top_k or int(retrieval_cfg.get("top_k") or 10),
                    int(retrieval_cfg.get("context_top_k") or 30))
    hits_ctx = context_assembler.assemble_full_sorted(built.hits or [], top_k=ctx_top_k) if built else ""
    context = f"{fixed_context}\n\n[其他检索内容]\n{hits_ctx}" if hits_ctx else fixed_context
    print(f"上下文: {len(context)} 字符 | 含 GB/T 1220: {'GB/T 1220' in context} | 含 不锈钢棒: {'不锈钢棒' in context}", flush=True)

    system, user = prompt_renderer.render_category(cfg, built, context)
    user = user.replace("${prev_brands}", "")
    body = {
        "model": llm_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            r = await client.post(llm_url, json=body, headers=llm_headers, timeout=None)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "response", None)
        detail = f"{type(exc).__name__}: {exc}"
        if status is not None:
            detail += f"\nHTTP {getattr(status, 'status_code', '?')}\n{getattr(status, 'text', '')[:2000]}"
        (OUT / "standard_info_fix_error.txt").write_text(detail + "\n", encoding="utf-8")
        (OUT / "standard_info_fix_request.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"LLM 调用失败，已写入 standard_info_fix_error.txt:\n{detail}", flush=True)
        await db.close()
        return
    dt = time.monotonic() - t0
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    usage = data.get("usage") or {}
    recs, perr = parse_records(content, tgt.return_type)
    (OUT / "standard_info_fix.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {
        "records": len(recs),
        "fixed_blocks": len(fixed),
        "context_chars": len(context),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "elapsed_sec": round(dt, 1),
        "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
        "parse_error": perr,
        "raw_content": content,
        "records_detail": recs,
    }
    (OUT / "standard_info_fix_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成: {len(recs)} 条 | {usage.get('completion_tokens')} tok | {dt:.0f}s")
    for r in recs:
        print("  ", json.dumps(r, ensure_ascii=False))
    await db.close()


if __name__ == "__main__":
    import traceback

    try:
        asyncio.run(main())
    except Exception:  # noqa: BLE001
        err = traceback.format_exc()
        (OUT / "standard_info_fix_error.txt").write_text(err, encoding="utf-8")
        print("脚本异常，已写入 standard_info_fix_error.txt：")
        print(err)
