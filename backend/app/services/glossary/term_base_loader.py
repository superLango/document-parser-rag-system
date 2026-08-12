"""术语集数据读取接口（S8/C6 预留登记）。

仅供【抽取联动】复用（名称展开、Query 术语集分组、字段取值、后处理取值），
抽取阶段必须直接使用本模块，禁止重复建设同类读取逻辑。

load_term_base：按 kb + term_base_id 读取 active 词条并分组缓存。
分组键：group_field 优先（extras[group_field]），否则 category。
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.glossary import TERM_STATUS_ACTIVE, Term, TermBase

logger = get_logger(__name__)

_ALL = "__ALL__"


class TermBaseValueLoader:
    """术语集分组加载器（进程内缓存 + asyncio 双检锁）。"""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], dict] = {}
        self._lock = asyncio.Lock()

    async def load_term_base(
        self,
        db: AsyncSession,
        kb_id: uuid.UUID,
        term_base_id: uuid.UUID,
        group_field: str | None = None,
    ) -> dict | None:
        """加载术语集：{name, source_type, column_aliases, grouped}。

        grouped: {group_value: {field: [values]}}；无分组字段时 group 为 __ALL__。
        """
        cache_key = (str(kb_id), str(term_base_id), group_field or "")
        if cache_key in self._cache:
            return self._cache[cache_key]
        async with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
            base = (
                await db.execute(
                    select(TermBase).where(
                        TermBase.id == term_base_id,
                        TermBase.kb_id == kb_id,
                        TermBase.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if base is None:
                return None
            rows = (
                await db.execute(
                    select(Term).where(
                        Term.term_base_id == base.id,
                        Term.kb_id == kb_id,
                        Term.status == TERM_STATUS_ACTIVE,
                        Term.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            grouped: dict[str, dict[str, list[str]]] = {}
            for t in rows:
                group = _ALL
                if group_field:
                    g = (t.extras or {}).get(group_field)
                    if g:
                        group = str(g)
                elif t.category and t.category.strip():
                    group = t.category.strip()
                bucket = grouped.setdefault(group, {})
                for field, value in {
                    "term_name": t.term_name,
                    "standard_name": t.standard_name,
                    "english_term": t.english_term,
                    "definition": t.definition,
                    "category": t.category,
                    "standard_number": t.standard_number,
                }.items():
                    if value:
                        bucket.setdefault(field, []).append(value)
                for alias in (t.aliases or []):
                    if alias:
                        bucket.setdefault("aliases", []).append(alias)
            data = {
                "name": base.name,
                "source_type": base.source_type,
                "column_aliases": base.column_aliases or {},
                "grouped": grouped,
            }
            self._cache[cache_key] = data
            return data


term_base_value_loader = TermBaseValueLoader()
