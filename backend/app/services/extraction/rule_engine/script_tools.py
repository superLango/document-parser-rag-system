"""脚本可调用工具句柄（类似 magic-api 注入的上下文 Bean）。

入口函数统一为 ``def run(args)``，脚本内通过 ``await kb_tools.xxx()``
调用内置能力（向量化 / 语义检索 / 匹配 / 术语集访问）。

工具清单（供右侧"可调用工具"面板展示）：
- ``embed(texts)``                         文本向量化（bge-m3 dense，1024 维）
- ``semantic_search(records, query, match_fields, top_k, return_fields)``
                                            在记录列表内做语义相似检索（自动向量化）
- ``match_record(name, records, match_fields, threshold)``
                                            单条记录匹配（语义→精确→编辑距离）
- ``get_term_records(name, *fields)``      取术语集记录列表（键为修改后字段名）
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.term import SOURCE_TYPE_MANUAL, Term, TermBase
from app.services.embedding.embedding_service import embedding_service
from app.services.extraction.extraction_models import ExtractionTarget

logger = get_logger(__name__)


def _edit_similarity(s1: str, s2: str) -> float:
    """计算编辑距离相似度（1 - distance/max_len），用于 match_record 编辑距离兜底。"""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    def _norm(s: str) -> str:
        return "".join(
            str(c).strip().lower()
            for c in s
        ).translate(
            str.maketrans(
                "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
                "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
            )
        )

    def _levenshtein(a: str, b: str) -> int:
        if len(a) < len(b):
            return _levenshtein(b, a)
        if len(b) == 0:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            cur = [i + 1]
            for j, cb in enumerate(b):
                cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
            prev = cur
        return prev[-1]

    s1_norm = _norm(s1)
    s2_norm = _norm(s2)
    if s1_norm == s2_norm:
        return 1.0
    max_len = max(len(s1_norm), len(s2_norm))
    return 1.0 - _levenshtein(s1_norm, s2_norm) / max_len


class KbScriptTools:
    """脚本注入工具句柄。"""

    def __init__(
        self,
        target: ExtractionTarget | None = None,
        kb_id: str | None = None,
        db: AsyncSession | None = None,
        kb_tool: dict[str, Any] | None = None,
    ) -> None:
        self.target = target
        self.kb_id = kb_id
        self.db = db
        self.feature = target.feature if target else ""
        # kb_tool 性能参数（抽取配置全局 kb_tool 区块，缺省用内置默认）
        _kt = kb_tool or {}
        self._embed_batch_size = int(_kt.get("embed_batch_size") or 32)
        self._search_concurrency = int(_kt.get("search_concurrency") or 10)
        self._semantic_top_k = int(_kt.get("semantic_top_k") or 5)
        self._match_top_k = int(_kt.get("match_top_k") or 1)
        self._match_threshold = float(_kt.get("match_threshold") or 0.90)
        # 检索/匹配并发上限（当前脚本实例内共享信号量）
        self._sem = asyncio.Semaphore(self._search_concurrency)

    # ------------------------------------------------------------------
    # 底层服务原语（向量化 / 向量检索 / 匹配 / 术语集，供脚本自组逻辑）
    # ------------------------------------------------------------------
    async def embed(
        self,
        texts: str | list[str],
    ) -> list[list[float]]:
        """文本向量化（bge-m3 dense 向量，已归一化）。

        Args:
            texts: 单个字符串或字符串列表。

        Returns:
            list[list[float]]: 每个文本一个 1024 维向量。
        """
        if isinstance(texts, str):
            texts = [texts]
        texts = [t for t in texts if t]
        if not texts:
            return []
        # 按配置的批次大小分批向量化，避免单次请求过大
        out: list[list[float]] = []
        for i in range(0, len(texts), self._embed_batch_size):
            batch = texts[i : i + self._embed_batch_size]
            async with self._sem:
                result = await embedding_service.embed(
                    batch, return_sparse=False, max_length=512
                )
            out.extend(v.tolist() for v in result["dense_vectors"])
        return out

    async def semantic_search(
        self,
        records: list[dict[str, Any]],
        query: str,
        match_fields: list[str] | str,
        top_k: int | None = None,
        return_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """在给定记录列表内做语义相似检索（术语库通用检索）。

        对 ``query`` 及 ``records`` 中 ``match_fields`` 字段的值内部自动向量化，
        按余弦相似度排序返回最相似的 ``top_k`` 条。

        Args:
            records: 记录列表（来自 ``get_term_records``）。
            query: 查询词（内部自动向量化，无需外部传向量）。
            match_fields: 参与匹配的字段（修改后字段名），可传单个或多个。
            top_k: 返回结果数，缺省用 kb_tool 配置的 semantic_top_k。
            return_fields: 返回时保留的记录字段（默认保留全部 + score）。

        Returns:
            list[dict]: 按相似度降序，每条含 ``score`` 及按 ``return_fields`` 裁剪的记录。
        """
        top_k = top_k if top_k is not None else self._semantic_top_k
        if not records or not query:
            return []
        mfs = match_fields if isinstance(match_fields, list) else [match_fields]
        mfs = [f for f in mfs if f]
        if not mfs:
            raise ValueError("match_fields 不能为空")

        # 拼接每条记录的匹配文本，同时记录有效索引
        texts: list[str] = []
        valid_idx: list[int] = []
        for i, r in enumerate(records):
            parts = [str(r.get(f, "")).strip() for f in mfs]
            text = " ".join(p for p in parts if p).strip()
            if text:
                texts.append(text)
                valid_idx.append(i)

        if not texts:
            return []

        async with self._sem:
            vecs = await embedding_service.embed(
                [query] + texts, return_sparse=False, max_length=512
            )
        query_vec = vecs[0]
        rec_vecs = vecs[1:]

        scored: list[tuple[float, dict[str, Any]]] = []
        for idx, vec in zip(valid_idx, rec_vecs):
            sim = float(np.dot(np.asarray(query_vec), np.asarray(vec)))
            if return_fields:
                item = {
                    k: records[idx].get(k)
                    for k in return_fields
                    if k in records[idx]
                }
            else:
                item = dict(records[idx])
            item["score"] = sim
            scored.append((sim, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    async def match_record(
        self,
        name: str,
        records: list[dict[str, Any]],
        match_fields: list[str] | str,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        """单条记录匹配：语义检索优先 + 精确/编辑距离 fallback。

        Args:
            name: 待匹配的查询词。
            records: 记录列表（来自 ``get_term_records``）。
            match_fields: 参与匹配的字段（修改后字段名）。
            threshold: 向量命中的相似度阈值，缺省用 kb_tool 配置的 match_threshold。

        Returns:
            dict: {"canonical": 规范值, "score": 置信度, "type": 匹配类型, "record": 命中记录}
                匹配类型：vector / exact / edit_distance / unverified。
        """
        threshold = threshold if threshold is not None else self._match_threshold
        if not name or not records:
            return {"canonical": name, "score": 0.0, "type": "unverified", "record": None}
        mfs = match_fields if isinstance(match_fields, list) else [match_fields]
        mfs = [f for f in mfs if f]
        canonical_field = mfs[0] if mfs else None
        name_clean = name.strip()

        # 1. 语义检索优先
        try:
            top = await self.semantic_search(records, name, mfs, top_k=self._match_top_k)
            if top and top[0]["score"] >= threshold:
                hit = top[0]
                canonical = str(hit.get(canonical_field) or name)
                return {
                    "canonical": canonical,
                    "score": hit["score"],
                    "type": "vector",
                    "record": hit,
                }
        except Exception as err:
            logger.warning("match_record 语义检索失败", error=str(err))

        # 2. 精确匹配
        for r in records:
            for f in mfs:
                if str(r.get(f, "")).strip() == name_clean:
                    return {
                        "canonical": name_clean,
                        "score": 1.0,
                        "type": "exact",
                        "record": r,
                    }

        # 3. 编辑距离匹配
        best_r = None
        best_val = ""
        best_sim = 0.0
        for r in records:
            for f in mfs:
                val = str(r.get(f, "")).strip()
                if not val:
                    continue
                sim = _edit_similarity(name_clean, val)
                if sim > best_sim:
                    best_sim = sim
                    best_r = r
                    best_val = val
        if best_r and best_sim >= 0.85:
            return {
                "canonical": best_val,
                "score": best_sim,
                "type": "edit_distance",
                "record": best_r,
            }

        return {
            "canonical": name,
            "score": best_sim,
            "type": "unverified",
            "record": None,
        }

    # ------------------------------------------------------------------
    # 术语集访问（可用参数：按术语集名称取记录）
    # ------------------------------------------------------------------
    async def get_term_records(
        self,
        term_base_name: str,
        *fields: str,
    ) -> list[dict[str, Any]]:
        """取指定术语集的记录列表，键为修改后的字段名。

        类似向量检索的封装：传入术语集名称 + 需要的字段（新表头名 / 原始字段名），
        返回对象列表，每个对象的键为传入的字段名（已是修改后的显示名）。

        .. code-block:: python

            async def run(args):
                rows = await kb_tools.get_term_records("材料牌号", "牌号", "厂家")
                ...

        Args:
            term_base_name: 术语集名称（TermBase.name）。
            *fields: 需要的字段名（优先按 column_aliases 新表头名，回退原始字段名）。

        Returns:
            list[dict]: 每条记录一个 dict；术语集不存在或无 db 时返回空列表。
        """
        if self.db is None or not self.kb_id:
            return []
        base = (
            await self.db.execute(
                select(TermBase).where(
                    TermBase.kb_id == self.kb_id,
                    TermBase.name == term_base_name,
                )
            )
        ).scalar_one_or_none()
        if base is None:
            return []
        rows = (
            await self.db.execute(
                select(Term)
                .where(
                    Term.term_base_id == base.id,
                    Term.kb_id == self.kb_id,
                    Term.status == "active",
                )
                .order_by(Term.term_name)
            )
        ).scalars().all()
        # 反向映射：新表头别名 -> 原始字段名
        raw_by_alias = {
            str(alias).strip(): raw for raw, alias in (base.column_aliases or {}).items()
        }
        result: list[dict[str, Any]] = []
        for t in rows:
            rec: dict[str, Any] = {}
            for field in fields:
                f = field.strip()
                raw = raw_by_alias.get(f, f)
                rec[f] = self._term_field_value(t, base, raw)
            result.append(rec)
        return result

    @staticmethod
    def _term_field_value(t: Term, base: TermBase, raw: str) -> Any:
        """按原始字段名取值：manual 用内置字段，api/db 用 extras 动态字段。"""
        if base.source_type == SOURCE_TYPE_MANUAL:
            return getattr(t, raw, None)
        extras = t.extras or {}
        return extras.get(raw)


# 工具目录（供右侧面板展示可调用工具）
TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "embed",
        "desc": "文本向量化：把文本转成 bge-m3 的 1024 维稠密向量（已归一化），是语义检索的第一步。",
        "params": [
            {"name": "texts", "type": "str | list[str]", "desc": "单个文本或文本列表"},
        ],
        "returns": "list[list[float]]（每个文本对应一个 1024 维向量，顺序与入参一致）",
        "usage": "vecs = await kb_tools.embed(\"拉伸强度\")\n# 或整批：vecs = await kb_tools.embed([\"a\", \"b\"])",
    },
    {
        "name": "semantic_search",
        "desc": "语义检索：在传入的记录列表内，用查询词与指定字段做相似度检索，返回最相似的 top_k 条（内部自动向量化）。",
        "params": [
            {"name": "records", "type": "list[dict]", "desc": "待检索的记录列表（通常来自 get_term_records）"},
            {"name": "query", "type": "str", "desc": "查询词"},
            {"name": "match_fields", "type": "str | list[str]", "desc": "参与匹配的字段名（可单个或多个）"},
            {"name": "top_k", "type": "int", "desc": "返回结果数，默认 5"},
            {"name": "return_fields", "type": "list[str] | None", "desc": "仅返回字段（可选），缺省返回全字段"},
        ],
        "returns": "list[dict]（按相似度降序，含 score 字段）",
        "usage": "top = await kb_tools.semantic_search(rows, \"Q235B\", [\"牌号\"], top_k=1)",
    },
    {
        "name": "match_record",
        "desc": "单条匹配：对一条查询词做语义检索，相似度 ≥ 阈值判为命中；失败回退精确/编辑距离匹配。用于项目名、牌号等归一化。",
        "params": [
            {"name": "name", "type": "str", "desc": "待匹配的查询词"},
            {"name": "records", "type": "list[dict]", "desc": "候选记录列表（通常来自 get_term_records）"},
            {"name": "match_fields", "type": "str | list[str]", "desc": "参与匹配的字段名"},
            {"name": "threshold", "type": "float", "desc": "语义命中阈值，默认 0.90"},
        ],
        "returns": "{canonical(标准化名), score(置信度), type(匹配类型 vector/exact/edit_distance/unverified), record(命中的原始记录)}",
        "usage": "hit = await kb_tools.match_record(\"Rp0.2\", rows, [\"项目名称\"])\n# if hit[\"type\"] != \"unverified\": r[\"项目名称\"] = hit[\"canonical\"]",
    },
    {
        "name": "get_term_records",
        "desc": "取术语集记录：按术语集名称读取当前知识库下该术语集的全部记录，返回对象列表（键为修改后的字段名）。",
        "params": [
            {"name": "name", "type": "str", "desc": "术语集名称（TermBase.name）"},
            {"name": "*fields", "type": "str", "desc": "需要的字段名（优先按新表头名，可传多个）"},
        ],
        "returns": "list[dict]（每条记录一个 dict，键为传入的字段名；术语集不存在返回空列表）",
        "usage": "rows = await kb_tools.get_term_records(\"材料牌号\", \"牌号\", \"厂家\")\n# rows = [{\"牌号\": \"Q235B\", \"厂家\": \"宝钢\"}, ...]",
    },
]