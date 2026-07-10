"""bge-m3 嵌入服务测试模块。

测试 EmbeddingService 的核心功能：
- 懒加载机制：__init__ 不加载模型
- 单例模式：多次构造返回同一实例
- embed()：Dense (1024) + Sparse 向量生成与形状校验
- embed_query()：单查询编码返回 dense + sparse
- sparse 格式转换：{str: float16} → Milvus {indices: [int], values: [float]}

测试分为两组：
1. **Mock 测试**（TestLazyLoading / TestSingleton / TestSparseConversion / TestEmptyInput）：
   不依赖真实模型与 GPU，通过 mock 验证逻辑正确性。
2. **真实模型测试**（TestRealModelEmbed）：
   加载真实 bge-m3 模型验证向量维度与格式。
"""

from collections import defaultdict
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.services.embedding_service import EmbeddingService


# ---------------------------------------------------------------
# 公共 fixture
# ---------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前后重置单例状态，确保测试间隔离。

    EmbeddingService 采用类级单例（_instance / _model / _loaded 为类属性），
    测试中需在用例前后清空，避免上一个测试的模型实例影响下一个。
    """
    EmbeddingService._instance = None
    EmbeddingService._model = None
    EmbeddingService._loaded = False
    yield
    EmbeddingService._instance = None
    EmbeddingService._model = None
    EmbeddingService._loaded = False


# ---------------------------------------------------------------
# 懒加载与单例测试（Mock，不加载真实模型）
# ---------------------------------------------------------------
class TestLazyLoading:
    """EmbeddingService 懒加载机制测试。"""

    def test_model_not_loaded_in_init(self):
        """测试 __init__ 不加载模型。

        构造 EmbeddingService 后，_model 应为 None，_loaded 应为 False。
        """
        service = EmbeddingService()

        assert service._model is None
        assert service._loaded is False

    def test_singleton_returns_same_instance(self):
        """测试单例模式返回同一实例。"""
        s1 = EmbeddingService()
        s2 = EmbeddingService()

        assert s1 is s2

    def test_load_model_sets_loaded_flag(self):
        """测试 _load_model 将 _loaded 置为 True（mock 模型加载）。"""
        service = EmbeddingService()

        # mock BGEM3FlagModel 构造，避免加载真实模型
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.services.embedding_service.BGEM3FlagModel",
                lambda *args, **kwargs: MagicMock(),
            )
            service._load_model()

        assert service._model is not None
        assert service._loaded is True

    def test_load_model_skipped_when_already_loaded(self):
        """测试已加载时 _load_model 直接返回不重复加载。"""
        service = EmbeddingService()
        service._loaded = True
        service._model = MagicMock()

        # 再次调用应直接返回，不触发 BGEM3FlagModel 构造
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.services.embedding_service.BGEM3FlagModel",
                lambda *args, **kwargs: pytest.fail("不应重复加载模型"),
            )
            service._load_model()

        assert service._loaded is True


# ---------------------------------------------------------------
# Sparse 格式转换测试（Mock）
# ---------------------------------------------------------------
class TestSparseConversion:
    """稀疏向量格式转换测试（使用 mock，不加载真实模型）。"""

    @pytest.mark.asyncio
    async def test_sparse_indices_are_int(self):
        """测试 sparse indices 转换为 int 类型。

        FlagEmbedding 返回的 lexical_weights 键为字符串，需转换为 int。
        """
        service = EmbeddingService()
        service._model = MagicMock()
        service._loaded = True

        # 模拟 FlagEmbedding.encode 的返回：token_id 为字符串
        service._model.encode.return_value = {
            "dense_vecs": np.zeros((1, 1024), dtype=np.float32),
            "lexical_weights": [{"100": np.float16(0.5), "200": np.float16(0.3)}],
        }

        result = await service.embed(["测试"])

        sparse_milvus = result["sparse_indices"][0]
        assert all(isinstance(i, int) for i in sparse_milvus["indices"])
        assert sparse_milvus["indices"] == [100, 200]

    @pytest.mark.asyncio
    async def test_sparse_values_are_float(self):
        """测试 sparse values 转换为 float 类型。

        FlagEmbedding 返回的 lexical_weights 值为 np.float16，需转换为 float。
        """
        service = EmbeddingService()
        service._model = MagicMock()
        service._loaded = True

        service._model.encode.return_value = {
            "dense_vecs": np.zeros((1, 1024), dtype=np.float32),
            "lexical_weights": [{"10": np.float16(0.8)}],
        }

        result = await service.embed(["测试"])

        sparse_milvus = result["sparse_indices"][0]
        assert all(isinstance(v, float) for v in sparse_milvus["values"])
        # np.float16(0.8) 精度有限，转 float 后约为 0.7998，使用近似比较
        assert sparse_milvus["values"] == [pytest.approx(0.8, abs=0.01)]

    @pytest.mark.asyncio
    async def test_sparse_milvus_format_structure(self):
        """测试 sparse 转换为 Milvus 格式的结构正确性。"""
        service = EmbeddingService()
        service._model = MagicMock()
        service._loaded = True

        # 使用 defaultdict 模拟 FlagEmbedding 的真实返回类型
        sparse_input = defaultdict(lambda: np.float16(0.0))
        sparse_input["42"] = np.float16(0.1)
        sparse_input["99"] = np.float16(0.9)

        service._model.encode.return_value = {
            "dense_vecs": np.zeros((1, 1024), dtype=np.float32),
            "lexical_weights": [sparse_input],
        }

        result = await service.embed(["测试"])

        item = result["sparse_indices"][0]
        assert "indices" in item
        assert "values" in item
        assert len(item["indices"]) == 2
        assert len(item["values"]) == 2
        assert set(item["indices"]) == {42, 99}

    @pytest.mark.asyncio
    async def test_batch_sparse_conversion(self):
        """测试批量 sparse 转换，每条文本独立转换。"""
        service = EmbeddingService()
        service._model = MagicMock()
        service._loaded = True

        service._model.encode.return_value = {
            "dense_vecs": np.zeros((2, 1024), dtype=np.float32),
            "lexical_weights": [
                {"1": np.float16(0.1)},
                {"2": np.float16(0.2), "3": np.float16(0.3)},
            ],
        }

        result = await service.embed(["文本1", "文本2"])

        assert len(result["sparse_indices"]) == 2
        assert result["sparse_indices"][0]["indices"] == [1]
        assert set(result["sparse_indices"][1]["indices"]) == {2, 3}


# ---------------------------------------------------------------
# 空输入测试（Mock）
# ---------------------------------------------------------------
class TestEmptyInput:
    """空输入处理测试。"""

    @pytest.mark.asyncio
    async def test_embed_empty_list_returns_empty(self):
        """测试空列表输入返回空结果，不触发模型推理。"""
        service = EmbeddingService()
        service._model = MagicMock()
        service._loaded = True

        result = await service.embed([])

        assert result["dense_vectors"].shape == (0, 1024)
        assert result["sparse_vectors"] == []
        assert result["sparse_indices"] == []
        # 不应调用模型 encode
        service._model.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_documents_empty(self):
        """测试 embed_documents 空列表返回空结果。"""
        service = EmbeddingService()
        service._model = MagicMock()
        service._loaded = True

        result = await service.embed_documents([])

        assert result["dense_vectors"].shape == (0, 1024)
        assert result["sparse_indices"] == []


# ---------------------------------------------------------------
# 真实模型测试（加载真实 bge-m3 模型）
# ---------------------------------------------------------------
class TestRealModelEmbed:
    """真实 bge-m3 模型嵌入测试。

    这组测试加载真实模型，验证向量维度与格式符合预期。
    模型路径来自 settings.EMBEDDING_MODEL_PATH。
    """

    def test_model_loads_correctly(self):
        """测试模型可以正确加载。"""
        service = EmbeddingService()
        service._load_model()

        assert service._model is not None
        assert service._loaded is True

    @pytest.mark.asyncio
    async def test_embed_single_text_dense_shape(self):
        """测试单文本编码 - dense 维度为 (1, 1024)。"""
        service = EmbeddingService()
        result = await service.embed(["这是一个测试文本"])

        assert result["dense_vectors"].shape == (1, 1024)
        assert isinstance(result["dense_vectors"], np.ndarray)

    @pytest.mark.asyncio
    async def test_embed_single_text_sparse_nonempty(self):
        """测试单文本编码 - sparse 非空。"""
        service = EmbeddingService()
        result = await service.embed(["这是一个测试文本"])

        sparse = result["sparse_vectors"][0]
        assert len(sparse) > 0  # 应有词法权重

    @pytest.mark.asyncio
    async def test_embed_batch_shapes(self):
        """测试批量编码 - dense 形状 (N, 1024)。"""
        service = EmbeddingService()
        texts = ["文档一", "文档二", "文档三"]
        result = await service.embed(texts)

        assert result["dense_vectors"].shape == (3, 1024)
        assert len(result["sparse_vectors"]) == 3
        assert len(result["sparse_indices"]) == 3

    @pytest.mark.asyncio
    async def test_embed_query_returns_dense_and_sparse(self):
        """测试 embed_query 同时返回 dense 和 sparse 向量。"""
        service = EmbeddingService()
        result = await service.embed_query("检索查询")

        # dense 向量
        assert "dense_vector" in result
        assert result["dense_vector"].shape == (1024,)

        # sparse 向量
        assert "sparse_vector" in result
        assert len(result["sparse_vector"]) > 0

        # Milvus 格式 sparse
        assert "sparse_for_milvus" in result
        milvus_sparse = result["sparse_for_milvus"]
        assert "indices" in milvus_sparse
        assert "values" in milvus_sparse
        assert all(isinstance(i, int) for i in milvus_sparse["indices"])
        assert all(isinstance(v, float) for v in milvus_sparse["values"])

    @pytest.mark.asyncio
    async def test_embed_query_sparse_indices_values_match(self):
        """测试 embed_query 的 sparse_indices 与 sparse_vector 一致。"""
        service = EmbeddingService()
        result = await service.embed_query("测试一致性")

        sparse_vec = result["sparse_vector"]
        milvus_sparse = result["sparse_for_milvus"]

        # 两个表示应包含相同数量的 token
        assert len(sparse_vec) == len(milvus_sparse["indices"])
        assert len(milvus_sparse["indices"]) == len(milvus_sparse["values"])

    @pytest.mark.asyncio
    async def test_dense_vectors_normalized(self):
        """测试 dense 向量已归一化（L2 范数约为 1）。"""
        service = EmbeddingService()
        result = await service.embed(["归一化测试"])

        dense = result["dense_vectors"][0]
        norm = float(np.linalg.norm(dense))
        # bge-m3 默认对 dense 向量做 L2 归一化，范数应接近 1
        assert abs(norm - 1.0) < 0.01, f"dense 向量范数 {norm} 不接近 1"

    @pytest.mark.asyncio
    async def test_embed_documents_batch(self):
        """测试 embed_documents 批量编码。"""
        service = EmbeddingService()
        texts = ["文档内容一", "文档内容二"]
        result = await service.embed_documents(texts)

        assert result["dense_vectors"].shape == (2, 1024)
        assert len(result["sparse_indices"]) == 2
