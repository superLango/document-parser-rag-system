"""E3 后处理/校验脚本执行（复用受限子进程执行器）。"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid

from sqlalchemy import select

from app.core.exceptions import BusinessException, ErrorCode
from app.services.extraction.term_base_loader import load_term_base


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


async def _term_tools(db, kb_id) -> dict:
    """按术语集名构建 {名称: {字段: [值]}} 只读数据。"""
    from app.models.glossary import TermBase

    bases = (await db.execute(select(TermBase).where(TermBase.kb_id == kb_id))).scalars().all()
    tools: dict[str, dict[str, list[str]]] = {}
    for b in bases:
        rows = await load_term_base(db, kb_id, b.id)
        bucket: dict[str, list[str]] = {}
        for r in rows:
            for f in ("term_name", "standard_name", "english_term", "definition", "category", "standard_number"):
                v = r.get(f)
                if v:
                    bucket.setdefault(f, []).append(str(v))
            for k, v in (r.get("extras") or {}).items():
                if v is not None:
                    bucket.setdefault(str(k), []).append(str(v))
        tools[b.name] = bucket
    return tools


_TEMPLATE = """
import asyncio, json, sys

TERM_DATA = {term_data}

class _KbTools:
    async def get_term_records(self, name, field):
        return TERM_DATA.get(name, {{}}).get(field, [])
    async def embed(self, text):
        return {{"text": text, "vector": []}}
    async def semantic_search(self, query, top_k=5):
        return []
    async def match_record(self, query, rows, fields):
        return []

kb_tools = _KbTools()

{code}

async def _main():
    args = json.loads(sys.stdin.read())
    result = run(args)
    if asyncio.iscoroutine(result):
        result = await result
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))

asyncio.run(_main())
"""


async def apply_scripts(db, kb_id, *, category_feature: str, records: list[dict], doc_id: str, rules: list[dict], script_timeout: int = 10):
    """按 sort_order 依次执行脚本，返回 (kept, rejected)。"""
    kept = [dict(r) for r in records]
    rejected: list[dict] = []
    term_data = await _term_tools(db, kb_id)
    for rule in sorted(rules, key=lambda x: x.get("sort_order") or 0):
        code = await _script_code(db, kb_id, str(rule["script_id"]))
        if "def run(args):" not in code:
            raise BusinessException(message="脚本需定义 def run(args): 并返回 dict")
        payload = _TEMPLATE.format(term_data=json.dumps(term_data, ensure_ascii=False), code=code)
        args = {"records": kept, "category": category_feature, "doc_id": str(doc_id)}
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-I", "-c", payload],
                input=json.dumps(args, ensure_ascii=False),
                capture_output=True, text=True, timeout=script_timeout, check=False,
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
    return kept, rejected
