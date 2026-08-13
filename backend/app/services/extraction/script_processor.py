"""E3 后处理/校验脚本执行（受限子进程 + 真实 kb_tools 工具层）。

脚本在 ``python -I`` 子进程中执行：术语集只读数据与运行参数经 stdin 注入；
``kb_tools`` 为真实工具（get_term_records/semantic_search/match_record/embed），
嵌入调用通过内部端点回父进程（BGE-M3 单例），避免子进程重复加载模型。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid

from sqlalchemy import select

from app.core.exceptions import BusinessException, ErrorCode
from app.services.extraction import script_tools


async def _script_code(db, kb_id, script_id: str) -> str:
    from app.models.extraction import KbScript

    s = (
        await db.execute(
            select(KbScript).where(KbScript.id == uuid.UUID(script_id), KbScript.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    if s is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message=f"脚本不存在：{script_id}")
    return s.code


async def apply_scripts(
    db,
    kb_id,
    *,
    category_feature: str,
    records: list[dict],
    doc_id: str,
    rules: list[dict],
    script_timeout: int = 10,
    term_data: dict | None = None,
):
    """按 sort_order 依次执行脚本，返回 (kept, rejected)。

    term_data/code 可由调用方预加载（并发场景避免共享会话并发查询）；
    未提供时按单线程调用方语义从 db 读取。
    """
    kept = [dict(r) for r in records]
    rejected: list[dict] = []
    term_data = term_data if term_data is not None else await script_tools.load_term_data(db, kb_id)
    token = script_tools.issue_embed_token(kb_id)
    try:
        embed_url = script_tools.embed_endpoint_url(kb_id)
        for rule in sorted(rules, key=lambda x: x.get("sort_order") or 0):
            code = rule.get("code") or await _script_code(db, kb_id, str(rule["script_id"]))
            if "def run(args):" not in code:
                raise BusinessException(message="脚本需定义 def run(args): 并返回 dict")
            payload = script_tools.build_script_code(code)
            stdin = json.dumps(
                {
                    "args": {
                        "records": kept,
                        "category": category_feature,
                        "doc_id": str(doc_id),
                    },
                    "term_data": term_data,
                    "embed": {"url": embed_url, "token": token},
                },
                ensure_ascii=False,
            )
            try:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, "-I", "-c", payload],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=script_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise BusinessException(message=f"脚本执行超时：{rule.get("script_name") or rule.get("script_id")}")
            if proc.returncode != 0:
                raise BusinessException(message=f"脚本执行失败：{rule.get("script_name") or rule.get("script_id")}：{(proc.stderr or "")[:300]}")
            try:
                result = json.loads(proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "null")
            except (ValueError, IndexError):
                raise BusinessException(message=f"脚本返回非 JSON：{rule.get("script_name") or rule.get("script_id")}")
            if not isinstance(result, dict):
                raise BusinessException(message="脚本必须返回 dict")
            kept = [dict(r) for r in result.get("records", kept) if isinstance(r, dict)]
            rejected.extend(dict(r) for r in result.get("rejected", []) if isinstance(r, dict))
    finally:
        script_tools.revoke_embed_token(token)
    return kept, rejected
