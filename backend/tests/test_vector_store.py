"""Milvus 向量库封装测试模块。

测试 VectorStore 的核心功能：
- RRF 融合逻辑：纯函数测试，不依赖 Milvus
- 空结果处理：Dense/Sparse 为空时的融合行为
- 分数计算：RRF 公式正确性验证
- 插入数据格式：字段顺序与向量转换
- 懒加载与单例：模块导入不连接
- hybrid_search / delete_by_doc_id：Mock Collection 验证调用参数

测试通过 mock Milvus Collection 实现，不依赖真实 Milvus 服务。
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pymilvus.client.search_result import Hit

from app.services.vector_store import VectorStore


# ---------------------------------------------------------------
# 公共 fixture 与辅助函数
# ---------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前后重置单例状态，确保测试间隔离。

    VectorStore 采用类级单例（_instance / _collection / _connected 为类属性），
    测试中需在用例前后清空，避免上一个测试的连接状态影响下一个。
    """
    VectorStore._instance = None
    VectorStore._collection = None
    VectorStore._connected = False
    yield
    VectorStore._instance = None
    VectorStore._collection = None
    VectorStore._connected = False


def make_hit(
    pk: int,
    distance: float = 0.9,
    chunk_id: str = "chunk_1",
    text: str = "示例文本",
    doc_id: str = "doc_1",
    title_chain: str = "卷 > 章 > 节",
    metadata: dict | None = None,
) -> Hit:
    """构造模拟的 Milvus 检索 Hit 对象。

    按 pymilvus 3.0.0 的 Hit 结构构造，pk_name="id" 与 Collection schema 一致。
    Hit 继承自 dict，hit.id 返回主键值，hit.entity 返回自身，
    hit.entity.to_dict()["entity"] 返回输出字段字典。

    Args:
        pk: 主键 ID。
        distance: 检索距离/分数。
        chunk_id: 分块唯一标识。
        text: 分块原文。
        doc_id: 所属文档 ID。
        title_chain: 文档标题层级链。
        metadata: 扩展元信息。

    Returns:
        Hit: 构造的 Hit 对象。
    """
    if metadata is None:
        metadata = {"page": 1}
    return Hit(
        {
            "id": pk,
            "distance": distance,
            "entity": {
                "chunk_id": chunk_id,
                "text": text,
                "doc_id": doc_id,
                "title_chain": title_chain,
                "metadata": metadata,
            },
        },
        pk_name="id",
    )


def make_mock_collection():
    """构造模拟的 Milvus Collection 对象。

    返回 MagicMock，预设 num_entities 属性，用于测试中替换真实 Collection。
    """
    mock = MagicMock()
    mock.num_entities = 100
    return mock


# ---------------------------------------------------------------
# RRF 融合逻辑测试（纯函数，不依赖 Milvus）
# ---------------------------------------------------------------
class TestRRFFusion:
    """RRF (Reciprocal Rank Fusion) 融合逻辑测试。

    直接调用 _reciprocal_rank_fusion 方法，使用模拟 Hit 对象，
    不需要真实 Milvus 连接。
    """

    def test_rrf_combines_dense_and_sparse(self):
        """测试 RRF 正确合并 Dense 和 Sparse 两路结果。

        Dense 和 Sparse 各返回 3 条不同结果，融合后应有 6 条。
        """
        store = VectorStore()

        dense_hits = [
            make_hit(pk=1, chunk_id="d1"),
            make_hit(pk=2, chunk_id="d2"),
            make_hit(pk=3, chunk_id="d3"),
        ]
        sparse_hits = [
            make_hit(pk=4, chunk_id="s1"),
            make_hit(pk=5, chunk_id="s2"),
            make_hit(pk=6, chunk_id="s3"),
        ]

        results = store._reciprocal_rank_fusion(
            dense_hits, sparse_hits, top_k=10
        )

        # 6 条不同结果应全部保留
        assert len(results) == 6
        # 所有 chunk_id 应在结果中
        chunk_ids = {r["chunk_id"] for r in results}
        assert chunk_ids == {"d1", "d2", "d3", "s1", "s2", "s3"}

    def test_rrf_with_both_empty(self):
        """测试 Dense 和 Sparse 均为空时返回空列表。"""
        store = VectorStore()

        results = store._reciprocal_rank_fusion([], [], top_k=10)

        assert results == []

    def test_rrf_with_empty_dense(self):
        """测试 Dense 为空、Sparse 有结果时的融合。

        此时结果应完全来自 Sparse，且分数为 1/(k + rank)。
        """
        store = VectorStore()

        sparse_hits = [
            make_hit(pk=10, chunk_id="s1"),
            make_hit(pk=11, chunk_id="s2"),
        ]

        results = store._reciprocal_rank_fusion([], sparse_hits, top_k=10)

        assert len(results) == 2
        assert results[0]["chunk_id"] == "s1"
        assert results[1]["chunk_id"] == "s2"
        # rank 从 1 开始
        assert results[0]["rank"] == 1
        assert results[1]["rank"] == 2

    def test_rrf_with_empty_sparse(self):
        """测试 Sparse 为空、Dense 有结果时的融合。

        此时结果应完全来自 Dense，且分数为 1/(k + rank)。
        """
        store = VectorStore()

        dense_hits = [
            make_hit(pk=20, chunk_id="d1"),
            make_hit(pk=21, chunk_id="d2"),
        ]

        results = store._reciprocal_rank_fusion(dense_hits, [], top_k=10)

        assert len(results) == 2
        assert results[0]["chunk_id"] == "d1"
        assert results[1]["chunk_id"] == "d2"

    def test_rrf_single_result_in_dense(self):
        """测试 Dense 仅一条结果、Sparse 为空。"""
        store = VectorStore()

        dense_hits = [make_hit(pk=1, chunk_id="only_dense")]

        results = store._reciprocal_rank_fusion(dense_hits, [], top_k=10)

        assert len(results) == 1
        assert results[0]["chunk_id"] == "only_dense"
        # Dense rank=1, k=60 → score = 1/(60+1) = 1/61
        assert results[0]["score"] == pytest.approx(1.0 / 61)

    def test_rrf_single_result_in_sparse(self):
        """测试 Sparse 仅一条结果、Dense 为空。"""
        store = VectorStore()

        sparse_hits = [make_hit(pk=2, chunk_id="only_sparse")]

        results = store._reciprocal_rank_fusion([], sparse_hits, top_k=10)

        assert len(results) == 1
        assert results[0]["chunk_id"] == "only_sparse"
        # Sparse rank=1, k=60 → score = 1/(60+1) = 1/61
        assert results[0]["score"] == pytest.approx(1.0 / 61)

    def test_rrf_score_calculation(self):
        """测试 RRF 分数计算公式正确性。

        RRF 公式: score(d) = Σ 1/(k + rank_i(d))
        k=60（标准参数）。

        场景：pk=1 在 Dense rank=1、Sparse rank=2，
        score = 1/(60+1) + 1/(60+2) = 1/61 + 1/62
        """
        store = VectorStore()

        dense_hits = [
            make_hit(pk=1, chunk_id="overlap"),
            make_hit(pk=2, chunk_id="d_only"),
        ]
        sparse_hits = [
            make_hit(pk=3, chunk_id="s_only"),
            make_hit(pk=1, chunk_id="overlap"),  # 与 Dense 重叠
        ]

        results = store._reciprocal_rank_fusion(dense_hits, sparse_hits, top_k=10)

        # pk=1 在两路都出现，分数应最高
        assert results[0]["chunk_id"] == "overlap"
        expected_score = 1.0 / 61 + 1.0 / 62  # dense_rank=1, sparse_rank=2
        assert results[0]["score"] == pytest.approx(expected_score)

    def test_rrf_overlapping_doc_gets_higher_score(self):
        """测试同时出现在两路结果中的文档分数更高。

        pk=1 在 Dense rank=1 和 Sparse rank=1，
        pk=2 仅在 Dense rank=2。
        pk=1 的分数应大于 pk=2。
        """
        store = VectorStore()

        dense_hits = [
            make_hit(pk=1, chunk_id="both"),
            make_hit(pk=2, chunk_id="dense_only"),
        ]
        sparse_hits = [
            make_hit(pk=1, chunk_id="both"),  # 与 Dense 重叠
        ]

        results = store._reciprocal_rank_fusion(dense_hits, sparse_hits, top_k=10)

        # both 的分数 = 1/61 + 1/61 = 2/61
        # dense_only 的分数 = 1/62
        both_score = next(r["score"] for r in results if r["chunk_id"] == "both")
        only_score = next(r["score"] for r in results if r["chunk_id"] == "dense_only")
        assert both_score > only_score

    def test_rrf_results_sorted_by_score_descending(self):
        """测试 RRF 结果按分数降序排列。"""
        store = VectorStore()

        # 构造 5 条 Dense 结果，无 Sparse 结果
        dense_hits = [make_hit(pk=i, chunk_id=f"d{i}") for i in range(5)]

        results = store._reciprocal_rank_fusion(dense_hits, [], top_k=10)

        # 分数应递减
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_top_k_limit(self):
        """测试 RRF 结果截取 top_k 条。"""
        store = VectorStore()

        dense_hits = [make_hit(pk=i, chunk_id=f"d{i}") for i in range(10)]
        sparse_hits = [make_hit(pk=i + 100, chunk_id=f"s{i}") for i in range(10)]

        results = store._reciprocal_rank_fusion(dense_hits, sparse_hits, top_k=5)

        assert len(results) == 5
        # rank 从 1 到 5
        ranks = [r["rank"] for r in results]
        assert ranks == [1, 2, 3, 4, 5]

    def test_rrf_rank_starts_from_one(self):
        """测试结果排名从 1 开始。"""
        store = VectorStore()

        results = store._reciprocal_rank_fusion(
            [make_hit(pk=1)], [make_hit(pk=2)], top_k=5
        )

        assert results[0]["rank"] == 1
        assert results[-1]["rank"] == len(results)

    def test_rrf_entity_fields_extracted(self):
        """测试融合结果正确提取 entity 字段。"""
        store = VectorStore()

        dense_hits = [
            make_hit(
                pk=1,
                chunk_id="chunk_abc",
                text="这是文本内容",
                doc_id="doc_xyz",
                title_chain="卷一 > 第一章",
                metadata={"page": 5, "bbox": [0, 0, 100, 100]},
            )
        ]

        results = store._reciprocal_rank_fusion(dense_hits, [], top_k=5)

        assert results[0]["id"] == 1
        assert results[0]["chunk_id"] == "chunk_abc"
        assert results[0]["text"] == "这是文本内容"
        assert results[0]["doc_id"] == "doc_xyz"
        assert results[0]["title_chain"] == "卷一 > 第一章"
        assert results[0]["metadata"] == {"page": 5, "bbox": [0, 0, 100, 100]}

    def test_rrf_default_k_is_60(self):
        """测试 RRF 默认 k 参数为 60。"""
        store = VectorStore()

        # rank=1 的 Dense 结果 → score = 1/(60+1) = 1/61
        results = store._reciprocal_rank_fusion(
            [make_hit(pk=1)], [], top_k=5
        )

        assert results[0]["score"] == pytest.approx(1.0 / 61)

    def test_rrf_custom_k(self):
        """测试自定义 k 参数影响分数计算。"""
        store = VectorStore()

        # k=1 → rank=1 的 score = 1/(1+1) = 1/2
        results = store._reciprocal_rank_fusion(
            [make_hit(pk=1)], [], top_k=5, k=1
        )

        assert results[0]["score"] == pytest.approx(1.0 / 2)


# ---------------------------------------------------------------
# 懒加载与单例测试（不连接 Milvus）
# ---------------------------------------------------------------
class TestLazyLoading:
    """VectorStore 懒加载与单例模式测试。"""

    def test_init_does_not_connect(self):
        """测试 __init__ 不连接 Milvus。

        构造 VectorStore 后，_connected 应为 False，_collection 应为 None。
        """
        store = VectorStore()

        assert store._connected is False
        assert store._collection is None

    def test_singleton_returns_same_instance(self):
        """测试单例模式返回同一实例。"""
        s1 = VectorStore()
        s2 = VectorStore()

        assert s1 is s2

    def test_ensure_connected_calls_connect(self):
        """测试 _ensure_connected 触发连接。"""
        store = VectorStore()

        with patch.object(VectorStore, "_connect") as mock_connect:
            store._ensure_connected()
            mock_connect.assert_called_once()

    def test_ensure_connected_skipped_when_already_connected(self):
        """测试已连接时 _ensure_connected 不重复连接。"""
        store = VectorStore()
        store._connected = True

        with patch.object(VectorStore, "_connect") as mock_connect:
            store._ensure_connected()
            mock_connect.assert_not_called()


# ---------------------------------------------------------------
# 插入数据格式测试（Mock Collection）
# ---------------------------------------------------------------
class TestInsertFormatting:
    """insert 方法数据格式化测试。

    通过 mock Collection 验证数据组织方式与调用参数，
    不依赖真实 Milvus。
    """

    @pytest.mark.asyncio
    async def test_insert_data_field_order(self):
        """测试插入数据按 schema 字段顺序组织。

        Collection schema 字段顺序：
        chunk_id, text, dense_vector, sparse_vector, doc_id, title_chain, metadata
        """
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        mock_result = MagicMock()
        mock_result.primary_keys = [1, 2]
        mock_result.insert_count = 2
        store._collection.insert.return_value = mock_result

        chunks = [
            {
                "chunk_id": "chunk_1",
                "text": "文本一",
                "dense_vector": np.ones(1024, dtype=np.float32),
                "sparse_vector": {"indices": [1, 2], "values": [0.1, 0.2]},
                "doc_id": "doc_1",
                "title_chain": "标题一",
                "metadata": {"page": 1},
            },
            {
                "chunk_id": "chunk_2",
                "text": "文本二",
                "dense_vector": np.zeros(1024, dtype=np.float32),
                "sparse_vector": {"indices": [3], "values": [0.3]},
                "doc_id": "doc_2",
                "title_chain": "标题二",
                "metadata": {"page": 2},
            },
        ]

        await store.insert(chunks)

        # 验证 insert 被调用
        store._collection.insert.assert_called_once()
        call_args = store._collection.insert.call_args
        data = call_args[0][0]  # 第一个位置参数

        # 验证字段顺序：chunk_id, text, dense_vector, sparse_vector, doc_id, title_chain, metadata
        assert data[0] == ["chunk_1", "chunk_2"]       # chunk_id
        assert data[1] == ["文本一", "文本二"]          # text
        assert data[3] == [                             # sparse_vector
            {"indices": [1, 2], "values": [0.1, 0.2]},
            {"indices": [3], "values": [0.3]},
        ]
        assert data[4] == ["doc_1", "doc_2"]            # doc_id
        assert data[5] == ["标题一", "标题二"]           # title_chain
        assert data[6] == [{"page": 1}, {"page": 2}]    # metadata

    @pytest.mark.asyncio
    async def test_insert_dense_vector_converted_to_list(self):
        """测试 dense_vector 从 np.ndarray 转换为 list。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        mock_result = MagicMock()
        mock_result.primary_keys = [1]
        mock_result.insert_count = 1
        store._collection.insert.return_value = mock_result

        dense = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        chunks = [
            {
                "chunk_id": "c1",
                "text": "t1",
                "dense_vector": dense,
                "sparse_vector": {"indices": [1], "values": [0.5]},
                "doc_id": "d1",
                "title_chain": "tc",
                "metadata": {},
            }
        ]

        await store.insert(chunks)

        data = store._collection.insert.call_args[0][0]
        # dense_vector（索引 2）应被转换为 list
        assert data[2] == [[1.0, 2.0, 3.0]]

    @pytest.mark.asyncio
    async def test_insert_returns_primary_keys(self):
        """测试 insert 返回插入记录的主键列表。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        mock_result = MagicMock()
        mock_result.primary_keys = [10, 20, 30]
        mock_result.insert_count = 3
        store._collection.insert.return_value = mock_result

        chunks = [
            {
                "chunk_id": f"c{i}",
                "text": f"t{i}",
                "dense_vector": np.zeros(3, dtype=np.float32),
                "sparse_vector": {"indices": [1], "values": [0.5]},
                "doc_id": f"d{i}",
                "title_chain": "tc",
                "metadata": {},
            }
            for i in range(3)
        ]

        result = await store.insert(chunks)

        assert result == [10, 20, 30]

    @pytest.mark.asyncio
    async def test_insert_triggers_connection(self):
        """测试 insert 在未连接时触发懒加载连接。"""
        store = VectorStore()

        with patch.object(VectorStore, "_connect") as mock_connect:
            store._collection = make_mock_collection()
            store._connected = True  # 模拟已连接，避免真实连接

            mock_result = MagicMock()
            mock_result.primary_keys = []
            mock_result.insert_count = 0
            store._collection.insert.return_value = mock_result

            await store.insert([])

        # insert 空列表也应正常调用 collection.insert
        store._collection.insert.assert_called_once()


# ---------------------------------------------------------------
# 混合检索测试（Mock Collection）
# ---------------------------------------------------------------
class TestHybridSearch:
    """hybrid_search 混合检索测试。

    通过 mock Collection.search 验证两路检索调用与 RRF 融合结果。
    """

    @pytest.mark.asyncio
    async def test_hybrid_search_calls_both_dense_and_sparse(self):
        """测试 hybrid_search 同时调用 Dense 和 Sparse 检索。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        # 构造模拟 search 结果：search() 返回 SearchResult（list-like），
        # SearchResult[0] 返回 Hits（list-like），Hits 内为 Hit 对象
        dense_hits = [make_hit(pk=1, chunk_id="d1")]
        sparse_hits = [make_hit(pk=2, chunk_id="s1")]

        store._collection.search.side_effect = [
            [dense_hits],   # SearchResult = [Hits]
            [sparse_hits],  # SearchResult = [Hits]
        ]

        query_dense = np.ones(1024, dtype=np.float32)
        query_sparse = {"indices": [1, 2], "values": [0.1, 0.2]}

        results = await store.hybrid_search(query_dense, query_sparse, top_k=5)

        # search 应被调用两次（Dense + Sparse）
        assert store._collection.search.call_count == 2
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_hybrid_search_dense_params(self):
        """测试 Dense 检索使用正确的 anns_field 和 metric_type。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        store._collection.search.side_effect = [
            [[make_hit(pk=1)]],
            [[make_hit(pk=2)]],
        ]

        await store.hybrid_search(
            np.ones(1024, dtype=np.float32),
            {"indices": [1], "values": [0.5]},
            top_k=5,
            nprobe=32,
        )

        # 第一次调用是 Dense 检索
        dense_call = store._collection.search.call_args_list[0]
        assert dense_call.kwargs["anns_field"] == "dense_vector"
        assert dense_call.kwargs["param"]["metric_type"] == "IP"
        assert dense_call.kwargs["param"]["params"]["nprobe"] == 32
        assert dense_call.kwargs["limit"] == 10  # top_k * 2

    @pytest.mark.asyncio
    async def test_hybrid_search_sparse_params(self):
        """测试 Sparse 检索使用正确的 anns_field 和 metric_type。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        store._collection.search.side_effect = [
            [[make_hit(pk=1)]],
            [[make_hit(pk=2)]],
        ]

        await store.hybrid_search(
            np.ones(1024, dtype=np.float32),
            {"indices": [1], "values": [0.5]},
            top_k=5,
        )

        # 第二次调用是 Sparse 检索
        sparse_call = store._collection.search.call_args_list[1]
        assert sparse_call.kwargs["anns_field"] == "sparse_vector"
        assert sparse_call.kwargs["param"]["metric_type"] == "IP"
        assert sparse_call.kwargs["limit"] == 10  # top_k * 2

    @pytest.mark.asyncio
    async def test_hybrid_search_limit_is_top_k_times_two(self):
        """测试两路检索的 limit 均为 top_k * 2。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        store._collection.search.side_effect = [
            [[make_hit(pk=1)]],
            [[make_hit(pk=2)]],
        ]

        await store.hybrid_search(
            np.ones(1024, dtype=np.float32),
            {"indices": [1], "values": [0.5]},
            top_k=7,
        )

        for call in store._collection.search.call_args_list:
            assert call.kwargs["limit"] == 14  # 7 * 2

    @pytest.mark.asyncio
    async def test_hybrid_search_output_fields(self):
        """测试检索请求包含所有必要的 output_fields。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        store._collection.search.side_effect = [
            [[make_hit(pk=1)]],
            [[make_hit(pk=2)]],
        ]

        await store.hybrid_search(
            np.ones(1024, dtype=np.float32),
            {"indices": [1], "values": [0.5]},
            top_k=5,
        )

        expected_fields = ["chunk_id", "text", "doc_id", "title_chain", "metadata"]
        for call in store._collection.search.call_args_list:
            assert set(call.kwargs["output_fields"]) == set(expected_fields)

    @pytest.mark.asyncio
    async def test_hybrid_search_default_nprobe(self):
        """测试默认 nprobe 为 16。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        store._collection.search.side_effect = [
            [[make_hit(pk=1)]],
            [[make_hit(pk=2)]],
        ]

        await store.hybrid_search(
            np.ones(1024, dtype=np.float32),
            {"indices": [1], "values": [0.5]},
        )

        dense_call = store._collection.search.call_args_list[0]
        assert dense_call.kwargs["param"]["params"]["nprobe"] == 16


# ---------------------------------------------------------------
# 删除测试（Mock Collection）
# ---------------------------------------------------------------
class TestDeleteByDocId:
    """delete_by_doc_id 删除测试。"""

    @pytest.mark.asyncio
    async def test_delete_calls_collection_delete(self):
        """测试按 doc_id 删除调用 collection.delete。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        mock_result = MagicMock()
        mock_result.delete_count = 5
        store._collection.delete.return_value = mock_result

        deleted = await store.delete_by_doc_id("doc_123")

        store._collection.delete.assert_called_once()
        assert deleted == 5

    @pytest.mark.asyncio
    async def test_delete_expr_contains_doc_id(self):
        """测试删除表达式包含正确的 doc_id。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        mock_result = MagicMock()
        mock_result.delete_count = 1
        store._collection.delete.return_value = mock_result

        await store.delete_by_doc_id("target_doc")

        call_args = store._collection.delete.call_args
        expr = call_args.kwargs["expr"]
        assert 'target_doc' in expr
        assert 'doc_id' in expr

    @pytest.mark.asyncio
    async def test_delete_returns_zero_when_no_match(self):
        """测试无匹配记录时返回 0。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        mock_result = MagicMock()
        mock_result.delete_count = 0
        store._collection.delete.return_value = mock_result

        deleted = await store.delete_by_doc_id("nonexistent")

        assert deleted == 0


# ---------------------------------------------------------------
# 统计记录数测试（Mock Collection）
# ---------------------------------------------------------------
class TestCount:
    """count 统计记录数测试。"""

    @pytest.mark.asyncio
    async def test_count_total_uses_num_entities(self):
        """测试不指定 doc_id 时使用 num_entities。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._collection.num_entities = 500
        store._connected = True

        count = await store.count()

        assert count == 500
        # 不应调用 query
        store._collection.query.assert_not_called()

    @pytest.mark.asyncio
    async def test_count_by_doc_id_uses_query(self):
        """测试指定 doc_id 时使用 query + count(*) 统计。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        store._collection.query.return_value = [{"count(*)": 7}]

        count = await store.count(doc_id="doc_abc")

        assert count == 7
        store._collection.query.assert_called_once()
        call_kwargs = store._collection.query.call_args.kwargs
        assert "doc_abc" in call_kwargs["expr"]
        assert "count(*)" in call_kwargs["output_fields"]

    @pytest.mark.asyncio
    async def test_count_by_doc_id_returns_zero_on_empty(self):
        """测试指定 doc_id 无匹配时返回 0。"""
        store = VectorStore()
        store._collection = make_mock_collection()
        store._connected = True

        store._collection.query.return_value = []

        count = await store.count(doc_id="nonexistent")

        assert count == 0


# ---------------------------------------------------------------
# 连接错误处理测试
# ---------------------------------------------------------------
class TestConnectionError:
    """连接错误处理测试。"""

    def test_connect_raises_runtime_error_on_failure(self):
        """测试 Milvus 连接失败时抛出 RuntimeError。"""
        store = VectorStore()

        with patch(
            "app.services.vector_store.connections.connect",
            side_effect=ConnectionError("Connection refused"),
        ):
            with pytest.raises(RuntimeError, match="无法连接 Milvus"):
                store._connect()

        # 连接失败后 _connected 应保持 False
        assert store._connected is False

    def test_ensure_connected_propagates_connection_error(self):
        """测试 _ensure_connected 传播连接错误。"""
        store = VectorStore()

        with patch.object(VectorStore, "_connect") as mock_connect:
            mock_connect.side_effect = RuntimeError("无法连接 Milvus")
            with pytest.raises(RuntimeError, match="无法连接 Milvus"):
                store._ensure_connected()
