"""重排器（S6/D6）：默认直通；开启全局配置 reranker 后使用 BGE-M3 语义精排。

说明：当前环境无独立重排模型，语义精排复用 BGE-M3（query 与候选块编码后按余弦
重排）；后续接入 bge-reranker 等交叉编码模型时替换 SemanticReranker 即可。
"""

from __future__ import annotations

from typing import Any, Protocol


class Reranker(Protocol):
    """重排器接口：对候选结果重新排序。"""

    async def rerank(self, query: str, hits: list[Any], top_k: int) -> list[Any]:
        """按相关性重新排序，返回 top_k。"""


class PassthroughReranker:
    """直通重排器：不改变顺序（默认实现）。"""

    async def rerank(self, query: str, hits: list[Any], top_k: int) -> list[Any]:
        return hits[:top_k]


class SemanticReranker:
    """BGE-M3 语义精排：query 与候选内容编码后按余弦相似度重排。"""

    async def rerank(self, query: str, hits: list[Any], top_k: int) -> list[Any]:
        from app.services.embedding.embedding_service import embedding_service

        if not hits:
            return []
        texts = [query] + [
            getattr(h, "content", None) or (h.get("content", "") if isinstance(h, dict) else "")
            for h in hits
        ]
        vecs = await embedding_service.embed(texts)
        qv = vecs[0]
        scored: list[tuple[float, Any]] = []
        for h, v in zip(hits, vecs[1:]):
            sim = sum(a * b for a, b in zip(qv, v))
            scored.append((sim, h))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [h for _, h in scored[:top_k]]


def get_reranker(retrieval_config: dict | None = None):
    """按全局配置选择重排器：reranker.enabled=true 时启用 BGE-M3 语义精排。"""
    rcfg = retrieval_config or {}
    rer = rcfg.get("reranker") or {}
    if rer.get("enabled"):
        return SemanticReranker()
    return passthrough_reranker


passthrough_reranker = PassthroughReranker()
