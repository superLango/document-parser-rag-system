"""LlamaIndex 查询引擎封装模块。

本模块封装 LlamaIndex 的 SubQuestionQueryEngine 和 RouterQueryEngine，
作为现有 RAG 管道的查询引擎增强层：

- ``SubQuestionQueryEngineWrapper``：将复杂问题分解为多个子问题并行回答，
  适合 comparison 类查询（如"304和316不锈钢的区别"）
- ``RouterEngineWrapper``：根据查询意图自动选择查询引擎，
  保留现有 LLM 意图分类作为路由 selector

设计要点：
- 懒加载：查询引擎在首次查询时才构建
- 容错降级：LlamaIndex 引擎失败时返回 None，由上层降级到 Milvus
- 复用现有模型：通过 IndexManager 的 LLM/嵌入适配器复用 vLLM 和 bge-m3
- 子问题数量限制：最多 3 个子问题，避免延迟过高

使用示例：
    from app.services.query_engines import subquestion_engine, router_engine

    # SubQuestionQueryEngine：复杂问题分解
    result = await subquestion_engine.query(
        question="304和316不锈钢在化学成分上的区别",
        sub_queries=["304不锈钢的化学成分", "316不锈钢的化学成分"],
    )

    # RouterQueryEngine：意图路由
    result = await router_engine.route_and_query(
        question="总结文档内容",
        intent="summarization",
    )
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# 子问题最大数量限制，避免延迟过高
_MAX_SUB_QUESTIONS = 3


@dataclass
class EngineQueryResult:
    """查询引擎结果。

    与 IndexManager.IndexQueryResult 对齐，便于上层统一处理。

    Attributes:
        answer: LLM 生成的回答文本。
        citations: 引用列表。
        sub_answers: 子问题答案列表（仅 SubQuestionQueryEngine 使用）。
        engine_type: 引擎类型标识。
    """

    answer: str = ""
    citations: list[dict] = field(default_factory=list)
    sub_answers: list[dict] = field(default_factory=list)
    engine_type: str = ""


class SubQuestionQueryEngineWrapper:
    """SubQuestionQueryEngine 封装。

    将复杂问题分解为多个子问题，每个子问题独立查询后合并答案。
    适合 comparison 类查询。

    工作流程：
    1. 接收用户问题与子问题列表（来自 query_service 的 sub_queries）
    2. 为每个子问题创建查询引擎（复用 IndexManager 的索引）
    3. 并行执行子问题查询
    4. 合并子答案为最终答案

    约束：
    - 子问题数量上限 3 个，超出截断
    - 单个子问题失败不影响其他
    - 全部失败时返回空结果，由上层降级
    """

    def __init__(self) -> None:
        """初始化子问题查询引擎封装。"""
        self._engine: Any = None
        self._built: bool = False

    async def query(
        self,
        question: str,
        sub_queries: list[str],
        top_k: int = 5,
    ) -> EngineQueryResult:
        """执行子问题分解查询。

        Args:
            question: 原始用户问题。
            sub_queries: 子问题列表（来自 query_service.analyze.sub_queries）。
            top_k: 每个子问题返回结果数量上限。

        Returns:
            EngineQueryResult: 查询结果。失败时返回空结果。
        """
        if not sub_queries:
            logger.debug("子问题列表为空，跳过 SubQuestionQueryEngine")
            return EngineQueryResult(engine_type="subquestion")

        # 限制子问题数量
        sub_queries = sub_queries[:_MAX_SUB_QUESTIONS]
        logger.info(
            "SubQuestionQueryEngine 开始查询",
            question=question[:100],
            sub_query_count=len(sub_queries),
        )

        try:
            # 获取 IndexManager 单例
            from app.services.index_manager import index_manager
            im = index_manager

            if not im._built:
                logger.debug("IndexManager 未构建，无法使用 SubQuestionQueryEngine")
                return EngineQueryResult(engine_type="subquestion")

            llm = im._get_llm()

            # 为每个子问题创建查询引擎并并行执行
            # 优先使用 SummaryIndex（适合事实查询），降级到 KeywordTableIndex
            async def _query_one(sub_q: str) -> dict:
                """查询单个子问题。"""
                try:
                    # 选择可用的索引
                    if im._summary_available and im._summary_index is not None:
                        engine = im._summary_index.as_query_engine(
                            llm=llm, similarity_top_k=top_k
                        )
                    elif im._keyword_available and im._keyword_index is not None:
                        engine = im._keyword_index.as_query_engine(
                            llm=llm, similarity_top_k=top_k
                        )
                    else:
                        return {"question": sub_q, "answer": "", "citations": []}

                    response = await asyncio.to_thread(engine.query, sub_q)
                    citations = im._extract_citations(response, "subquestion")
                    return {
                        "question": sub_q,
                        "answer": str(response),
                        "citations": citations,
                    }
                except Exception as err:
                    logger.warning(
                        "子问题查询失败",
                        sub_question=sub_q[:50],
                        error=str(err),
                    )
                    return {"question": sub_q, "answer": "", "citations": []}

            # 并行执行所有子问题
            sub_results = await asyncio.gather(*[_query_one(sq) for sq in sub_queries])

            # 过滤掉失败的子问题
            valid_results = [r for r in sub_results if r["answer"]]
            if not valid_results:
                logger.warning("所有子问题查询均失败")
                return EngineQueryResult(engine_type="subquestion")

            # 合并子答案为最终答案
            merged_answer = await self._merge_answers(question, valid_results, llm)

            # 合并所有引用
            all_citations: list[dict] = []
            for r in valid_results:
                all_citations.extend(r["citations"])

            logger.info(
                "SubQuestionQueryEngine 查询完成",
                sub_query_count=len(sub_queries),
                valid_count=len(valid_results),
                citation_count=len(all_citations),
            )

            return EngineQueryResult(
                answer=merged_answer,
                citations=all_citations,
                sub_answers=valid_results,
                engine_type="subquestion",
            )

        except Exception as err:
            logger.warning(
                "SubQuestionQueryEngine 查询异常",
                error=str(err),
                exc_info=True,
            )
            return EngineQueryResult(engine_type="subquestion")

    async def _merge_answers(
        self,
        question: str,
        sub_results: list[dict],
        llm: Any,
    ) -> str:
        """合并子答案为最终答案。

        通过 asyncio.to_thread 将同步 LLM 调用包装为异步，避免阻塞事件循环。
        若 LLM 合并失败，使用简单的拼接策略降级。

        Args:
            question: 原始用户问题。
            sub_results: 子问题结果列表。
            llm: LlamaIndex LLM 实例。

        Returns:
            str: 合并后的最终答案。
        """
        # 构建合并 prompt
        parts = [f"原始问题：{question}\n"]
        for i, r in enumerate(sub_results, start=1):
            parts.append(f"子问题 {i}：{r['question']}")
            parts.append(f"答案：{r['answer']}\n")
        parts.append("请基于以上子问题答案，综合回答原始问题。")

        merge_prompt = "\n".join(parts)

        try:
            # 异步调用 LLM 合并，避免阻塞事件循环
            result = await asyncio.to_thread(llm.complete, merge_prompt)
            return str(result)
        except Exception as err:
            logger.warning("LLM 合并子答案失败，使用拼接策略", error=str(err))
            # 降级：简单拼接
            fallback_parts = []
            for r in sub_results:
                fallback_parts.append(f"Q: {r['question']}\nA: {r['answer']}")
            return "\n\n".join(fallback_parts)


class RouterEngineWrapper:
    """RouterQueryEngine 封装。

    根据查询意图自动选择查询引擎，保留现有 LLM 意图分类作为路由 selector。

    路由策略：
    - ``summarization`` → SummaryIndex（通过 IndexManager）
    - ``comparison`` → SubQuestionQueryEngine（子问题分解）
    - ``document_search`` / ``general`` → 降级到 Milvus（返回 None）
    - ``knowledge_graph`` → 降级到 graph_store（返回 None）

    设计说明：
    本封装不直接使用 LlamaIndex 的 RouterQueryEngine，而是基于现有
    query_service 的 LLM 意图分类结果进行路由，避免重复的 LLM 调用。
    """

    def __init__(self) -> None:
        """初始化路由引擎封装。"""
        self._subquestion_engine = SubQuestionQueryEngineWrapper()

    async def route_and_query(
        self,
        question: str,
        intent: str,
        sub_queries: list[str] | None = None,
        top_k: int = 5,
    ) -> EngineQueryResult | None:
        """根据意图路由到合适的查询引擎。

        Args:
            question: 用户查询文本。
            intent: 查询意图（来自 query_service.analyze）。
            sub_queries: 子问题列表（comparison 意图时使用）。
            top_k: 返回结果数量上限。

        Returns:
            EngineQueryResult | None: 查询结果。若意图不在 LlamaIndex 处理范围
            或查询失败，返回 None 由上层降级到 Milvus。
        """
        # summarization 意图：通过 IndexManager 的 SummaryIndex 处理
        # （已在 rag_service._try_llamaindex_query 中处理，此处不重复）

        # comparison 意图：使用 SubQuestionQueryEngine
        if intent == "comparison" and sub_queries:
            result = await self._subquestion_engine.query(
                question=question,
                sub_queries=sub_queries,
                top_k=top_k,
            )
            if result.answer:
                return result
            # 子问题查询失败，返回 None 降级
            logger.debug("SubQuestionQueryEngine 返回空，降级到 Milvus")
            return None

        # 其他意图不在 LlamaIndex 处理范围
        return None

    def get_status(self) -> dict:
        """获取路由引擎状态。

        Returns:
            dict: 状态信息。
        """
        return {
            "subquestion_engine": "available",
            "router_strategy": "intent-based",
        }


# 模块级单例
subquestion_engine = SubQuestionQueryEngineWrapper()
router_engine = RouterEngineWrapper()
