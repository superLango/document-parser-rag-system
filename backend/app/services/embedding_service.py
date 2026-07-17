"""bge-m3 嵌入服务模块。

本模块基于 BAAI/bge-m3 模型，通过单次前向推理同时输出：
- Dense 向量（1024 维，已归一化）
- Sparse 向量（词法权重，{token_id: weight}）

按方案 7.6 节实现关键约束：
- 使用 BAAI/bge-m3 模型（非 bge-base-zh-v1.5）
- batch_size=4 防止显存溢出
- 设置 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
- 使用 FlagEmbedding 库获取 Dense+Sparse 向量

采用单例模式确保模型只加载一次，通过 asyncio.to_thread
将同步推理调用包装为非阻塞异步接口。模型与 OCR 服务一致采用
懒加载：模块导入时不占用 GPU 资源，首次调用 embed / warmup 时才加载。

使用示例：
    from app.services.embedding_service import embedding_service

    # 编码查询
    result = await embedding_service.embed_query("检索文本")
    dense_vec = result["dense_vector"]          # np.ndarray (1024,)
    sparse_vec = result["sparse_vector"]        # {token_id: weight, ...}
    milvus_sparse = result["sparse_for_milvus"] # {"indices": [...], "values": [...]}

    # 批量编码文档
    batch = await embedding_service.embed_documents(["文档1", "文档2"])
"""

# 必须在导入 torch（FlagEmbedding 间接导入）之前设置 CUDA 内存分配策略
import os

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import asyncio
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    """bge-m3 嵌入服务，同时输出 Dense 与 Sparse 向量。

    采用单例模式：模型实例在首次实际调用 ``embed`` / ``warmup`` 时加载并复用，
    避免重复加载占用显存，同时确保模块导入时不产生 GPU 副作用。
    同步推理调用通过 asyncio.to_thread 包装为异步接口，避免阻塞事件循环。

    Attributes:
        _instance: 单例实例。
        _model: BGEM3FlagModel 模型实例，懒加载。
        _loaded: 模型是否已完成加载。
    """

    _instance: "EmbeddingService | None" = None
    _model: Any = None
    _loaded: bool = False

    def __new__(cls) -> "EmbeddingService":
        """单例模式 - 模型只加载一次。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化嵌入服务，不加载模型（懒加载）。

        模型加载推迟到首次 ``embed`` / ``warmup`` 调用，确保模块导入时
        不占用 GPU 资源。单例模式下 ``__init__`` 仅在首次构造时生效。
        """

    def _load_model(self) -> None:
        """加载 bge-m3 模型。

        从配置项 EMBEDDING_MODEL_PATH 加载模型，使用半精度（fp16）
        减少显存占用。模型在 GPU 上运行。已加载时直接返回，避免重复加载。
        """
        if self._loaded:
            return
        model_path = settings.EMBEDDING_MODEL_PATH
        logger.info("开始加载 bge-m3 嵌入模型", model_path=model_path)
        from FlagEmbedding import BGEM3FlagModel  # 延迟导入，避免模块导入阶段即触发重型依赖

        self._model = BGEM3FlagModel(
            model_path,
            use_fp16=True,  # 半精度减少显存
            device="cuda",
        )
        self._loaded = True
        logger.info("bge-m3 嵌入模型加载完成", model_path=model_path)

    def _ensure_model(self) -> None:
        """确保模型已加载（懒加载入口）。"""
        if not self._loaded:
            self._load_model()

    async def embed(self, texts: list[str], batch_size: int | None = None) -> dict[str, Any]:
        """同时生成 Dense 和 Sparse 向量。

        通过 asyncio.to_thread 将同步 encode 调用交由线程池执行，
        避免阻塞事件循环。bge-m3 默认对 Dense 向量做 L2 归一化。

        Args:
            texts: 待编码文本列表。
            batch_size: 批次大小，默认使用配置项 EMBEDDING_BATCH_SIZE（=16），
                利用批量推理加速（P2.2 优化，从 4 提升到 16）。

        Returns:
            dict: 包含以下键：
                - dense_vectors: np.ndarray (N, 1024)，已归一化的密集向量。
                - sparse_vectors: list[dict]，原始稀疏权重 [{token_id: weight}, ...]。
                - sparse_indices: list[dict]，Milvus SPARSE_FLOAT_VECTOR 格式，
                  [{"indices": [int, ...], "values": [float, ...]}, ...]。
        """
        self._ensure_model()
        if batch_size is None:
            batch_size = settings.EMBEDDING_BATCH_SIZE

        # 空列表直接返回空结果，避免触发模型推理
        if not texts:
            return {
                "dense_vectors": np.empty((0, 1024), dtype=np.float32),
                "sparse_vectors": [],
                "sparse_indices": [],
            }

        # asyncio.to_thread 包装同步调用，防止阻塞事件循环
        result = await asyncio.to_thread(
            self._model.encode,
            texts,
            batch_size=batch_size,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,  # 不需要 ColBERT 向量
        )

        dense = result["dense_vecs"]  # np.ndarray (N, 1024)
        sparse = result["lexical_weights"]  # list[dict {token_id(str): weight(float16)}]

        # 转换 sparse 为 Milvus SPARSE_FLOAT_VECTOR 格式
        # 注意：FlagEmbedding 返回的 token_id 为字符串、weight 为 np.float16，需做类型转换
        sparse_for_milvus: list[dict[str, list]] = []
        for s in sparse:
            indices = [int(k) for k in s.keys()]
            values = [float(v) for v in s.values()]
            sparse_for_milvus.append({"indices": indices, "values": values})

        return {
            "dense_vectors": dense,
            "sparse_vectors": sparse,
            "sparse_indices": sparse_for_milvus,
        }

    async def embed_query(self, query: str) -> dict[str, Any]:
        """编码单个查询文本。

        Args:
            query: 待编码的查询文本。

        Returns:
            dict: 包含以下键：
                - dense_vector: np.ndarray (1024,)，已归一化的密集向量。
                - sparse_vector: dict，原始稀疏权重 {token_id: weight}。
                - sparse_for_milvus: dict，Milvus 格式
                  {"indices": [int, ...], "values": [float, ...]}。
        """
        result = await self.embed([query])
        return {
            "dense_vector": result["dense_vectors"][0],
            "sparse_vector": result["sparse_vectors"][0],
            "sparse_for_milvus": result["sparse_indices"][0],
        }

    async def embed_documents(self, texts: list[str]) -> dict[str, Any]:
        """编码文档列表（批量）。

        使用配置项 EMBEDDING_BATCH_SIZE（=16）作为批次大小。

        Args:
            texts: 待编码文档文本列表。

        Returns:
            dict: 同 embed() 返回结构。
        """
        return await self.embed(texts, batch_size=settings.EMBEDDING_BATCH_SIZE)

    def warmup(self) -> None:
        """预热模型，完成首次推理以加载 CUDA 内核。

        建议在应用启动阶段调用，避免首个请求承担预热延迟。
        """
        self._ensure_model()
        self._model.encode(["预热"], batch_size=1)
        logger.info("bge-m3 嵌入模型预热完成")


# 模块级单例，懒加载，导入时不加载模型
embedding_service = EmbeddingService()
