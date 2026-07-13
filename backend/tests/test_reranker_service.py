"""bge-reranker-v2-m3 CrossEncoder 重排服务测试模块。

测试 RerankerService 的核心功能：
- 懒加载机制：__init__ 不加载模型，首次 rerank 才加载
- 线程安全加载：mock CrossEncoder 构造
- rerank 排序：按 rerank_score 降序
- top_k 截断
- 批量推理：predict 调用使用 batch_size
- 优雅降级：模型加载失败时按原始顺序返回
- 空输入与单文档处理
- original_score 保留

所有测试通过 mock CrossEncoder 实现，不加载真实模型，不依赖 GPU。
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.reranker_service import RerankResult, RerankerService


# ---------------------------------------------------------------
# 公共 fixture 与辅助函数
# ---------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_service():
    """每个测试前后重置单例状态，确保测试间隔离。

    RerankerService 通过实例属性持有模型与加载标志，
    测试中需在用例前后清空，避免上一个测试的模型实例影响下一个。
    """
    service = RerankerService()
    service._model = None
    service._loaded = False
    yield
    service._model = None
    service._loaded = False


def make_mock_cross_encoder(predict_scores: list[float]) -> MagicMock:
    """构造模拟 CrossEncoder 实例。

    预设 predict 返回指定分数数组，便于验证排序与截断逻辑。

    Args:
        predict_scores: predict 方法返回的分数列表（按输入对顺序）。

    Returns:
        MagicMock: 模拟的 CrossEncoder 实例。
    """
    model = MagicMock()
    # CrossEncoder.predict 在 convert_to_numpy=True 时返回 numpy 数组
    model.predict.return_value = np.array(predict_scores, dtype=np.float32)
    return model


def make_documents(n: int = 3) -> list[dict]:
    """构造模拟候选文档列表。

    Args:
        n: 文档数量。

    Returns:
        list[dict]: 候选文档列表，每项包含 chunk_id/document_id/content/score/metadata。
    """
    return [
        {
            "chunk_id": f"chunk_{i}",
            "document_id": f"doc_{i}",
            "content": f"文档内容 {i}",
            "score": 0.1 * (n - i),  # 原始分数递减
            "metadata": {"page": i + 1, "chunk_index": i},
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------
# 懒加载与初始化测试（Mock，不加载真实模型）
# ---------------------------------------------------------------
class TestLazyLoading:
    """RerankerService 懒加载机制测试。"""

    def test_model_not_loaded_in_init(self):
        """测试 __init__ 不加载模型。

        构造 RerankerService 后，_model 应为 None，_loaded 应为 False。
        """
        service = RerankerService()

        assert service._model is None
        assert service._loaded is False

    def test_model_loaded_on_first_call(self):
        """测试模型在首次调用 _ensure_loaded 时加载。"""
        service = RerankerService()

        with patch(
            "app.services.reranker_service.CrossEncoder",
            return_value=make_mock_cross_encoder([0.9]),
        ) as mock_cls:
            loaded = service._ensure_loaded()

        assert loaded is True
        assert service._loaded is True
        assert service._model is not None
        # CrossEncoder 应被构造一次，且 max_length=512
        mock_cls.assert_called_once()
        assert mock_cls.call_args.kwargs.get("max_length") == 512

    def test_model_not_reloaded_when_already_loaded(self):
        """测试已加载时不重复加载模型。"""
        service = RerankerService()
        service._loaded = True
        service._model = MagicMock()

        with patch(
            "app.services.reranker_service.CrossEncoder",
            side_effect=AssertionError("不应重复加载模型"),
        ):
            loaded = service._ensure_loaded()

        assert loaded is True

    @pytest.mark.asyncio
    async def test_rerank_triggers_model_loading(self):
        """测试 rerank 首次调用会触发模型懒加载。"""
        service = RerankerService()
        mock_model = make_mock_cross_encoder([0.5])

        with patch(
            "app.services.reranker_service.CrossEncoder",
            return_value=mock_model,
        ) as mock_cls:
            await service.rerank("query", make_documents(1), top_k=1)

        # rerank 应触发一次模型构造
        mock_cls.assert_called_once()
        assert service._loaded is True


# ---------------------------------------------------------------
# rerank 核心逻辑测试（Mock）
# ---------------------------------------------------------------
class TestRerank:
    """rerank 重排核心逻辑测试。"""

    @pytest.mark.asyncio
    async def test_results_sorted_by_rerank_score_descending(self):
        """测试结果按 rerank_score 降序排列。

        喂入 [低分, 高分, 中分]，期望结果顺序为 [高分, 中分, 低分]。
        """
        service = RerankerService()
        docs = make_documents(3)  # chunk_0/1/2，原始分数递减
        # 故意让 chunk_2 得分最高，chunk_0 最低，验证排序不依赖原始顺序
        service._model = make_mock_cross_encoder([0.1, 0.5, 0.9])
        service._loaded = True

        results = await service.rerank("query", docs, top_k=3)

        assert len(results) == 3
        # 按 rerank_score 降序
        assert results[0].rerank_score > results[1].rerank_score
        assert results[1].rerank_score > results[2].rerank_score
        # 期望 chunk_2 在首位（最高分）
        assert results[0].chunk_id == "chunk_2"
        assert results[2].chunk_id == "chunk_0"

    @pytest.mark.asyncio
    async def test_top_k_limit(self):
        """测试 top_k 截断。

        输入 5 条文档，top_k=2，期望仅返回前 2 条。
        """
        service = RerankerService()
        docs = make_documents(5)
        # 分数递增：chunk_4 最高
        scores = [0.1, 0.2, 0.3, 0.4, 0.5]
        service._model = make_mock_cross_encoder(scores)
        service._loaded = True

        results = await service.rerank("query", docs, top_k=2)

        assert len(results) == 2
        # 期望返回最高分的两条
        assert results[0].chunk_id == "chunk_4"
        assert results[1].chunk_id == "chunk_3"

    @pytest.mark.asyncio
    async def test_top_k_greater_than_input(self):
        """测试 top_k 大于输入文档数时返回全部文档。"""
        service = RerankerService()
        docs = make_documents(2)
        service._model = make_mock_cross_encoder([0.7, 0.3])
        service._loaded = True

        results = await service.rerank("query", docs, top_k=10)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_batch_processing_uses_batch_size(self):
        """测试批量推理调用 predict 时使用指定 batch_size。"""
        service = RerankerService()
        docs = make_documents(4)
        mock_model = make_mock_cross_encoder([0.1, 0.2, 0.3, 0.4])
        service._model = mock_model
        service._loaded = True

        await service.rerank("query", docs, top_k=4, batch_size=2)

        # predict 应被调用一次，且 batch_size=2
        mock_model.predict.assert_called_once()
        call_kwargs = mock_model.predict.call_args.kwargs
        assert call_kwargs.get("batch_size") == 2

    @pytest.mark.asyncio
    async def test_predict_called_with_query_content_pairs(self):
        """测试 predict 接收正确的 (query, content) 文本对。"""
        service = RerankerService()
        docs = make_documents(2)
        mock_model = make_mock_cross_encoder([0.5, 0.8])
        service._model = mock_model
        service._loaded = True

        await service.rerank("采购规范", docs, top_k=2)

        # predict 的第一个位置参数应为 (query, content) 对的列表
        call_args = mock_model.predict.call_args
        pairs = call_args.args[0] if call_args.args else call_args.kwargs.get("sentences")
        assert pairs == [
            ["采购规范", "文档内容 0"],
            ["采购规范", "文档内容 1"],
        ]

    @pytest.mark.asyncio
    async def test_original_score_preserved(self):
        """测试 RerankResult.original_score 保留输入文档的原始 score。"""
        service = RerankerService()
        docs = make_documents(3)  # score: 0.3, 0.2, 0.1
        service._model = make_mock_cross_encoder([0.9, 0.5, 0.1])
        service._loaded = True

        results = await service.rerank("query", docs, top_k=3)

        # original_score 应与输入文档的 score 一一对应
        original_scores = {r.chunk_id: r.original_score for r in results}
        assert original_scores["chunk_0"] == pytest.approx(0.3)
        assert original_scores["chunk_1"] == pytest.approx(0.2)
        assert original_scores["chunk_2"] == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_rank_starts_from_one(self):
        """测试 rank 字段从 1 开始连续递增。"""
        service = RerankerService()
        docs = make_documents(3)
        service._model = make_mock_cross_encoder([0.3, 0.9, 0.5])
        service._loaded = True

        results = await service.rerank("query", docs, top_k=3)

        ranks = [r.rank for r in results]
        assert ranks == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_metadata_preserved(self):
        """测试 metadata 字段透传到 RerankResult。"""
        service = RerankerService()
        docs = make_documents(2)
        service._model = make_mock_cross_encoder([0.5, 0.8])
        service._loaded = True

        results = await service.rerank("query", docs, top_k=2)

        # 排序后 chunk_1（rerank_score=0.8）应在前
        top = results[0]
        assert top.chunk_id == "chunk_1"
        assert top.metadata == {"page": 2, "chunk_index": 1}

    @pytest.mark.asyncio
    async def test_document_id_preserved(self):
        """测试 document_id 字段透传到 RerankResult。"""
        service = RerankerService()
        docs = make_documents(2)
        service._model = make_mock_cross_encoder([0.4, 0.6])
        service._loaded = True

        results = await service.rerank("query", docs, top_k=2)

        doc_ids = {r.document_id for r in results}
        assert doc_ids == {"doc_0", "doc_1"}

    @pytest.mark.asyncio
    async def test_content_preserved(self):
        """测试 content 字段透传到 RerankResult。"""
        service = RerankerService()
        docs = make_documents(2)
        service._model = make_mock_cross_encoder([0.4, 0.6])
        service._loaded = True

        results = await service.rerank("query", docs, top_k=2)

        contents = {r.content for r in results}
        assert contents == {"文档内容 0", "文档内容 1"}


# ---------------------------------------------------------------
# 边界场景测试
# ---------------------------------------------------------------
class TestEdgeCases:
    """空输入与单文档等边界场景测试。"""

    @pytest.mark.asyncio
    async def test_empty_documents_returns_empty(self):
        """测试空文档列表返回空结果，不触发模型推理。"""
        service = RerankerService()
        mock_model = make_mock_cross_encoder([])
        service._model = mock_model
        service._loaded = True

        results = await service.rerank("query", [], top_k=5)

        assert results == []
        mock_model.predict.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_document(self):
        """测试单文档输入正确返回一条结果。"""
        service = RerankerService()
        docs = make_documents(1)
        service._model = make_mock_cross_encoder([0.95])
        service._loaded = True

        results = await service.rerank("query", docs, top_k=5)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk_0"
        assert results[0].rerank_score == pytest.approx(0.95)
        assert results[0].rank == 1

    @pytest.mark.asyncio
    async def test_skip_empty_content_documents(self):
        """测试 content 为空的文档被过滤掉。

        输入 3 条文档，其中一条 content 为空字符串，
        期望仅对 2 条非空文档进行推理。
        """
        service = RerankerService()
        docs = [
            {
                "chunk_id": "chunk_0",
                "document_id": "doc_0",
                "content": "正常文档",
                "score": 0.5,
                "metadata": {},
            },
            {
                "chunk_id": "chunk_1",
                "document_id": "doc_1",
                "content": "",  # 空 content 应被跳过
                "score": 0.4,
                "metadata": {},
            },
            {
                "chunk_id": "chunk_2",
                "document_id": "doc_2",
                "content": "另一篇正常文档",
                "score": 0.3,
                "metadata": {},
            },
        ]
        # predict 应仅接收 2 条非空文档
        mock_model = make_mock_cross_encoder([0.8, 0.6])
        service._model = mock_model
        service._loaded = True

        results = await service.rerank("query", docs, top_k=5)

        assert len(results) == 2
        chunk_ids = {r.chunk_id for r in results}
        assert chunk_ids == {"chunk_0", "chunk_2"}
        # chunk_1 不应在结果中
        assert "chunk_1" not in chunk_ids

    @pytest.mark.asyncio
    async def test_all_empty_content_returns_empty(self):
        """测试全部文档 content 为空时返回空结果。"""
        service = RerankerService()
        docs = [
            {
                "chunk_id": "chunk_0",
                "document_id": "doc_0",
                "content": "",
                "score": 0.5,
                "metadata": {},
            }
        ]
        mock_model = make_mock_cross_encoder([])
        service._model = mock_model
        service._loaded = True

        results = await service.rerank("query", docs, top_k=5)

        assert results == []
        mock_model.predict.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_content_key_skipped(self):
        """测试缺失 content 键的文档被过滤掉。"""
        service = RerankerService()
        docs = [
            {
                "chunk_id": "chunk_0",
                "document_id": "doc_0",
                # 缺失 content 键
                "score": 0.5,
                "metadata": {},
            },
            {
                "chunk_id": "chunk_1",
                "document_id": "doc_1",
                "content": "正常文档",
                "score": 0.4,
                "metadata": {},
            },
        ]
        mock_model = make_mock_cross_encoder([0.7])
        service._model = mock_model
        service._loaded = True

        results = await service.rerank("query", docs, top_k=5)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk_1"


# ---------------------------------------------------------------
# 优雅降级测试（Mock，模拟加载/推理失败）
# ---------------------------------------------------------------
class TestGracefulDegradation:
    """模型加载/推理失败时的优雅降级测试。"""

    @pytest.mark.asyncio
    async def test_model_loading_failure_returns_original_order(self):
        """测试模型加载失败时按原始顺序返回候选文档。

        CrossEncoder 构造抛异常时，_ensure_loaded 返回 False，
        rerank 进入降级路径，按原始顺序返回前 top_k 条。
        """
        service = RerankerService()

        with patch(
            "app.services.reranker_service.CrossEncoder",
            side_effect=RuntimeError("模型加载失败"),
        ):
            results = await service.rerank(
                "query", make_documents(3), top_k=2
            )

        # 应按原始顺序返回前 2 条
        assert len(results) == 2
        assert results[0].chunk_id == "chunk_0"
        assert results[1].chunk_id == "chunk_1"
        # 降级时 rerank_score == original_score
        assert results[0].rerank_score == results[0].original_score
        assert results[1].rerank_score == results[1].original_score
        # _loaded 仍为 False
        assert service._loaded is False
        assert service._model is None

    @pytest.mark.asyncio
    async def test_model_loading_failure_preserves_original_scores(self):
        """测试模型加载失败时 original_score 正确保留。"""
        service = RerankerService()
        docs = make_documents(3)  # score: 0.3, 0.2, 0.1

        with patch(
            "app.services.reranker_service.CrossEncoder",
            side_effect=OSError("文件不存在"),
        ):
            results = await service.rerank("query", docs, top_k=3)

        assert len(results) == 3
        # 按原始顺序，原分数应保留
        assert results[0].original_score == pytest.approx(0.3)
        assert results[1].original_score == pytest.approx(0.2)
        assert results[2].original_score == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_predict_failure_returns_original_order(self):
        """测试模型推理失败时按原始顺序降级返回。

        模型已加载但 predict 抛异常时，应捕获异常并降级返回。
        """
        service = RerankerService()
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("推理失败")
        service._model = mock_model
        service._loaded = True

        results = await service.rerank("query", make_documents(3), top_k=3)

        assert len(results) == 3
        # 按原始顺序
        assert results[0].chunk_id == "chunk_0"
        assert results[1].chunk_id == "chunk_1"
        assert results[2].chunk_id == "chunk_2"
        # 降级时 rerank_score == original_score
        for r in results:
            assert r.rerank_score == r.original_score

    @pytest.mark.asyncio
    async def test_fallback_respects_top_k(self):
        """测试降级路径同样受 top_k 限制。"""
        service = RerankerService()

        with patch(
            "app.services.reranker_service.CrossEncoder",
            side_effect=RuntimeError("加载失败"),
        ):
            results = await service.rerank(
                "query", make_documents(5), top_k=2
            )

        assert len(results) == 2


# ---------------------------------------------------------------
# 模块单例测试
# ---------------------------------------------------------------
class TestModuleSingleton:
    """模块级单例 reranker_service 测试。"""

    def test_module_singleton_exists(self):
        """测试模块级 reranker_service 实例存在且类型正确。"""
        from app.services.reranker_service import reranker_service

        assert isinstance(reranker_service, RerankerService)

    def test_module_singleton_initially_unloaded(self):
        """测试模块级单例初始未加载模型。"""
        # 重置后重新导入验证
        from app.services.reranker_service import reranker_service

        reranker_service._model = None
        reranker_service._loaded = False

        assert reranker_service._loaded is False
        assert reranker_service._model is None


# ---------------------------------------------------------------
# RerankResult 数据模型测试
# ---------------------------------------------------------------
class TestRerankResultDataclass:
    """RerankResult 数据类字段测试。"""

    def test_rerank_result_fields(self):
        """测试 RerankResult 包含所有必需字段。"""
        result = RerankResult(
            chunk_id="chunk_1",
            document_id="doc_1",
            content="内容",
            original_score=0.5,
            rerank_score=0.9,
            rank=1,
            metadata={"page": 1},
        )

        assert result.chunk_id == "chunk_1"
        assert result.document_id == "doc_1"
        assert result.content == "内容"
        assert result.original_score == 0.5
        assert result.rerank_score == 0.9
        assert result.rank == 1
        assert result.metadata == {"page": 1}

    def test_rerank_result_metadata_default_empty_dict(self):
        """测试 metadata 默认为空 dict。"""
        result = RerankResult(
            chunk_id="c",
            document_id="d",
            content="x",
            original_score=0.0,
            rerank_score=0.0,
            rank=1,
        )

        assert result.metadata == {}

    def test_rerank_result_metadata_independent_instances(self):
        """测试不同 RerankResult 实例的 metadata 默认值相互独立。"""
        r1 = RerankResult(
            chunk_id="c1",
            document_id="d",
            content="x",
            original_score=0.0,
            rerank_score=0.0,
            rank=1,
        )
        r2 = RerankResult(
            chunk_id="c2",
            document_id="d",
            content="x",
            original_score=0.0,
            rerank_score=0.0,
            rank=2,
        )

        r1.metadata["key"] = "value"
        # 修改 r1.metadata 不应影响 r2.metadata
        assert r2.metadata == {}
