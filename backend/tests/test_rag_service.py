"""RAG 编排服务测试模块。

测试 RAGService 的核心功能：
- 完整流程：查询理解 → 检索 → 重排 → 生成 → 响应
- 流式查询：逐块 yield LLM 输出
- 功能开关：use_graph / use_reranker 控制流程跳过
- 错误处理：各阶段失败时的优雅降级
- 边界情况：空检索结果
- 引用构建：citations 正确填充
- 上下文组装：格式与内容正确性

所有下游服务通过 monkeypatch mock，不依赖真实模型或数据库。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from app.services.query_service import QueryAnalysis, QueryEntity
from app.services.rag_service import (
    Citation,
    RAGResponse,
    embedding_service,
    graph_store,
    llm_service,
    query_service,
    rag_service,
    reranker_service,
    vector_store,
)
from app.services.reranker_service import RerankResult


# ---------------------------------------------------------------
# 测试辅助函数：构造模拟数据
# ---------------------------------------------------------------
def make_query_analysis(
    intent: str = "document_search",
    rewritten_query: str = "304不锈钢 化学成分",
) -> QueryAnalysis:
    """构造模拟的查询分析结果。

    Args:
        intent: 意图类型。
        rewritten_query: 重写后的查询。

    Returns:
        QueryAnalysis: 包含实体、重写查询的完整分析结果。
    """
    return QueryAnalysis(
        intent=intent,
        entities=[
            QueryEntity(text="304不锈钢", type="material"),
            QueryEntity(text="GB/T 1220", type="standard"),
        ],
        rewritten_query=rewritten_query,
        sub_queries=[],
        confidence=0.95,
    )


def make_embed_result():
    """构造模拟的嵌入结果。"""
    return {
        "dense_vector": np.zeros(1024, dtype=np.float32),
        "sparse_vector": {},
        "sparse_for_milvus": {"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]},
    }


def make_vector_results(n: int = 3) -> list[dict]:
    """构造模拟的向量检索结果（vector_store 原始格式）。

    Args:
        n: 结果数量。

    Returns:
        list[dict]: 检索结果列表，含 chunk_id/text/doc_id/score/metadata。
    """
    return [
        {
            "id": i,
            "chunk_id": f"chunk_{i}",
            "text": f"304不锈钢的化学成分包括铬、镍等元素。片段{i}",
            "doc_id": f"doc_{i}",
            "title_chain": f"标准 > 304 > {i}",
            "metadata": {"page": i, "chunk_index": i},
            "score": 0.9 - i * 0.1,
            "rank": i,
        }
        for i in range(1, n + 1)
    ]


def make_rerank_results(n: int = 3) -> list[RerankResult]:
    """构造模拟的重排结果。

    Args:
        n: 结果数量。

    Returns:
        list[RerankResult]: 重排结果列表，按 rerank_score 降序。
    """
    return [
        RerankResult(
            chunk_id=f"chunk_{i}",
            document_id=f"doc_{i}",
            content=f"重排后内容{i}",
            original_score=0.8 - i * 0.1,
            rerank_score=0.95 - i * 0.05,
            rank=i,
            metadata={"page": i, "chunk_index": i},
        )
        for i in range(1, n + 1)
    ]


def make_graph_nodes(n: int = 2) -> list[dict]:
    """构造模拟的图谱节点搜索结果。"""
    return [
        {
            "id": i,
            "name": "304不锈钢" if i == 1 else f"实体_{i}",
            "labels": ["Material"] if i == 1 else ["Standard"],
        }
        for i in range(1, n + 1)
    ]


def make_graph_subgraph() -> dict:
    """构造模拟的子图查询结果。"""
    return {
        "nodes": [{"id": 1, "name": "304不锈钢", "labels": ["Material"]}],
        "edges": [
            {"source": "304不锈钢", "target": "GB/T 1220", "type": "执行标准"}
        ],
    }


# ---------------------------------------------------------------
# 公共 fixture：mock 所有下游服务
# ---------------------------------------------------------------
@pytest.fixture
def mock_services(monkeypatch):
    """mock 所有下游服务单例方法，避免真实模型或数据库调用。

    返回 SimpleNamespace 包含所有 mock 对象，测试中可通过修改
    mock 的 return_value / side_effect 来定制行为。
    """
    # 查询理解
    mock_analyze = AsyncMock(return_value=make_query_analysis())
    monkeypatch.setattr(query_service, "analyze", mock_analyze)

    # 嵌入服务
    mock_embed = AsyncMock(return_value=make_embed_result())
    monkeypatch.setattr(embedding_service, "embed_query", mock_embed)

    # 向量检索
    mock_search = AsyncMock(return_value=make_vector_results())
    monkeypatch.setattr(vector_store, "hybrid_search", mock_search)

    # 重排服务
    mock_rerank = AsyncMock(return_value=make_rerank_results())
    monkeypatch.setattr(reranker_service, "rerank", mock_rerank)

    # 图谱节点搜索
    mock_search_nodes = AsyncMock(return_value=make_graph_nodes())
    monkeypatch.setattr(graph_store, "search_nodes", mock_search_nodes)

    # 图谱子图查询
    mock_get_subgraph = AsyncMock(return_value=make_graph_subgraph())
    monkeypatch.setattr(graph_store, "get_subgraph", mock_get_subgraph)

    # LLM 文本生成
    mock_generate = AsyncMock(return_value="这是生成的回答")
    monkeypatch.setattr(llm_service, "generate", mock_generate)

    # LLM 流式生成（异步生成器函数，用 MagicMock + side_effect 包装）
    async def _stream_gen(*args, **kwargs):
        """模拟流式生成，逐块 yield 文本。"""
        for chunk in ["这是", "流式", "回答"]:
            yield chunk

    mock_stream = MagicMock(side_effect=_stream_gen)
    monkeypatch.setattr(llm_service, "stream_generate", mock_stream)

    return SimpleNamespace(
        analyze=mock_analyze,
        embed=mock_embed,
        search=mock_search,
        rerank=mock_rerank,
        search_nodes=mock_search_nodes,
        get_subgraph=mock_get_subgraph,
        generate=mock_generate,
        stream=mock_stream,
    )


# ---------------------------------------------------------------
# 完整流程测试
# ---------------------------------------------------------------
class TestFullPipeline:
    """完整 RAG 流程测试。"""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, mock_services):
        """测试完整流程：查询理解 → 嵌入 → 检索 → 重排 → 生成 → 响应。

        验证：
        - 所有下游服务被正确调用
        - 响应字段正确填充
        - 嵌入使用重写后的查询
        - 重排接收转换后的文档列表
        """
        response = await rag_service.query(
            "304不锈钢的化学成分", top_k=3
        )

        # 响应基本字段
        assert isinstance(response, RAGResponse)
        assert response.answer == "这是生成的回答"
        assert response.intent == "document_search"
        assert response.retrieval_count == 3
        assert response.rerank_count == 3
        assert len(response.citations) == 3

        # 实体列表
        assert len(response.entities) == 2
        assert response.entities[0] == {"text": "304不锈钢", "type": "material"}

        # query_analysis 包含完整信息
        assert response.query_analysis["intent"] == "document_search"
        assert response.query_analysis["rewritten_query"] == "304不锈钢 化学成分"

        # 查询理解被调用一次，参数为原始问题
        mock_services.analyze.assert_called_once_with("304不锈钢的化学成分")

        # 嵌入使用重写后的查询
        mock_services.embed.assert_called_once()
        embed_arg = mock_services.embed.call_args.args[0]
        assert embed_arg == "304不锈钢 化学成分"

        # 向量检索被调用
        mock_services.search.assert_called_once()

        # 重排被调用，documents 为转换后的向量结果
        mock_services.rerank.assert_called_once()
        rerank_kwargs = mock_services.rerank.call_args.kwargs
        assert rerank_kwargs["query"] == "304不锈钢 化学成分"
        assert rerank_kwargs["top_k"] == 3
        documents = rerank_kwargs["documents"]
        assert len(documents) == 3
        # 验证 vector_store 格式已转换（text→content, doc_id→document_id）
        assert documents[0]["content"] == "304不锈钢的化学成分包括铬、镍等元素。片段1"
        assert documents[0]["document_id"] == "doc_1"

        # 图谱检索被调用（use_graph 默认 True）
        mock_services.search_nodes.assert_called()
        mock_services.get_subgraph.assert_called_once()

        # LLM 生成被调用
        mock_services.generate.assert_called_once()


# ---------------------------------------------------------------
# 流式查询测试
# ---------------------------------------------------------------
class TestStreaming:
    """流式查询测试。"""

    @pytest.mark.asyncio
    async def test_streaming(self, mock_services):
        """测试流式生成：逐块 yield LLM 输出。

        验证：
        - 收集到的分片拼接后等于完整回答
        - 使用 stream_generate 而非 generate
        """
        chunks: list[str] = []
        async for chunk in rag_service.query_stream("304不锈钢的化学成分"):
            chunks.append(chunk)

        assert chunks == ["这是", "流式", "回答"]

        # 应使用 stream_generate 而非 generate
        mock_services.stream.assert_called_once()
        mock_services.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_streaming_vector_failure(self, mock_services):
        """测试流式查询中向量检索失败时返回错误信息。"""
        mock_services.search.side_effect = RuntimeError("Milvus 不可用")

        chunks: list[str] = []
        async for chunk in rag_service.query_stream("304不锈钢的化学成分"):
            chunks.append(chunk)

        # 应返回错误信息
        assert len(chunks) == 1
        assert "向量检索失败" in chunks[0]


# ---------------------------------------------------------------
# 功能开关测试
# ---------------------------------------------------------------
class TestFeatureFlags:
    """功能开关测试。"""

    @pytest.mark.asyncio
    async def test_use_graph_false(self, mock_services):
        """测试 use_graph=False 时跳过图谱检索。

        验证：
        - graph_store.search_nodes 未被调用
        - graph_store.get_subgraph 未被调用
        - 响应仍正常返回
        """
        response = await rag_service.query(
            "304不锈钢的化学成分", use_graph=False
        )

        assert response.answer == "这是生成的回答"
        mock_services.search_nodes.assert_not_called()
        mock_services.get_subgraph.assert_not_called()

    @pytest.mark.asyncio
    async def test_use_reranker_false(self, mock_services):
        """测试 use_reranker=False 时跳过重排。

        验证：
        - reranker_service.rerank 未被调用
        - 引用来源于原始向量检索结果（内容为 text 字段转换后的 content）
        - 引用分数为原始检索分数
        """
        response = await rag_service.query(
            "304不锈钢的化学成分", top_k=3, use_reranker=False
        )

        assert response.answer == "这是生成的回答"
        assert len(response.citations) == 3
        mock_services.rerank.assert_not_called()

        # 引用内容应来自向量检索结果（text → content）
        assert response.citations[0].content == "304不锈钢的化学成分包括铬、镍等元素。片段1"
        assert response.citations[0].document_id == "doc_1"
        assert response.citations[0].chunk_id == "chunk_1"
        # 原始分数 0.9 - 1*0.1 = 0.8
        assert response.citations[0].score == pytest.approx(0.8)
        assert response.citations[0].source == "vector"


# ---------------------------------------------------------------
# 错误处理测试
# ---------------------------------------------------------------
class TestErrorHandling:
    """各阶段错误处理测试。"""

    @pytest.mark.asyncio
    async def test_query_understanding_failure(self, mock_services):
        """测试查询理解失败时使用原始查询继续流程。

        验证：
        - 意图回退为 general
        - 嵌入使用原始问题（非重写查询）
        - 后续流程正常执行
        """
        mock_services.analyze.side_effect = Exception("LLM 不可用")

        response = await rag_service.query("304不锈钢的化学成分")

        # 意图回退为 general
        assert response.intent == "general"
        assert response.query_analysis["intent"] == "general"
        assert response.query_analysis["rewritten_query"] == "304不锈钢的化学成分"

        # 嵌入应使用原始问题（兜底分析中 rewritten_query = 原始查询）
        mock_services.embed.assert_called_once()
        embed_arg = mock_services.embed.call_args.args[0]
        assert embed_arg == "304不锈钢的化学成分"

        # 后续流程仍正常执行
        assert response.answer == "这是生成的回答"
        assert len(response.citations) > 0

    @pytest.mark.asyncio
    async def test_vector_search_failure(self, mock_services):
        """测试向量检索失败时返回错误信息。

        验证：
        - 响应 answer 包含错误说明
        - citations 为空
        - retrieval_count 为 0
        - LLM 未被调用
        """
        mock_services.search.side_effect = RuntimeError("Milvus 连接失败")

        response = await rag_service.query("304不锈钢的化学成分")

        assert "向量检索失败" in response.answer
        assert response.citations == []
        assert response.retrieval_count == 0
        assert response.rerank_count == 0
        # LLM 不应被调用
        mock_services.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_embedding_failure(self, mock_services):
        """测试嵌入服务失败时返回错误信息。"""
        mock_services.embed.side_effect = RuntimeError("嵌入模型未加载")

        response = await rag_service.query("304不锈钢的化学成分")

        assert "向量检索失败" in response.answer
        assert response.citations == []

    @pytest.mark.asyncio
    async def test_reranker_failure(self, mock_services):
        """测试重排失败时降级使用原始检索结果。

        验证：
        - 响应仍正常返回
        - 引用来源于原始向量检索结果
        - 引用内容为 text 字段（非重排后的内容）
        """
        mock_services.rerank.side_effect = Exception("CrossEncoder 加载失败")

        response = await rag_service.query(
            "304不锈钢的化学成分", top_k=3
        )

        assert response.answer == "这是生成的回答"
        assert len(response.citations) == 3
        # 引用内容应来自原始向量结果
        assert response.citations[0].content == "304不锈钢的化学成分包括铬、镍等元素。片段1"
        assert response.citations[0].document_id == "doc_1"

    @pytest.mark.asyncio
    async def test_graph_search_failure(self, mock_services):
        """测试图谱检索失败时跳过图谱上下文。

        验证：
        - 响应仍正常返回
        - LLM 上下文中不包含图谱信息
        """
        mock_services.search_nodes.side_effect = RuntimeError("Neo4j 不可用")

        response = await rag_service.query("304不锈钢的化学成分")

        assert response.answer == "这是生成的回答"
        assert len(response.citations) > 0

        # 检查 LLM 上下文不包含图谱信息
        prompt = mock_services.generate.call_args.kwargs["prompt"]
        assert "知识图谱信息" not in prompt

    @pytest.mark.asyncio
    async def test_graph_subgraph_failure(self, mock_services):
        """测试子图查询失败时仍使用实体信息。"""
        mock_services.get_subgraph.side_effect = RuntimeError("子图查询超时")

        response = await rag_service.query("304不锈钢的化学成分")

        assert response.answer == "这是生成的回答"
        # 实体信息应仍在上下文中
        prompt = mock_services.generate.call_args.kwargs["prompt"]
        assert "知识图谱信息" in prompt
        assert "实体:" in prompt

    @pytest.mark.asyncio
    async def test_llm_failure(self, mock_services):
        """测试 LLM 生成失败时返回包含错误信息的兜底回答。

        验证：
        - 响应 answer 包含错误说明
        - citations 仍被填充（上下文已检索）
        """
        mock_services.generate.side_effect = Exception("GPU 显存不足")

        response = await rag_service.query("304不锈钢的化学成分")

        assert "生成回答时发生错误" in response.answer
        # 引用仍被填充
        assert len(response.citations) > 0
        assert response.retrieval_count > 0

    @pytest.mark.asyncio
    async def test_llm_stream_failure(self, mock_services):
        """测试流式生成失败时 yield 错误信息。"""
        async def _error_stream(*args, **kwargs):
            yield "部分内容"
            raise RuntimeError("流式生成中断")
            yield "不应到达"  # noqa: E231

        mock_services.stream.side_effect = _error_stream

        chunks: list[str] = []
        async for chunk in rag_service.query_stream("304不锈钢的化学成分"):
            chunks.append(chunk)

        # 应包含已生成的部分内容与错误信息
        assert "部分内容" in chunks
        assert any("生成失败" in c for c in chunks)


# ---------------------------------------------------------------
# 边界情况测试
# ---------------------------------------------------------------
class TestEdgeCases:
    """边界情况测试。"""

    @pytest.mark.asyncio
    async def test_empty_search_results(self, mock_services):
        """测试空检索结果时仍调用 LLM 生成。

        验证：
        - citations 为空
        - retrieval_count 为 0
        - LLM 仍被调用（模型会说明无法找到答案）
        """
        mock_services.search.return_value = []

        response = await rag_service.query("304不锈钢的化学成分")

        assert response.citations == []
        assert response.retrieval_count == 0
        assert response.rerank_count == 0
        # LLM 仍被调用
        mock_services.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_graph_results(self, mock_services):
        """测试图谱检索返回空时上下文不含图谱部分。"""
        mock_services.search_nodes.return_value = []

        response = await rag_service.query("304不锈钢的化学成分")

        assert response.answer == "这是生成的回答"
        prompt = mock_services.generate.call_args.kwargs["prompt"]
        # 图谱检索返回空列表时，_graph_search 返回 {"entities": [], "relations": []}
        # 上下文中不会有图谱部分（entities 和 relations 均为空）
        assert "知识图谱信息" not in prompt

    @pytest.mark.asyncio
    async def test_doc_ids_filter(self, mock_services):
        """测试 doc_ids 过滤功能。

        vector_store 不支持原生 doc_ids 过滤，RAG 服务在后置过滤。
        验证：向量检索返回 3 条，过滤后 retrieval_count 为 2。
        """
        response = await rag_service.query(
            "304不锈钢的化学成分", top_k=5, doc_ids=["doc_1", "doc_2"]
        )

        # 向量检索返回 3 条，过滤后应剩 2 条
        assert response.retrieval_count == 2


# ---------------------------------------------------------------
# 引用构建测试
# ---------------------------------------------------------------
class TestCitations:
    """引用构建测试。"""

    @pytest.mark.asyncio
    async def test_citations_populated(self, mock_services):
        """测试引用正确填充。

        验证：
        - 引用数量与重排结果一致
        - 每条引用包含 document_id/chunk_id/content/score/source
        - 引用内容来自重排结果
        - source 为 "vector"
        """
        response = await rag_service.query(
            "304不锈钢的化学成分", top_k=3
        )

        assert len(response.citations) == 3

        for i, citation in enumerate(response.citations, start=1):
            assert isinstance(citation, Citation)
            assert citation.document_id == f"doc_{i}"
            assert citation.chunk_id == f"chunk_{i}"
            assert citation.content == f"重排后内容{i}"
            assert citation.score == pytest.approx(0.95 - i * 0.05)
            assert citation.source == "vector"

    @pytest.mark.asyncio
    async def test_citations_without_reranker(self, mock_services):
        """测试不使用重排时引用来自向量检索结果。"""
        response = await rag_service.query(
            "304不锈钢的化学成分", top_k=2, use_reranker=False
        )

        assert len(response.citations) == 2
        # 内容应来自向量检索的 text 字段
        assert response.citations[0].content == "304不锈钢的化学成分包括铬、镍等元素。片段1"
        assert response.citations[1].content == "304不锈钢的化学成分包括铬、镍等元素。片段2"

    @pytest.mark.asyncio
    async def test_query_analysis_in_response(self, mock_services):
        """测试响应中包含完整的查询分析信息。"""
        response = await rag_service.query("304不锈钢的化学成分")

        analysis = response.query_analysis
        assert analysis["intent"] == "document_search"
        assert analysis["rewritten_query"] == "304不锈钢 化学成分"
        assert analysis["confidence"] == 0.95
        assert len(analysis["entities"]) == 2
        assert analysis["entities"][0]["text"] == "304不锈钢"
        assert analysis["entities"][0]["type"] == "material"


# ---------------------------------------------------------------
# 上下文组装测试
# ---------------------------------------------------------------
class TestContextAssembly:
    """上下文组装格式测试。"""

    @pytest.mark.asyncio
    async def test_context_format(self, mock_services):
        """测试上下文组装格式正确。

        验证上下文包含：
        - 文档片段标题与来源标注
        - 图谱实体与关系
        - 用户问题
        """
        await rag_service.query("304不锈钢的化学成分", top_k=3)

        prompt = mock_services.generate.call_args.kwargs["prompt"]

        # 文档片段部分
        assert "=== 检索到的文档片段 ===" in prompt
        assert "[1] 来源: 文档 doc_1, 片段 chunk_1" in prompt
        assert "内容: 重排后内容1" in prompt
        assert "[2] 来源: 文档 doc_2, 片段 chunk_2" in prompt

        # 图谱信息部分
        assert "=== 知识图谱信息 ===" in prompt
        assert "实体: 304不锈钢" in prompt
        assert "关系: 304不锈钢 --执行标准--> GB/T 1220" in prompt

        # 问题部分
        assert "问题: 304不锈钢的化学成分" in prompt

    @pytest.mark.asyncio
    async def test_context_no_graph_section(self, mock_services):
        """测试无图谱数据时上下文不含图谱部分。"""
        mock_services.search_nodes.return_value = []

        await rag_service.query("304不锈钢的化学成分")

        prompt = mock_services.generate.call_args.kwargs["prompt"]
        assert "=== 知识图谱信息 ===" not in prompt
        # 文档片段和问题部分仍存在
        assert "=== 检索到的文档片段 ===" in prompt
        assert "问题:" in prompt

    @pytest.mark.asyncio
    async def test_context_system_prompt(self, mock_services):
        """测试 LLM 使用正确的系统提示词。"""
        await rag_service.query("304不锈钢的化学成分")

        system_prompt = mock_services.generate.call_args.kwargs["system_prompt"]
        assert "文档问答助手" in system_prompt
        assert "检索到的文档片段" in system_prompt

    @pytest.mark.asyncio
    async def test_context_truncation(self, mock_services, monkeypatch):
        """测试上下文超长时被截断。"""
        # 构造超长内容
        long_results = [
            {
                "id": 1,
                "chunk_id": "chunk_1",
                "text": "A" * 5000,
                "doc_id": "doc_1",
                "title_chain": "标准",
                "metadata": {"page": 1},
                "score": 0.9,
                "rank": 1,
            }
        ]
        mock_services.search.return_value = long_results
        mock_services.rerank.return_value = [
            RerankResult(
                chunk_id="chunk_1",
                document_id="doc_1",
                content="A" * 5000,
                original_score=0.9,
                rerank_score=0.95,
                rank=1,
                metadata={"page": 1},
            )
        ]

        # 设置较小的最大上下文长度
        from app.core.config import settings
        monkeypatch.setattr(settings, "RAG_MAX_CONTEXT_LENGTH", 200)

        await rag_service.query("测试问题")

        prompt = mock_services.generate.call_args.kwargs["prompt"]
        assert len(prompt) <= 200 + 50  # 允许截断标记的额外长度
        assert "截断" in prompt
