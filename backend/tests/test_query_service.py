"""查询理解服务测试模块。

测试 QueryService 的核心功能：
- 数据模型：QueryEntity / QueryAnalysis 默认值与字段校验
- 意图分类：5 种意图（document_search / knowledge_graph / summarization /
  comparison / general）的识别
- 实体抽取：材料、标准、技术属性的解析
- 查询重写：rewritten_query 的生成
- 子查询生成：复杂查询的拆解
- 错误处理：LLM 返回非法 JSON 时的优雅降级
- rewrite_for_retrieval：返回原始 + 重写 + 子查询的合并列表

所有测试通过 mock ``llm_service.generate_json`` 避免真实模型调用，
确保可在无 GPU 环境运行。
"""

from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BusinessException
from app.services.query_service import (
    QueryAnalysis,
    QueryEntity,
    QueryService,
    query_service,
)


# ---------------------------------------------------------------
# 测试辅助：LLM 服务 mock
# ---------------------------------------------------------------
@pytest.fixture
def mock_llm(monkeypatch):
    """mock llm_service.generate_json，避免真实模型调用。

    返回 AsyncMock，测试中通过设置 return_value / side_effect 控制行为。
    """
    from app.services import llm_service as llm_module

    mock_generate = AsyncMock()
    monkeypatch.setattr(llm_module.llm_service, "generate_json", mock_generate)
    return mock_generate


# ---------------------------------------------------------------
# 数据模型测试
# ---------------------------------------------------------------
class TestModels:
    """QueryEntity / QueryAnalysis 数据模型测试。"""

    def test_query_entity_defaults(self):
        """测试 QueryEntity 默认值：type=other，offsets=-1。"""
        entity = QueryEntity(text="304不锈钢")

        assert entity.text == "304不锈钢"
        assert entity.type == "other"
        assert entity.start == -1
        assert entity.end == -1

    def test_query_entity_with_full_fields(self):
        """测试 QueryEntity 完整字段赋值。"""
        entity = QueryEntity(
            text="GB/T 1220",
            type="standard",
            start=5,
            end=15,
        )

        assert entity.text == "GB/T 1220"
        assert entity.type == "standard"
        assert entity.start == 5
        assert entity.end == 15

    def test_query_analysis_defaults(self):
        """测试 QueryAnalysis 默认值：intent=general，空列表，confidence=0。"""
        analysis = QueryAnalysis()

        assert analysis.intent == "general"
        assert analysis.entities == []
        assert analysis.rewritten_query == ""
        assert analysis.sub_queries == []
        assert analysis.confidence == 0.0

    def test_query_analysis_with_data(self):
        """测试 QueryAnalysis 携带完整数据。"""
        entities = [QueryEntity(text="304不锈钢", type="material")]
        analysis = QueryAnalysis(
            intent="document_search",
            entities=entities,
            rewritten_query="304不锈钢 化学成分",
            sub_queries=["304的化学成分"],
            confidence=0.92,
        )

        assert analysis.intent == "document_search"
        assert len(analysis.entities) == 1
        assert analysis.rewritten_query == "304不锈钢 化学成分"
        assert analysis.sub_queries == ["304的化学成分"]
        assert analysis.confidence == 0.92


# ---------------------------------------------------------------
# 意图分类测试
# ---------------------------------------------------------------
class TestIntentClassification:
    """5 种意图类型的分类测试。"""

    @pytest.mark.asyncio
    async def test_intent_document_search(self, mock_llm):
        """测试 document_search 意图识别。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [{"text": "GB/T 1220", "type": "standard"}],
            "rewritten_query": "GB/T 1220 不锈钢棒 化学成分",
            "sub_queries": ["GB/T 1220 不锈钢棒化学成分"],
            "confidence": 0.95,
        }

        analysis = await query_service.analyze(
            "GB/T 1220中不锈钢棒的化学成分是什么？"
        )

        assert analysis.intent == "document_search"
        assert analysis.confidence == 0.95

    @pytest.mark.asyncio
    async def test_intent_knowledge_graph(self, mock_llm):
        """测试 knowledge_graph 意图识别。"""
        mock_llm.return_value = {
            "intent": "knowledge_graph",
            "entities": [{"text": "304不锈钢", "type": "material"}],
            "rewritten_query": "304不锈钢 执行标准",
            "sub_queries": [],
            "confidence": 0.88,
        }

        analysis = await query_service.analyze("304不锈钢执行什么标准？")

        assert analysis.intent == "knowledge_graph"

    @pytest.mark.asyncio
    async def test_intent_summarization(self, mock_llm):
        """测试 summarization 意图识别。"""
        mock_llm.return_value = {
            "intent": "summarization",
            "entities": [{"text": "304不锈钢", "type": "material"}],
            "rewritten_query": "总结 304不锈钢 材料特性",
            "sub_queries": [],
            "confidence": 0.91,
        }

        analysis = await query_service.analyze("总结304不锈钢的材料特性")

        assert analysis.intent == "summarization"

    @pytest.mark.asyncio
    async def test_intent_comparison(self, mock_llm):
        """测试 comparison 意图识别。"""
        mock_llm.return_value = {
            "intent": "comparison",
            "entities": [
                {"text": "304不锈钢", "type": "material"},
                {"text": "316不锈钢", "type": "material"},
            ],
            "rewritten_query": "304不锈钢 316不锈钢 区别",
            "sub_queries": ["304不锈钢特性", "316不锈钢特性"],
            "confidence": 0.93,
        }

        analysis = await query_service.analyze("304和316不锈钢的区别")

        assert analysis.intent == "comparison"
        assert len(analysis.entities) == 2

    @pytest.mark.asyncio
    async def test_intent_general(self, mock_llm):
        """测试 general 意图识别。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "rewritten_query": "你好",
            "sub_queries": [],
            "confidence": 0.7,
        }

        analysis = await query_service.analyze("你好")

        assert analysis.intent == "general"
        assert analysis.entities == []

    @pytest.mark.asyncio
    async def test_intent_invalid_falls_back_to_general(self, mock_llm):
        """测试 LLM 返回非法意图时回退为 general。"""
        mock_llm.return_value = {
            "intent": "unknown_intent",
            "entities": [],
            "rewritten_query": "查询",
            "sub_queries": [],
            "confidence": 0.5,
        }

        analysis = await query_service.analyze("查询")

        assert analysis.intent == "general"


# ---------------------------------------------------------------
# 实体抽取测试
# ---------------------------------------------------------------
class TestEntityExtraction:
    """实体抽取功能测试。"""

    @pytest.mark.asyncio
    async def test_extract_material_entity(self, mock_llm):
        """测试抽取材料类实体。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [{"text": "304不锈钢", "type": "material"}],
            "rewritten_query": "304不锈钢",
            "sub_queries": [],
            "confidence": 0.9,
        }

        analysis = await query_service.analyze("304不锈钢的化学成分")

        assert len(analysis.entities) == 1
        assert analysis.entities[0].text == "304不锈钢"
        assert analysis.entities[0].type == "material"

    @pytest.mark.asyncio
    async def test_extract_standard_entity(self, mock_llm):
        """测试抽取标准类实体。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [{"text": "GB/T 1220", "type": "standard"}],
            "rewritten_query": "GB/T 1220",
            "sub_queries": [],
            "confidence": 0.9,
        }

        analysis = await query_service.analyze("GB/T 1220标准内容")

        assert len(analysis.entities) == 1
        assert analysis.entities[0].text == "GB/T 1220"
        assert analysis.entities[0].type == "standard"

    @pytest.mark.asyncio
    async def test_extract_property_entity(self, mock_llm):
        """测试抽取技术属性类实体。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [{"text": "屈服强度", "type": "property"}],
            "rewritten_query": "屈服强度",
            "sub_queries": [],
            "confidence": 0.88,
        }

        analysis = await query_service.analyze("304的屈服强度是多少")

        assert len(analysis.entities) == 1
        assert analysis.entities[0].text == "屈服强度"
        assert analysis.entities[0].type == "property"

    @pytest.mark.asyncio
    async def test_extract_multiple_entities(self, mock_llm):
        """测试抽取多个不同类型的实体。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [
                {"text": "304不锈钢", "type": "material"},
                {"text": "GB/T 1220", "type": "standard"},
                {"text": "化学成分", "type": "property"},
            ],
            "rewritten_query": "304不锈钢 GB/T 1220 化学成分",
            "sub_queries": [],
            "confidence": 0.96,
        }

        analysis = await query_service.analyze(
            "GB/T 1220中304不锈钢的化学成分是什么？"
        )

        assert len(analysis.entities) == 3
        types = {e.type for e in analysis.entities}
        assert types == {"material", "standard", "property"}

    @pytest.mark.asyncio
    async def test_extract_entity_with_offsets(self, mock_llm):
        """测试实体携带偏移信息。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [
                {"text": "304不锈钢", "type": "material", "start": 0, "end": 6}
            ],
            "rewritten_query": "304不锈钢",
            "sub_queries": [],
            "confidence": 0.9,
        }

        analysis = await query_service.analyze("304不锈钢的化学成分")

        assert analysis.entities[0].start == 0
        assert analysis.entities[0].end == 6

    @pytest.mark.asyncio
    async def test_extract_skips_invalid_entity(self, mock_llm):
        """测试非法实体条目被跳过，不中断整体解析。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [
                {"text": "304不锈钢", "type": "material"},
                {"type": "material"},  # 缺 text 字段，应跳过
                "非字典条目",  # 非字典，应跳过
                {"text": "GB/T 1220", "type": "standard"},
            ],
            "rewritten_query": "304不锈钢 GB/T 1220",
            "sub_queries": [],
            "confidence": 0.9,
        }

        analysis = await query_service.analyze("304不锈钢 GB/T 1220")

        assert len(analysis.entities) == 2
        assert analysis.entities[0].text == "304不锈钢"
        assert analysis.entities[1].text == "GB/T 1220"


# ---------------------------------------------------------------
# 查询重写测试
# ---------------------------------------------------------------
class TestQueryRewriting:
    """查询重写功能测试。"""

    @pytest.mark.asyncio
    async def test_rewritten_query_contains_expanded_abbreviation(self, mock_llm):
        """测试重写查询包含缩写扩展（304 → 304不锈钢）。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [{"text": "304不锈钢", "type": "material"}],
            "rewritten_query": "304不锈钢 化学成分",
            "sub_queries": [],
            "confidence": 0.92,
        }

        analysis = await query_service.analyze("304的化学成分")

        assert "304不锈钢" in analysis.rewritten_query
        assert analysis.rewritten_query != "304的化学成分"

    @pytest.mark.asyncio
    async def test_rewritten_query_includes_entities(self, mock_llm):
        """测试重写查询整合了抽取到的实体上下文。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [
                {"text": "304不锈钢", "type": "material"},
                {"text": "GB/T 1220", "type": "standard"},
                {"text": "化学成分", "type": "property"},
            ],
            "rewritten_query": "304不锈钢 GB/T 1220 化学成分",
            "sub_queries": [],
            "confidence": 0.95,
        }

        analysis = await query_service.analyze("GB/T 1220中304的成分")

        # 重写查询应包含所有抽取实体的文本
        for entity in analysis.entities:
            assert entity.text in analysis.rewritten_query

    @pytest.mark.asyncio
    async def test_rewritten_query_falls_back_to_original_when_missing(
        self, mock_llm
    ):
        """测试 LLM 未返回 rewritten_query 时回退为原查询。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "sub_queries": [],
            "confidence": 0.5,
        }

        analysis = await query_service.analyze("原始查询内容")

        assert analysis.rewritten_query == "原始查询内容"

    @pytest.mark.asyncio
    async def test_rewritten_query_falls_back_when_empty(self, mock_llm):
        """测试 LLM 返回空字符串 rewritten_query 时回退为原查询。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "rewritten_query": "",
            "sub_queries": [],
            "confidence": 0.5,
        }

        analysis = await query_service.analyze("原始查询")

        assert analysis.rewritten_query == "原始查询"


# ---------------------------------------------------------------
# 子查询生成测试
# ---------------------------------------------------------------
class TestSubQueryGeneration:
    """子查询生成功能测试。"""

    @pytest.mark.asyncio
    async def test_sub_queries_for_complex_query(self, mock_llm):
        """测试复杂查询生成多个子查询。"""
        mock_llm.return_value = {
            "intent": "comparison",
            "entities": [
                {"text": "304不锈钢", "type": "material"},
                {"text": "316不锈钢", "type": "material"},
            ],
            "rewritten_query": "304不锈钢 316不锈钢 区别",
            "sub_queries": [
                "304不锈钢的化学成分",
                "316不锈钢的化学成分",
                "304和316不锈钢成分差异",
            ],
            "confidence": 0.94,
        }

        analysis = await query_service.analyze("304和316不锈钢的区别")

        assert len(analysis.sub_queries) == 3
        assert "304不锈钢的化学成分" in analysis.sub_queries
        assert "316不锈钢的化学成分" in analysis.sub_queries

    @pytest.mark.asyncio
    async def test_sub_queries_empty_for_simple_query(self, mock_llm):
        """测试简单查询无子查询。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "rewritten_query": "你好",
            "sub_queries": [],
            "confidence": 0.7,
        }

        analysis = await query_service.analyze("你好")

        assert analysis.sub_queries == []

    @pytest.mark.asyncio
    async def test_sub_queries_filters_non_string(self, mock_llm):
        """测试子查询列表过滤非字符串项。"""
        mock_llm.return_value = {
            "intent": "comparison",
            "entities": [],
            "rewritten_query": "查询",
            "sub_queries": [
                "有效子查询",
                123,  # 非字符串，应被过滤
                "",  # 空字符串，应被过滤
                "  ",  # 纯空白，应被过滤
                "另一个有效查询",
            ],
            "confidence": 0.8,
        }

        analysis = await query_service.analyze("查询")

        assert analysis.sub_queries == ["有效子查询", "另一个有效查询"]

    @pytest.mark.asyncio
    async def test_sub_queries_non_list_returns_empty(self, mock_llm):
        """测试 sub_queries 非列表时返回空列表。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "rewritten_query": "查询",
            "sub_queries": "不是列表",
            "confidence": 0.5,
        }

        analysis = await query_service.analyze("查询")

        assert analysis.sub_queries == []


# ---------------------------------------------------------------
# 错误处理测试
# ---------------------------------------------------------------
class TestErrorHandling:
    """LLM 调用失败与异常返回场景测试。"""

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json_falls_back(self, mock_llm):
        """测试 LLM 返回非法 JSON 时优雅降级为 general 意图。"""
        mock_llm.side_effect = BusinessException(
            code=30003,
            message="无法从模型输出中解析出合法 JSON",
        )

        analysis = await query_service.analyze("查询内容")

        assert analysis.intent == "general"
        assert analysis.entities == []
        assert analysis.rewritten_query == "查询内容"
        assert analysis.sub_queries == []
        assert analysis.confidence == 0.0

    @pytest.mark.asyncio
    async def test_llm_runtime_error_falls_back(self, mock_llm):
        """测试 LLM 抛出运行时异常时优雅降级。"""
        mock_llm.side_effect = RuntimeError("vLLM 推理失败")

        analysis = await query_service.analyze("查询内容")

        assert analysis.intent == "general"
        assert analysis.rewritten_query == "查询内容"
        assert analysis.confidence == 0.0

    @pytest.mark.asyncio
    async def test_llm_returns_non_dict_falls_back(self, mock_llm):
        """测试 LLM 返回非字典（如列表）时优雅降级。"""
        mock_llm.return_value = ["not", "a", "dict"]

        analysis = await query_service.analyze("查询")

        assert analysis.intent == "general"
        assert analysis.rewritten_query == "查询"

    @pytest.mark.asyncio
    async def test_llm_returns_null_falls_back(self, mock_llm):
        """测试 LLM 返回 None 时优雅降级。"""
        mock_llm.return_value = None

        analysis = await query_service.analyze("查询")

        assert analysis.intent == "general"

    @pytest.mark.asyncio
    async def test_empty_query_raises(self, mock_llm):
        """测试空查询抛出 BusinessException。"""
        with pytest.raises(BusinessException) as exc_info:
            await query_service.analyze("")

        assert "不能为空" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_whitespace_query_raises(self, mock_llm):
        """测试纯空白查询抛出 BusinessException。"""
        with pytest.raises(BusinessException):
            await query_service.analyze("   \n  \t  ")

    @pytest.mark.asyncio
    async def test_confidence_clamped_to_range(self, mock_llm):
        """测试 confidence 超出 [0, 1] 范围时被 clamp。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "rewritten_query": "查询",
            "sub_queries": [],
            "confidence": 1.5,
        }

        analysis = await query_service.analyze("查询")

        assert analysis.confidence == 1.0

    @pytest.mark.asyncio
    async def test_confidence_negative_clamped_to_zero(self, mock_llm):
        """测试负数 confidence 被 clamp 到 0。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "rewritten_query": "查询",
            "sub_queries": [],
            "confidence": -0.3,
        }

        analysis = await query_service.analyze("查询")

        assert analysis.confidence == 0.0

    @pytest.mark.asyncio
    async def test_confidence_non_numeric_returns_zero(self, mock_llm):
        """测试非数值 confidence 返回 0。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "rewritten_query": "查询",
            "sub_queries": [],
            "confidence": "high",
        }

        analysis = await query_service.analyze("查询")

        assert analysis.confidence == 0.0


# ---------------------------------------------------------------
# rewrite_for_retrieval 测试
# ---------------------------------------------------------------
class TestRewriteForRetrieval:
    """rewrite_for_retrieval 方法测试。"""

    @pytest.mark.asyncio
    async def test_returns_original_first(self, mock_llm):
        """测试返回列表中原始查询位于首位。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [],
            "rewritten_query": "重写查询",
            "sub_queries": ["子查询1"],
            "confidence": 0.9,
        }

        queries = await query_service.rewrite_for_retrieval("原始查询")

        assert queries[0] == "原始查询"
        assert len(queries) >= 1

    @pytest.mark.asyncio
    async def test_returns_list_of_queries(self, mock_llm):
        """测试返回包含原始、重写、子查询的合并列表。"""
        mock_llm.return_value = {
            "intent": "comparison",
            "entities": [],
            "rewritten_query": "重写查询",
            "sub_queries": ["子查询1", "子查询2"],
            "confidence": 0.9,
        }

        queries = await query_service.rewrite_for_retrieval("原始查询")

        assert isinstance(queries, list)
        assert "原始查询" in queries
        assert "重写查询" in queries
        assert "子查询1" in queries
        assert "子查询2" in queries
        assert len(queries) == 4

    @pytest.mark.asyncio
    async def test_deduplicates_queries(self, mock_llm):
        """测试重复查询被去重。"""
        mock_llm.return_value = {
            "intent": "document_search",
            "entities": [],
            "rewritten_query": "原始查询",  # 与原查询相同
            "sub_queries": ["原始查询", "另一个子查询"],
            "confidence": 0.9,
        }

        queries = await query_service.rewrite_for_retrieval("原始查询")

        # 去重后应只剩 2 个
        assert len(queries) == 2
        assert queries[0] == "原始查询"
        assert "另一个子查询" in queries

    @pytest.mark.asyncio
    async def test_returns_only_original_on_llm_failure(self, mock_llm):
        """测试 LLM 失败时仅返回原始查询。"""
        mock_llm.side_effect = RuntimeError("vLLM 推理失败")

        queries = await query_service.rewrite_for_retrieval("原始查询")

        assert queries == ["原始查询"]

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self, mock_llm):
        """测试空查询返回空列表。"""
        queries = await query_service.rewrite_for_retrieval("")

        assert queries == []
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_rewritten_no_subqueries(self, mock_llm):
        """测试无重写查询与子查询时仅返回原始查询。"""
        mock_llm.return_value = {
            "intent": "general",
            "entities": [],
            "rewritten_query": "",
            "sub_queries": [],
            "confidence": 0.5,
        }

        queries = await query_service.rewrite_for_retrieval("原始查询")

        # rewritten_query 为空时回退为原查询，但已在列表中，去重后仅 1 个
        assert queries == ["原始查询"]


# ---------------------------------------------------------------
# 提示词构造测试
# ---------------------------------------------------------------
class TestPromptBuilding:
    """_build_prompt 方法测试。"""

    def test_prompt_contains_query(self):
        """测试提示词中包含用户查询。"""
        prompt = QueryService._build_prompt("304不锈钢的化学成分")

        assert "304不锈钢的化学成分" in prompt

    def test_prompt_contains_intent_types(self):
        """测试提示词中包含所有意图类型。"""
        prompt = QueryService._build_prompt("查询")

        assert "document_search" in prompt
        assert "knowledge_graph" in prompt
        assert "summarization" in prompt
        assert "comparison" in prompt
        assert "general" in prompt

    def test_prompt_contains_entity_types(self):
        """测试提示词中包含所有实体类型。"""
        prompt = QueryService._build_prompt("查询")

        assert "material" in prompt
        assert "standard" in prompt
        assert "property" in prompt
        assert "document" in prompt
        assert "other" in prompt

    def test_prompt_contains_json_format(self):
        """测试提示词中包含 JSON 输出格式说明。"""
        prompt = QueryService._build_prompt("查询")

        assert "JSON" in prompt
        assert "intent" in prompt
        assert "entities" in prompt
        assert "rewritten_query" in prompt
        assert "sub_queries" in prompt
        assert "confidence" in prompt

    def test_prompt_contains_rewrite_instructions(self):
        """测试提示词中包含重写要求说明。"""
        prompt = QueryService._build_prompt("查询")

        assert "重写要求" in prompt
        assert "扩展缩写" in prompt


# ---------------------------------------------------------------
# 兜底解析测试
# ---------------------------------------------------------------
class TestFallbackParsing:
    """_parse_analysis 与 _fallback_analysis 方法测试。"""

    def test_fallback_analysis_returns_general_intent(self):
        """测试兜底分析返回 general 意图。"""
        analysis = QueryService._fallback_analysis("原查询")

        assert analysis.intent == "general"
        assert analysis.rewritten_query == "原查询"
        assert analysis.confidence == 0.0
        assert analysis.entities == []
        assert analysis.sub_queries == []

    def test_parse_analysis_handles_missing_intent(self):
        """测试解析时缺失 intent 字段使用默认 general。"""
        analysis = QueryService._parse_analysis(
            {"entities": [], "rewritten_query": "查询"}, "原查询"
        )

        assert analysis.intent == "general"

    def test_parse_analysis_handles_missing_entities(self):
        """测试解析时缺失 entities 字段返回空列表。"""
        analysis = QueryService._parse_analysis(
            {"intent": "general", "rewritten_query": "查询"}, "原查询"
        )

        assert analysis.entities == []

    def test_parse_analysis_handles_missing_sub_queries(self):
        """测试解析时缺失 sub_queries 字段返回空列表。"""
        analysis = QueryService._parse_analysis(
            {"intent": "general", "rewritten_query": "查询"}, "原查询"
        )

        assert analysis.sub_queries == []

    def test_parse_analysis_handles_missing_confidence(self):
        """测试解析时缺失 confidence 字段返回 0。"""
        analysis = QueryService._parse_analysis(
            {"intent": "general", "rewritten_query": "查询"}, "原查询"
        )

        assert analysis.confidence == 0.0
