"""查询理解服务模块。

本模块基于 vLLM（Qwen3.5-9B）实现 RAG 引擎的查询理解能力，包含：
- 意图分类：将用户查询归类为 document_search / knowledge_graph /
  summarization / comparison / general 五类
- 实体抽取：抽取材料名、标准名、技术属性、文档引用等关键实体
- 查询重写：扩展缩写、补全上下文，生成检索友好的查询
- 子查询生成：针对复杂查询拆解出多个子查询，提升召回率

设计要点：
- 所有 LLM 调用通过 ``llm_service.generate_json`` 完成，本身为异步接口
- LLM 失败时进行优雅降级：返回 ``intent=general`` 的兜底分析结果，
  保证 RAG 主流程在查询理解异常时仍可继续运行
- 采用模块级单例 ``query_service``，导入时不触发任何重型初始化

使用示例：
    from app.services.query_service import query_service

    analysis = await query_service.analyze("GB/T 1220中304不锈钢的化学成分是什么？")
    # analysis.intent -> "document_search"
    # analysis.entities -> [QueryEntity(text="304不锈钢", type="material"), ...]
    # analysis.rewritten_query -> "304不锈钢 GB/T 1220 化学成分"

    queries = await query_service.rewrite_for_retrieval("304和316的区别")
    # queries -> ["304和316的区别", "304不锈钢 特性", "316不锈钢 特性", ...]
"""

from typing import Any

from pydantic import BaseModel, Field

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------
# 意图与实体类型常量
# ---------------------------------------------------------------
# 意图类型枚举值，与 prompt 中说明的意图保持一致
INTENT_DOCUMENT_SEARCH = "document_search"
INTENT_KNOWLEDGE_GRAPH = "knowledge_graph"
INTENT_SUMMARIZATION = "summarization"
INTENT_COMPARISON = "comparison"
INTENT_GENERAL = "general"

# 合法意图集合，用于校验 LLM 返回值
_VALID_INTENTS = {
    INTENT_DOCUMENT_SEARCH,
    INTENT_KNOWLEDGE_GRAPH,
    INTENT_SUMMARIZATION,
    INTENT_COMPARISON,
    INTENT_GENERAL,
}

# 实体类型枚举值
ENTITY_TYPE_MATERIAL = "material"
ENTITY_TYPE_STANDARD = "standard"
ENTITY_TYPE_PROPERTY = "property"
ENTITY_TYPE_DOCUMENT = "document"
ENTITY_TYPE_OTHER = "other"


# 查询文本最大长度，超过则截断，避免超出模型上下文窗口
_MAX_QUERY_LEN = 500


class QueryEntity(BaseModel):
    """查询实体。

    表示从用户查询中抽取的关键实体，例如材料名、标准号、技术属性等。

    Attributes:
        text: 实体文本内容，如 "304不锈钢"。
        type: 实体类型，取值为 material / standard / property / document / other。
        start: 实体在原查询中的起始字符偏移，缺省 -1 表示未定位。
        end: 实体在原查询中的结束字符偏移（ exclusive ），缺省 -1 表示未定位。
    """

    text: str
    type: str = ENTITY_TYPE_OTHER
    start: int = -1
    end: int = -1


class QueryAnalysis(BaseModel):
    """查询分析结果。

    Attributes:
        intent: 意图类型，取值为 document_search / knowledge_graph /
            summarization / comparison / general。
        entities: 抽取到的实体列表。
        rewritten_query: 重写后的查询，用于提升检索召回率。
        sub_queries: 复杂查询拆解出的子查询列表，简单查询为空。
        confidence: 意图分类置信度，取值范围 [0.0, 1.0]。
    """

    intent: str = INTENT_GENERAL
    entities: list[QueryEntity] = Field(default_factory=list)
    rewritten_query: str = ""
    sub_queries: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class QueryService:
    """查询理解服务。

    通过调用 LLM（Qwen3.5-9B）完成意图分类、实体抽取、查询重写与子查询生成。
    所有 LLM 调用均通过 ``llm_service.generate_json`` 完成，本身为异步接口，
    无需额外的 ``asyncio.to_thread`` 包装。

    LLM 失败时进行优雅降级：返回 ``intent=general`` 的兜底分析结果，
    保证 RAG 主流程在查询理解异常时仍可继续运行。
    """

    def __init__(self) -> None:
        # 查询理解为纯 LLM 调用，无需任何本地模型加载
        pass

    async def analyze(self, query: str) -> QueryAnalysis:
        """分析用户查询，输出意图、实体、重写查询与子查询。

        调用 LLM 进行一次性结构化分析，返回 QueryAnalysis 对象。
        LLM 调用失败或返回非法 JSON 时，返回兜底分析结果（intent=general，
        rewritten_query=原查询），不抛出异常，保证 RAG 主流程可用。

        Args:
            query: 用户原始查询文本。

        Returns:
            QueryAnalysis: 查询分析结果。

        Raises:
            BusinessException: 仅当查询为空或纯空白时抛出。
        """
        # 输入校验：空查询直接抛出，不进入 LLM 调用
        if not query or not query.strip():
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="查询文本不能为空",
            )

        from app.services.llm_service import llm_service

        # 截断超长查询，避免超出模型上下文窗口
        truncated = query[:_MAX_QUERY_LEN]
        prompt = self._build_prompt(truncated)

        logger.info("开始查询理解", query_len=len(truncated))

        try:
            response = await llm_service.generate_json(prompt)
        except BusinessException as err:
            # LLM 调用失败或 JSON 解析失败时优雅降级，记录警告
            logger.warning(
                "查询理解 LLM 调用失败，返回兜底分析",
                error=str(err),
                message=err.message,
            )
            return self._fallback_analysis(query)
        except Exception as err:
            # 兜底捕获其他未预期异常，避免中断 RAG 主流程
            logger.error(
                "查询理解发生未预期异常，返回兜底分析",
                error=str(err),
                exc_info=True,
            )
            return self._fallback_analysis(query)

        analysis = self._parse_analysis(response, original_query=query)

        logger.info(
            "查询理解完成",
            intent=analysis.intent,
            entity_count=len(analysis.entities),
            sub_query_count=len(analysis.sub_queries),
            confidence=analysis.confidence,
        )
        return analysis

    async def rewrite_for_retrieval(self, query: str) -> list[str]:
        """生成检索优化的查询列表。

        返回原始查询与重写查询、子查询的去重合并列表，供向量检索多路召回使用。
        顺序保证原始查询位于首位，便于调用方优先使用。

        Args:
            query: 用户原始查询文本。

        Returns:
            list[str]: 检索查询列表，至少包含原始查询。
                失败时仅返回 [原查询]。
        """
        # 空查询直接返回空列表，避免触发 LLM 调用
        if not query or not query.strip():
            return []

        analysis = await self.analyze(query)

        # 合并原始查询、重写查询与子查询，保持顺序并去重
        queries: list[str] = [query]
        seen = {query}
        if analysis.rewritten_query and analysis.rewritten_query not in seen:
            queries.append(analysis.rewritten_query)
            seen.add(analysis.rewritten_query)
        for sub in analysis.sub_queries:
            if sub and sub not in seen:
                queries.append(sub)
                seen.add(sub)
        return queries

    @staticmethod
    def _build_prompt(query: str) -> str:
        """构造查询理解提示词。

        提示词为中文，明确意图类型、实体类型与输出 JSON 格式，
        引导 Qwen3.5-9B 输出结构化结果。

        Args:
            query: 已截断的用户查询文本。

        Returns:
            str: 完整的 LLM 提示词。
        """
        return (
            "你是一个查询理解助手。请分析以下用户查询，提取意图和实体。\n\n"
            "意图类型：\n"
            "- document_search: 查找特定文档内容\n"
            "- knowledge_graph: 查询实体关系\n"
            "- summarization: 请求总结\n"
            "- comparison: 比较不同项\n"
            "- general: 一般问题\n\n"
            "实体类型：\n"
            "- material: 材料名称（如304不锈钢、316L）\n"
            "- standard: 标准名称（如GB/T 1220、ASTM A276）\n"
            "- property: 技术属性（如化学成分、屈服强度）\n"
            "- document: 文档引用\n"
            "- other: 其他\n\n"
            "重写要求：\n"
            "- 扩展缩写（如304应扩展为304不锈钢）\n"
            "- 整合抽取到的实体补全上下文\n"
            "- 针对复杂查询生成2-4个子查询\n\n"
            f"查询: {query}\n\n"
            "请输出JSON格式:\n"
            "{\n"
            '  "intent": "document_search",\n'
            '  "entities": [{"text": "304不锈钢", "type": "material"}],\n'
            '  "rewritten_query": "304不锈钢 GB/T 1220 化学成分",\n'
            '  "sub_queries": ["304不锈钢的化学成分", "GB/T 1220标准中304的成分要求"],\n'
            '  "confidence": 0.95\n'
            "}\n"
        )

    @staticmethod
    def _parse_analysis(data: Any, original_query: str) -> QueryAnalysis:
        """将 LLM 返回的字典解析为 QueryAnalysis 对象。

        对非法字段进行兜底处理：
        - 非字典输入：返回兜底结果
        - 非法意图：回退为 general
        - 非法实体条目：跳过
        - 非法 confidence：clamp 到 [0, 1]
        - 缺失 rewritten_query：使用原查询

        Args:
            data: LLM 返回的原始数据。
            original_query: 原始用户查询，用于兜底重写。

        Returns:
            QueryAnalysis: 解析后的查询分析对象。
        """
        if not isinstance(data, dict):
            return QueryService._fallback_analysis(original_query)

        # 意图：非法值回退为 general
        intent = data.get("intent", INTENT_GENERAL)
        if intent not in _VALID_INTENTS:
            logger.warning("LLM 返回非法意图，回退为 general", intent=intent)
            intent = INTENT_GENERAL

        # 实体：逐条解析，跳过非法条目
        entities = QueryService._parse_entities(data.get("entities", []))

        # 重写查询：缺失时回退为原查询
        rewritten = data.get("rewritten_query") or original_query
        if not isinstance(rewritten, str):
            rewritten = original_query

        # 子查询：过滤非字符串与空串
        sub_queries = QueryService._parse_sub_queries(data.get("sub_queries", []))

        # 置信度：clamp 到 [0, 1]
        confidence = QueryService._clamp_confidence(data.get("confidence", 0.0))

        return QueryAnalysis(
            intent=intent,
            entities=entities,
            rewritten_query=rewritten,
            sub_queries=sub_queries,
            confidence=confidence,
        )

    @staticmethod
    def _parse_entities(entities_data: Any) -> list[QueryEntity]:
        """解析实体列表，跳过格式不合法的条目。

        Args:
            entities_data: LLM 返回的原始实体数据。

        Returns:
            list[QueryEntity]: 成功解析的实体列表。
        """
        if not isinstance(entities_data, list):
            return []
        entities: list[QueryEntity] = []
        for item in entities_data:
            if not isinstance(item, dict):
                continue
            try:
                entities.append(QueryEntity(**item))
            except Exception as err:
                logger.warning("跳过格式不合法的实体条目", item=item, error=str(err))
        return entities

    @staticmethod
    def _parse_sub_queries(sub_data: Any) -> list[str]:
        """解析子查询列表，仅保留非空字符串。

        Args:
            sub_data: LLM 返回的原始子查询数据。

        Returns:
            list[str]: 过滤后的子查询列表。
        """
        if not isinstance(sub_data, list):
            return []
        result: list[str] = []
        for item in sub_data:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        """将置信度 clamp 到 [0, 1] 区间。

        Args:
            value: LLM 返回的原始置信度值。

        Returns:
            float: 规范化后的置信度。
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v

    @staticmethod
    def _fallback_analysis(query: str) -> QueryAnalysis:
        """构造兜底分析结果。

        LLM 调用失败或返回非法数据时使用，保证 RAG 主流程可用。

        Args:
            query: 原始用户查询。

        Returns:
            QueryAnalysis: intent=general 的兜底分析结果。
        """
        return QueryAnalysis(
            intent=INTENT_GENERAL,
            entities=[],
            rewritten_query=query,
            sub_queries=[],
            confidence=0.0,
        )


# 模块级单例，供整个应用直接导入使用
query_service = QueryService()
