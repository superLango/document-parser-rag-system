"""重排器（S6/D6）：默认直通；reranker.model 配置 bge-reranker 路径时用交叉编码精排。

- `PassthroughReranker`：默认直通；
- `SemanticReranker`：复用 BGE-M3 语义精排（无独立重排模型时的回退）；
- `CrossEncoderReranker`：bge-reranker（XLM-RoBERTa 交叉编码），
  query 与候选块拼接打分，质量优于向量精排（2026-08 接入，权重在 models/）。
"""

from __future__ import annotations

import asyncio
import logging
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


class CrossEncoderReranker:
    """bge-reranker 交叉编码重排（reranker.model 指向模型目录）。"""

    _model = None
    _tokenizer = None
    _device = None
    _max_length = 512

    def __init__(self, model_path: str) -> None:
        self.model_path = model_path

    def _ensure_loaded(self) -> None:
        if CrossEncoderReranker._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        CrossEncoderReranker._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        CrossEncoderReranker._model = AutoModelForSequenceClassification.from_pretrained(
            self.model_path
        )
        CrossEncoderReranker._model.eval()
        # 长文本重排：表格行文本单块约 2-3k 字符（≈1500-2000 token），
        # 用 2048 兼顾覆盖与速度（8192 全开在后台进程偶发卡顿且无必要）
        CrossEncoderReranker._max_length = min(
            2048,
            int(getattr(CrossEncoderReranker._model.config, "max_position_embeddings", 2048)),
        )
        CrossEncoderReranker._device = "cuda" if torch.cuda.is_available() else "cpu"
        if CrossEncoderReranker._device == "cuda":
            CrossEncoderReranker._model = CrossEncoderReranker._model.to("cuda")
        logging.getLogger(__name__).info(
            "交叉编码重排模型已加载", model=self.model_path, device=CrossEncoderReranker._device
        )

    async def rerank(self, query: str, hits: list[Any], top_k: int) -> list[Any]:
        if not hits:
            return []
        self._ensure_loaded()

        def _score() -> list[tuple[float, Any]]:
            import torch

            contents = [
                getattr(h, "content", None) or (h.get("content", "") if isinstance(h, dict) else "")
                for h in hits
            ]
            scored: list[tuple[float, Any]] = []
            batch_size = 8
            for i in range(0, len(hits), batch_size):
                batch_hits = hits[i : i + batch_size]
                batch_texts = contents[i : i + batch_size]
                pairs = [[query, t] for t in batch_texts]
                enc = CrossEncoderReranker._tokenizer(
                    pairs,
                    padding=True,
                    truncation=True,
                    max_length=CrossEncoderReranker._max_length,
                    return_tensors="pt",
                )
                if CrossEncoderReranker._device == "cuda":
                    enc = {k: v.to("cuda") for k, v in enc.items()}
                with torch.no_grad():
                    logits = CrossEncoderReranker._model(**enc).logits
                if CrossEncoderReranker._device == "cuda":
                    logits = logits.cpu()
                for h, score in zip(batch_hits, logits[:, 0].tolist()):
                    # 分数写回 hit（供抽取上下文阈值过滤使用）
                    if isinstance(h, dict):
                        h["rerank_score"] = float(score)
                    else:
                        try:
                            h.rerank_score = float(score)
                        except Exception:
                            pass
                    scored.append((float(score), h))
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored

        try:
            # 后台进程偶发死锁兜底：超时回退直通，避免整任务卡死
            scored = await asyncio.wait_for(asyncio.to_thread(_score), timeout=60)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "交叉编码重排超时，回退直通", model=self.model_path
            )
            return hits[:top_k]
        return [h for _, h in scored[:top_k]]


def get_reranker(retrieval_config: dict | None = None):
    """按全局配置选择重排器：enabled=true 且 model 非空时用交叉编码精排。"""
    rcfg = retrieval_config or {}
    rer = rcfg.get("reranker") or {}
    if rer.get("enabled"):
        model = (rer.get("model") or "").strip()
        if model:
            return CrossEncoderReranker(model)
        return SemanticReranker()
    return passthrough_reranker


passthrough_reranker = PassthroughReranker()
