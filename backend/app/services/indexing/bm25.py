"""KB 级 jieba BM25（S5/D4，零 LLM 依赖）。

职责：
- 分词：正则提取 ASCII 词元（元素符号 C/Cr/Mo、标准号 GB/T 228.1、数值范围），
  剩余中文用 jieba；
- 统计：kb_bm25_stats 表增量维护 n_docs/total_len/doc_freq，
  随文档索引/重索引/删除同步（行锁串行化同 KB 更新）；
- 打分：查询 tokenize → SQL 候选（bm25_tokens ?| query_tokens）→ Python BM25
  （k1=1.5, b=0.75，配置化）。

与旧项目 bm25_sparse.py 的关系：沿用 jieba + ASCII 词元与 k1/b 参数结论，
但存储从本地 JSON + Milvus SPARSE_FLOAT_VECTOR 改为 PG 增量统计 + GIN 索引，
不产生稀疏向量格式。
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter

import jieba
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.indexing import KbBm25Stats

logger = get_logger(__name__)

# 英文/数字词元（含小数点、±、~、/ 等）：元素符号、标准号、数值范围
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[.~\-\+/][A-Za-z0-9]+)*")


def tokenize_text(text: str) -> list[str]:
    """将文本切分为词元列表（ASCII 词元优先，中文剩余 jieba）。"""
    if not text:
        return []
    tokens: list[str] = []
    pos = 0
    for m in _ASCII_TOKEN_RE.finditer(text):
        if m.start() > pos:
            tokens.extend(_jieba_cut(text[pos : m.start()]))
        tokens.append(m.group(0))
        pos = m.end()
    if pos < len(text):
        tokens.extend(_jieba_cut(text[pos:]))
    return tokens


# 纯标点/空白词元（jieba 可能产出；引号类词元由 jieba 自带过滤）
_PUNCT_ONLY_RE = re.compile(r"^[\s，。！？；：、（）()【】\[\]·—…~～、.≥≤±℃×%％]+$")


def _jieba_cut(segment: str) -> list[str]:
    out: list[str] = []
    for tok in jieba.cut(segment):
        tok = tok.strip()
        if tok and not _PUNCT_ONLY_RE.fullmatch(tok):
            out.append(tok)
    return out


def chunk_token_counts(text: str) -> dict[str, int]:
    """块文本 → {token: count}（写入 document_chunks.bm25_tokens）。"""
    return dict(Counter(tokenize_text(text)))


def _idf(n_docs: int, doc_freq: int) -> float:
    return math.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))


def bm25_score(
    term_freq: int, doc_len: int, avg_dl: float, n_docs: int, doc_freq: int
) -> float:
    """单词元 BM25 得分（k1/b 来自配置）。"""
    k1 = settings.BM25_K1
    b = settings.BM25_B
    idf = _idf(n_docs, doc_freq)
    if avg_dl <= 0:
        return 0.0
    denom = term_freq + k1 * (1 - b + b * doc_len / avg_dl)
    return idf * (term_freq * (k1 + 1)) / denom if denom else 0.0


class KBBm25Service:
    """KB 级 BM25 统计与查询打分。"""

    # ------------------------------------------------------------------
    # 统计维护
    # ------------------------------------------------------------------

    async def add_document_stats(
        self,
        db: AsyncSession,
        kb_id: uuid.UUID,
        chunks_tokens: list[dict[str, int]],
    ) -> None:
        """新增文档块统计（同 KB 行锁串行，version 自增）。"""
        stats = await self._lock_stats(db, kb_id)
        payload = dict(stats.payload or {})
        doc_freq = dict(payload.get("doc_freq") or {})
        n_docs = int(payload.get("n_docs") or 0)
        total_len = int(payload.get("total_len") or 0)
        for counts in chunks_tokens:
            n_docs += 1
            total_len += sum(counts.values())
            for tok in counts:
                doc_freq[tok] = doc_freq.get(tok, 0) + 1
        payload["n_docs"] = n_docs
        payload["total_len"] = total_len
        payload["doc_freq"] = doc_freq
        stats.payload = payload
        stats.version += 1
        await db.commit()

    async def remove_document_stats(
        self,
        db: AsyncSession,
        kb_id: uuid.UUID,
        chunks_tokens: list[dict[str, int]],
    ) -> None:
        """回退文档块统计（删除/重索引前调用；缺失 token 按 0 处理）。"""
        if not chunks_tokens:
            return
        stats = await self._lock_stats(db, kb_id)
        payload = dict(stats.payload or {})
        doc_freq = dict(payload.get("doc_freq") or {})
        n_docs = max(0, int(payload.get("n_docs") or 0) - len(chunks_tokens))
        total_len = max(0, int(payload.get("total_len") or 0) - sum(sum(c.values()) for c in chunks_tokens))
        for counts in chunks_tokens:
            for tok in counts:
                if tok in doc_freq:
                    doc_freq[tok] = max(0, doc_freq[tok] - 1)
                    if doc_freq[tok] == 0:
                        del doc_freq[tok]
        payload["n_docs"] = n_docs
        payload["total_len"] = total_len
        payload["doc_freq"] = doc_freq
        stats.payload = payload
        stats.version += 1
        await db.commit()

    async def _lock_stats(
        self, db: AsyncSession, kb_id: uuid.UUID
    ) -> KbBm25Stats:
        """获取并锁住 KB 统计行（不存在则幂等创建，并发安全）。"""
        await db.execute(
            text(
                "INSERT INTO kb_bm25_stats (kb_id, payload, version) "
                "VALUES (:kb, '{\"n_docs\": 0, \"total_len\": 0, \"doc_freq\": {}}'::jsonb, 1) "
                "ON CONFLICT (kb_id) DO NOTHING"
            ).bindparams(kb=kb_id)
        )
        stats = (
            await db.execute(
                select(KbBm25Stats)
                .where(KbBm25Stats.kb_id == kb_id)
                .with_for_update(),
            )
        ).scalar_one()
        return stats

    # ------------------------------------------------------------------
    # 查询打分
    # ------------------------------------------------------------------

    async def score_query(
        self,
        db: AsyncSession,
        kb_id: uuid.UUID,
        query: str,
        top_k: int = 20,
        extra_where: str = "",
        extra_params: dict | None = None,
    ) -> list[dict]:
        """查询 BM25 打分：候选过滤 + Python 打分，返回 top_k。

        Returns:
            [{"chunk_id", "score", "content", "hierarchy_path", "title",
              "document_id", "source_pages", "has_table"}] 按 score 降序。
        """
        query_tokens = tokenize_text(query)
        if not query_tokens or not query_tokens[0]:
            return []
        unique_tokens = list(dict.fromkeys(query_tokens))

        # 候选：包含任一查询词元的未删除块（GIN 索引加速；支持过滤条件）
        bind = {"kb": kb_id, "tokens": unique_tokens}
        if extra_params:
            bind.update(extra_params)
        rows = (
            await db.execute(
                text(
                    "SELECT chunk_id, document_id, content, hierarchy_path, title, "
                    "source_pages, has_table, bm25_tokens FROM document_chunks "
                    "WHERE kb_id = :kb AND deleted_at IS NULL "
                    f"AND bm25_tokens ?| :tokens{extra_where}"
                ).bindparams(**bind),
            )
        ).all()
        if not rows:
            return []

        stats = (
            await db.execute(select(KbBm25Stats).where(KbBm25Stats.kb_id == kb_id))
        ).scalar_one_or_none()
        payload = (stats.payload if stats else {}) or {}
        n_docs = int(payload.get("n_docs") or 0)
        total_len = int(payload.get("total_len") or 0)
        avg_dl = total_len / n_docs if n_docs else 0.0
        doc_freq: dict[str, int] = payload.get("doc_freq") or {}

        scored: list[dict] = []
        for row in rows:
            counts: dict[str, int] = row.bm25_tokens or {}
            doc_len = sum(counts.values())
            score = 0.0
            for tok in unique_tokens:
                freq = int(counts.get(tok, 0))
                if freq > 0:
                    score += bm25_score(
                        freq, doc_len, avg_dl, max(n_docs, 1), doc_freq.get(tok, 0) + 1
                    )
            if score > 0:
                scored.append({
                    "chunk_id": row.chunk_id,
                    "document_id": str(row.document_id),
                    "content": row.content,
                    "hierarchy_path": row.hierarchy_path,
                    "title": row.title,
                    "source_pages": row.source_pages,
                    "has_table": row.has_table,
                    "score": round(score, 6),
                })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


kb_bm25_service = KBBm25Service()
