"""问答（QA）请求/响应 Schema 模块。

定义 KB 内问答（``kbs.py``/``kb_qa.py``）共用的请求与响应模型，
避免端点在视图层重复定义 DTO。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """问答查询请求模型。

    Attributes:
        question: 用户问题文本，不可为空。
        top_k: 最终返回的文档片段数量，默认 5。
        doc_ids: 限定检索的文档 ID 列表，``None`` 表示不限制。
        use_graph: 是否启用知识图谱检索，默认开启。
        use_reranker: 是否启用重排，默认开启。
        session_id: 问答会话 ID（KB 内问答专用，传入则持久化消息到会话历史）。
    """

    question: str = Field(..., min_length=1, description="用户问题文本")
    top_k: int = Field(default=5, ge=1, description="返回的文档片段数量")
    doc_ids: list[str] | None = Field(
        default=None, description="限定检索的文档 ID 列表"
    )
    use_graph: bool = Field(default=True, description="是否启用知识图谱检索")
    use_reranker: bool = Field(default=True, description="是否启用重排")
    session_id: str | None = Field(
        default=None,
        description="问答会话 ID（KB 内问答专用，传入则持久化消息到会话历史）",
    )


class CitationModel(BaseModel):
    """引用来源响应模型。

    Attributes:
        document_id: 来源文档 ID。
        chunk_id: 来源分块 ID。
        content: 分块原文。
        score: 检索或重排分数。
        source: 来源类型，``"vector"`` 或 ``"graph"``。
    """

    document_id: str
    chunk_id: str
    content: str
    score: float
    source: str


class QueryResponse(BaseModel):
    """问答查询响应模型。

    Attributes:
        answer: LLM 生成的回答文本。
        intent: 查询意图分类。
        entities: 抽取的实体列表，每项为 ``{"text": str, "type": str}``。
        citations: 检索引用列表。
        retrieval_count: 向量检索返回的候选数量。
        rerank_count: 重排后保留的结果数量。
        query: 原始查询文本，便于前端关联。
    """

    answer: str
    intent: str
    entities: list[dict]
    citations: list[CitationModel]
    retrieval_count: int
    rerank_count: int
    query: str
