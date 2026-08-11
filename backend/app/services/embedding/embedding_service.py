"""BGE-M3 嵌入服务（S3/D2，dense only）。

设计：
- 单例 + 懒加载：模块导入无 GPU 副作用，首次 embed/warmup 才加载模型；
- transformers 直接加载（AutoTokenizer + AutoModel），CLS 池化 + L2 归一化，
  与 FlagEmbedding M3Embedder 默认 cls pooling 及官方余弦语义对齐；
- asyncio.Lock 串行化 + asyncio.to_thread：避免多线程并发触发 torch
  MKL fork 崩溃（原版已验证的防护策略），同时不阻塞事件循环；
- 可插拔：EmbeddingProvider 抽象，模型路径/设备/精度/批次/长度全部配置化。

与旧项目 embedding_service.py 的关系：沿用单例/懒加载/锁/批量参数结论，
但实现改为 transformers 直载（不依赖 FlagEmbedding，X3），仅产出 dense，
异常与配置全部按当前项目规范。
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(ABC):
    """嵌入提供者抽象（可插拔，未来可换 Qwen3-Embedding 等）。"""

    @abstractmethod
    def encode(
        self, texts: list[str], batch_size: int, max_length: int
    ) -> np.ndarray:
        """编码文本列表，返回 (N, dim) float32 已归一化向量。"""


class BgeM3TransformersProvider(EmbeddingProvider):
    """BGE-M3 的 transformers 直载实现。

    dense 向量 = last_hidden_state[:, 0]（CLS token），L2 归一化。
    与 FlagEmbedding 的 M3Embedder 默认 pooling_method="cls" 对齐。
    """

    def __init__(self, model_dir: str, device: str, fp16: bool) -> None:
        self.model_dir = model_dir
        self.device = device
        self.fp16 = fp16
        self._tokenizer = None
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        model_path = Path(self.model_dir)
        if not model_path.exists() or not (model_path / "config.json").exists():
            raise RuntimeError(
                f"嵌入模型不存在：{model_path}。请先运行 "
                "scripts/download_embedding_model.py 下载 BGE-M3 权重。"
            )
        from transformers import AutoModel, AutoTokenizer

        logger.info("开始加载 BGE-M3 嵌入模型", model_dir=self.model_dir)
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        self._model = AutoModel.from_pretrained(str(model_path))
        if self.fp16 and self.device.startswith("cuda"):
            self._model = self._model.half()
        self._model.to(self.device)
        self._model.eval()
        logger.info("BGE-M3 嵌入模型加载完成", device=self.device, fp16=self.fp16)

    def encode(
        self, texts: list[str], batch_size: int, max_length: int
    ) -> np.ndarray:
        import torch
        import torch.nn.functional as F

        if not texts:
            return np.empty((0, settings.EMBEDDING_DIM), dtype=np.float32)

        self.load()
        assert self._tokenizer is not None and self._model is not None

        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            inputs = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                last_hidden_state = self._model(**inputs).last_hidden_state
            # CLS 池化 + L2 归一化（与 FlagEmbedding cls pooling 对齐）
            vecs = F.normalize(last_hidden_state[:, 0], p=2, dim=1)
            vectors.append(vecs.float().cpu().numpy())

        # texts 非空时循环至少执行一次，vectors 恒非空（空输入已在入口短路）
        return np.vstack(vectors)


class EmbeddingService:
    """嵌入服务门面：单例、懒加载、串行锁、批量编码。"""

    _instance: EmbeddingService | None = None
    _provider: EmbeddingProvider | None = None
    _embed_lock: asyncio.Lock | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._embed_lock is None:
            self._embed_lock = asyncio.Lock()

    def _ensure_provider(self) -> EmbeddingProvider:
        if self._provider is None:
            self._provider = BgeM3TransformersProvider(
                model_dir=settings.EMBEDDING_MODEL_DIR,
                device=settings.EMBEDDING_DEVICE,
                fp16=settings.EMBEDDING_FP16,
            )
        return self._provider

    async def embed(
        self,
        texts: list[str],
        batch_size: int | None = None,
        max_length: int | None = None,
    ) -> list[list[float]]:
        """编码文本列表，返回 (N, dim) 归一化向量列表。

        空列表短路（不触发模型加载/加锁）。
        """
        if not texts:
            return []
        batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        max_length = max_length or settings.EMBEDDING_MAX_LENGTH
        assert self._embed_lock is not None
        async with self._embed_lock:
            provider = self._ensure_provider()
            vectors = await asyncio.to_thread(
                provider.encode, texts, batch_size, max_length
            )
        return [v.tolist() for v in vectors]

    @property
    def dimension(self) -> int:
        return settings.EMBEDDING_DIM

    async def warmup(self) -> None:
        """预热：加载模型并跑一次小批量。"""
        await self.embed(["预热文本"])


embedding_service = EmbeddingService()
