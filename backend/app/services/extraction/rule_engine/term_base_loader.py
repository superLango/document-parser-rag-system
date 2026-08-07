"""术语集动态加载器（TermBaseValueLoader）。

按 term_base_id 按需加载术语集字段值并缓存，供后处理 / 校验规则动态取值。
对齐 Schema 类别 / Query 术语集的取值方式：
- value_field 优先按术语集 column_aliases 的新表头名匹配，回退原始字段名 / 内置字段。
- 支持 group_field 分组，供按类别过滤（对齐 query_sources.group_field）。

加载结果以 ``{group_value: {field: [value...]}}`` 组织；无 group_field 时
group_value 固定为 ``__ALL__``。
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.term import SOURCE_TYPE_MANUAL, Term, TermBase

logger = get_logger(__name__)

# 手动术语集内置字段 → Term 模型字段映射
_MANUAL_FIELD_MAP: dict[str, tuple[str, str]] = {
    "term_name": ("term_name", "term_name"),
    "standard_name": ("standard_name", "standard_name"),
    "definition": ("definition", "definition"),
    "category": ("category", "category"),
    "synonyms": ("synonyms", "synonyms"),
    "aliases": ("aliases", "aliases"),
    "standard_number": ("standard_number", "standard_number"),
}

# 分组未配置时的统一 key
_ALL = "__ALL__"


class TermBaseValueLoader:
    """术语集字段值加载器（带进程内缓存）。"""

    def __init__(self) -> None:
        # key: (kb_id, term_base_id) -> {version, grouped: {group: {field: [values]}}}
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def load_term_base(
        self,
        db: AsyncSession,
        kb_id: str,
        term_base_id: str,
        group_field: str | None = None,
    ) -> dict[str, Any] | None:
        """加载术语集，返回 {name, source_type, column_aliases, grouped} 或 None。

        ``group_field`` 指定时按该字段（如 FEATURE）对词条分组，供 Query 术语集
        按类别展开实例名取值；不指定时回退默认分组（api/db 按 extras.group/分组，
        手动类型按 category）。分组字段纳入缓存 key。
        """
        cache_key = (str(kb_id), str(term_base_id), group_field or "")
        if cache_key in self._cache:
            return self._cache[cache_key]

        async with self._lock:
            # 双检：可能已被并发填充
            if cache_key in self._cache:
                return self._cache[cache_key]

            base = (
                await db.execute(
                    select(TermBase).where(
                        TermBase.id == term_base_id,
                        TermBase.kb_id == kb_id,
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
                        Term.status == "active",
                    )
                )
            ).scalars().all()

            data = {
                "name": base.name,
                "source_type": base.source_type,
                "column_aliases": base.column_aliases or {},
                "grouped": self._group_rows(rows, base, group_field),
            }
            self._cache[cache_key] = data
            return data

    def _group_rows(
        self,
        rows: list[Term],
        base: TermBase,
        group_field: str | None = None,
    ) -> dict[str, dict[str, list[str]]]:
        """按分组字段分组：{group_value: {field: [values]}}。

        ``group_field`` 指定时优先用其作为分组键（如 api/db 术语集的 FEATURE）；
        未指定时回退默认（api/db 用 extras.group/分组，手动类型用 category）。
        """
        grouped: dict[str, dict[str, list[str]]] = {}
        for t in rows:
            group = _ALL
            if base.source_type == SOURCE_TYPE_MANUAL:
                cat = t.category or ""
                if cat.strip():
                    group = cat.strip()
            else:
                g = None
                if group_field:
                    g = (t.extras or {}).get(group_field)
                if g is None:
                    g = (t.extras or {}).get("group") or (t.extras or {}).get("分组")
                group = str(g) if g not in (None, "") else _ALL
            bucket = grouped.setdefault(group, {})
            self._accumulate_row(bucket, t, base)
        return grouped

    def _accumulate_row(
        self,
        bucket: dict[str, list[str]],
        t: Term,
        base: TermBase,
    ) -> None:
        """把一条术语可能出现的各字段值累加进 bucket。"""
        # 手动类型：内置字段全量累加，便于按任意内置字段取值
        if base.source_type == SOURCE_TYPE_MANUAL:
            self._add(bucket, "term_name", t.term_name)
            self._add(bucket, "standard_name", t.standard_name)
            self._add(bucket, "definition", t.definition)
            self._add(bucket, "category", t.category)
            self._add(bucket, "synonyms", t.synonyms)
            self._add(bucket, "aliases", t.aliases)
            self._add(bucket, "standard_number", t.standard_number)
            return
        # api/db：extras 动态字段
        for k, v in (t.extras or {}).items():
            self._add(bucket, k, v)

    @staticmethod
    def _add(bucket: dict[str, list[str]], field: str, value: Any) -> None:
        if value is None:
            return
        values = value if isinstance(value, list) else [value]
        existing = bucket.setdefault(field, [])
        for v in values:
            vs = str(v).strip()
            if vs and vs not in existing:
                existing.append(vs)

    def _resolve_field(self, data: dict[str, Any], field: str) -> str:
        """把 value_field（新表头别名/原始字段名）解析为 bucket 中的取值键。"""
        aliases = data.get("column_aliases") or {}
        # 反向映射：新表头名 -> 原始字段名
        for raw, alias in aliases.items():
            if alias == field:
                return raw
        # 直接是原始字段名 / 内置字段
        return field

    def get_group_values(
        self,
        data: dict[str, Any],
        field: str,
        group_value: str | None = None,
    ) -> list[str]:
        """取指定字段的值列表。

        Args:
            data: load_term_base 返回的数据（已按 group_field 分组）。
            field: 取值字段（新表头别名或原始字段名）。
            group_value: 分组值（None 表示取全量）。
        """
        grouped: dict[str, dict[str, list[str]]] = data.get("grouped", {})
        key = self._resolve_field(data, field)

        if group_value is None:
            # 全量：合并所有分组
            merged: list[str] = []
            for bucket in grouped.values():
                for v in bucket.get(key, []):
                    if v not in merged:
                        merged.append(v)
            return merged

        bucket = grouped.get(group_value) or grouped.get(_ALL) or {}
        return bucket.get(key, [])

    def invalidate(self, kb_id: str, term_base_id: str) -> None:
        """失效指定术语集缓存。"""
        self._cache.pop((str(kb_id), str(term_base_id)), None)


# 模块级单例
term_base_loader = TermBaseValueLoader()