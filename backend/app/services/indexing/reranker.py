"""重排接口占位（S6/D6：本期直通，预留 bge-reranker 等接入点）。"""

from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    """重排器接口：对候选结果重新排序。"""

    async def rerank(self, query: str, hits: list[dict], top_k: int) -> list[dict]:
        """按相关性重新排序，返回 top_k。"""


class PassthroughReranker:
    """直通重排器：不改变顺序（默认实现，后续可替换）。"""

    async def rerank(self, query: str, hits: list[dict], top_k: int) -> list[dict]:
        return hits[:top_k]


passthrough_reranker = PassthroughReranker()
