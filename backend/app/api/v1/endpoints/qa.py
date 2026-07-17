"""问答（QA）端点模块。

本模块定义基于 RAG 引擎的问答接口，包括：

- ``POST /qa/query``：标准查询，返回完整 RAG 响应（回答、引用、查询分析）
- ``POST /qa/stream``：SSE 流式查询，逐块推送 LLM 生成内容
- ``GET /qa/health``：RAG 引擎健康检查

标准查询返回 ``QueryResponse`` 模型，包含回答文本、意图、实体、引用列表
以及检索/重排数量。流式查询通过 Server-Sent Events 协议推送文本分片，
便于前端实现打字机效果。

所有接口均需 Bearer Token 鉴权。
"""

import json
from dataclasses import asdict

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.user import User
from app.services.rag_service import Citation, RAGResponse, rag_service

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------
# 请求与响应模型
# ---------------------------------------------------------------
class QueryRequest(BaseModel):
    """问答查询请求模型。

    Attributes:
        question: 用户问题文本，不可为空。
        top_k: 最终返回的文档片段数量，默认 5。
        doc_ids: 限定检索的文档 ID 列表，``None`` 表示不限制。
        use_graph: 是否启用知识图谱检索，默认开启。
        use_reranker: 是否启用重排，默认开启。
    """

    question: str = Field(..., min_length=1, description="用户问题文本")
    top_k: int = Field(default=5, ge=1, description="返回的文档片段数量")
    doc_ids: list[str] | None = Field(
        default=None, description="限定检索的文档 ID 列表"
    )
    use_graph: bool = Field(default=True, description="是否启用知识图谱检索")
    use_reranker: bool = Field(default=True, description="是否启用重排")


class CitationModel(BaseModel):
    """引用来源响应模型。

    与 ``Citation`` 数据类字段对齐，用于 API 响应序列化。

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

    封装 RAG 查询的完整结果，包含回答、引用以及检索统计信息。

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


# ---------------------------------------------------------------
# 端点定义
# ---------------------------------------------------------------
@router.post("/query", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> QueryResponse:
    """标准问答查询，返回完整 RAG 响应。

    处理流程：
        1. 调用 ``rag_service.query`` 执行完整 RAG 流程（查询理解 →
           检索 → 重排 → 上下文组装 → LLM 生成）。
        2. 将 ``RAGResponse`` 转换为 ``QueryResponse`` 返回给前端。

    Args:
        request: 查询请求体，包含问题与可选的检索参数。
        db: 异步数据库会话（保留用于未来扩展，当前 RAG 流程不直接使用）。
        current_user: 当前已认证用户。

    Returns:
        QueryResponse: 包含回答、引用与检索统计的响应对象。
    """
    logger.info(
        "收到问答查询",
        question=request.question[:100],
        top_k=request.top_k,
        use_graph=request.use_graph,
        use_reranker=request.use_reranker,
    )

    # 调用 RAG 服务执行完整查询流程
    rag_response: RAGResponse = await rag_service.query(
        question=request.question,
        top_k=request.top_k,
        doc_ids=request.doc_ids,
        use_graph=request.use_graph,
        use_reranker=request.use_reranker,
    )

    # 将 Citation 数据类转换为 CitationModel 响应模型
    citations: list[CitationModel] = [
        CitationModel(**asdict(c)) for c in rag_response.citations
    ]

    logger.info(
        "问答查询完成",
        intent=rag_response.intent,
        retrieval_count=rag_response.retrieval_count,
        rerank_count=rag_response.rerank_count,
        citation_count=len(citations),
    )

    return QueryResponse(
        answer=rag_response.answer,
        intent=rag_response.intent,
        entities=rag_response.entities,
        citations=citations,
        retrieval_count=rag_response.retrieval_count,
        rerank_count=rag_response.rerank_count,
        query=request.question,
    )


@router.post("/stream")
async def query_stream(
    request: QueryRequest,
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """SSE 流式问答查询。

    通过 Server-Sent Events 协议逐块推送 LLM 生成内容，便于前端实现
    打字机效果。事件格式遵循以下规范：

    - 文本分片：``data: {"chunk": "..."}\\n\\n``
    - 结束标记：``data: {"done": true}\\n\\n``
    - 错误信息：``data: {"error": "..."}\\n\\n``

    前置阶段（查询理解、检索、重排、上下文组装）同步完成后，再通过
    ``rag_service.query_stream`` 逐块 yield 文本。

    Args:
        request: 查询请求体，包含问题与可选的检索参数。
        current_user: 当前已认证用户。

    Returns:
        StreamingResponse: ``text/event-stream`` 类型的流式响应。
    """
    logger.info(
        "收到流式问答查询",
        question=request.question[:100],
        top_k=request.top_k,
    )

    async def event_generator():
        """SSE 事件生成器。

        调用 ``rag_service.query_stream`` 获取 LLM 生成分片，逐块格式化
        为 SSE 事件。流式生成过程中发生异常时推送错误事件并终止。
        """
        try:
            async for chunk in rag_service.query_stream(
                question=request.question,
                top_k=request.top_k,
                doc_ids=request.doc_ids,
                use_graph=request.use_graph,
                use_reranker=request.use_reranker,
            ):
                payload: dict = {"chunk": chunk}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # 正常结束，推送 done 事件
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        except Exception as err:
            # 流式生成过程中发生异常，推送错误事件
            logger.error(
                "流式问答查询失败",
                error=str(err),
                exc_info=True,
            )
            error_payload: dict = {"error": str(err)}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲，确保实时推送
        },
    )


@router.get("/health")
async def qa_health() -> dict:
    """RAG 引擎健康检查。

    返回 RAG 服务的健康状态，用于监控与负载均衡探针。

    Returns:
        dict: 包含状态与服务标识的字典，例如
            ``{"status": "healthy", "service": "rag"}``。
    """
    return {"status": "healthy", "service": "rag"}


@router.post("/build-llamaindex")
async def build_llamaindex_index(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """手动触发 LlamaIndex 辅助索引构建。

    从数据库加载所有已索引文档的 parsed_text，分块后转换为
    LlamaIndex TextNode，调用 index_manager.build_indices() 构建
    SummaryIndex / TreeIndex / KeywordTableIndex。

    用于后端进程启动后恢复 LlamaIndex 索引（arq worker 构建的
    索引存在于 worker 进程，后端进程需单独构建）。
    """
    import asyncio
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.document import Document

    try:
        from llama_index.core.schema import TextNode as LITextNode
        from app.services.index_manager import index_manager
    except ImportError:
        return {"status": "skipped", "message": "llama-index-core 未安装"}

    # 1. 查询所有已索引文档
    async with AsyncSessionLocal() as db:
        stmt = select(Document).where(Document.status == "indexed")
        result = await db.execute(stmt)
        documents = list(result.scalars().all())

    if not documents:
        return {"status": "no_documents", "message": "没有已索引的文档"}

    # 2. 表格感知分块（P1.1 优化）：常规分块 + PDF 表格提取
    from app.services.chunking_service import chunker
    from app.services.table_extractor import table_extractor

    # 本地 PDF 查找目录（测试文档存放路径）
    import os
    _PDF_DIR = os.environ.get(
        "TEST_PDF_DIR", "/home/hanson/doc_parse_project/test_standard_doc"
    )

    all_nodes: list[LITextNode] = []
    table_node_count = 0
    for doc in documents:
        text = doc.parsed_text or ""
        if not text.strip():
            continue

        # 查找本地 PDF 文件用于表格提取
        pdf_path: str | None = None
        if doc.filename:
            candidate = os.path.join(_PDF_DIR, doc.filename)
            if os.path.isfile(candidate):
                pdf_path = candidate

        doc_meta = {
            "doc_id": str(doc.id),
            "doc_title": doc.filename or "",
            "file_name": doc.filename or "",
        }

        # 表格感知分块：常规文本分块 + 表格独立分块
        chunks = await chunker.chunk_document_with_tables(
            text, doc_meta, pdf_path=pdf_path
        )

        for chunk in chunks:
            chunk_text = chunk.get("text", "")
            if len(chunk_text) < 10:
                continue
            chunk_meta = chunk.get("metadata", {})
            node = LITextNode(
                id_=chunk.get("chunk_id", f"{doc.id}_{len(all_nodes)}"),
                text=chunk_text,
                metadata={
                    "doc_id": str(doc.id),
                    "doc_title": doc.filename or "",
                    "file_name": doc.filename or "",
                    "chunk_type": chunk_meta.get("chunk_type", "text"),
                    "title_chain": chunk_meta.get("title_chain", ""),
                },
            )
            all_nodes.append(node)
            if chunk_meta.get("chunk_type") == "table":
                table_node_count += 1

    # 3. 构建 LlamaIndex 索引
    await index_manager.build_indices(all_nodes)

    return {
        "status": "success",
        "document_count": len(documents),
        "node_count": len(all_nodes),
        "table_node_count": table_node_count,
        "summary_available": index_manager._summary_available,
        "tree_available": index_manager._tree_available,
        "keyword_available": index_manager._keyword_available,
    }
