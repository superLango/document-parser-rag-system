"""知识库内问答（QA）端点模块（方案 §10.3）。

提供 KB 隔离的 RAG 问答接口，所有端点强制 ``Depends(get_kb_context)``，
通过 ``kb_id`` 将检索限定在 KB 专属向量 Collection 与图谱 space：

- ``POST /kbs/{kb_id}/qa/query``   标准查询，返回完整 RAG 响应（viewer+）
- ``POST /kbs/{kb_id}/qa/stream``  SSE 流式查询，逐块推送 LLM 生成内容（viewer+）
- ``GET  /kbs/{kb_id}/qa/health``  RAG 引擎健康检查（viewer+）

知识库隔离要点：
- 向量检索：``rag_service`` 将 ``kb_id`` 透传至 ``vector_store.hybrid_search``，
  命中 ``doc_chunks_{kb_id_hex}`` 专属 Collection。
- 图谱检索：``kb_id`` 透传至 ``graph_store.search_nodes/get_subgraph``，
  命中 ``kb_{kb_id_hex}`` 专属 graph space。
- 多级缓存：L1/L2/L3 缓存键均带 ``kb:{kb_id}:`` 前缀，避免跨 KB 缓存污染。
- 全局路径降级：BM25 与 LlamaIndex 索引为全局构建（未按 KB 隔离），
  KB 查询时自动跳过，避免跨 KB 数据泄漏。

与旧 ``qa.py``（全局，向后兼容）共存，本模块为 KB 化主入口。
"""

import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AI_LIMIT, DEFAULT_LIMIT, KBContext, get_db, get_kb_context, limiter
from app.core.logging import get_logger
from app.services.qa_history_service import add_message, ensure_session
from app.services.rag.rag_service import RAGResponse, rag_service

# 复用全局 qa 模块的请求/响应模型，保持两端契约一致
from app.api.v1.endpoints.qa import CitationModel, QueryRequest, QueryResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/kbs/{kb_id}/qa", tags=["知识库-智能问答"])


@router.post("/query", response_model=QueryResponse)
@limiter.limit(AI_LIMIT)
async def kb_query(
    body: QueryRequest,
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """知识库内标准问答查询，返回完整 RAG 响应（viewer+）。

    处理流程与全局 ``POST /qa/query`` 一致，区别在于：
    - ``kb_id`` 透传至检索层与缓存层，确保检索范围与缓存命名空间均限定在当前 KB。
    - 若 ``request.session_id`` 提供，则持久化本轮问答到会话历史（user + assistant 消息）。
      首次问答自动回填会话标题。

    Args:
        request: 查询请求体，包含问题与可选的检索参数与会话 ID。
        kb_ctx: 知识库上下文（已校验成员资格 + 激活 RLS）。
        db: 异步数据库会话。

    Returns:
        QueryResponse: 包含回答、引用与检索统计的响应对象。
    """
    logger.info(
        "收到 KB 问答查询",
        kb_id=str(kb_ctx.kb_id),
        question=body.question[:100],
        top_k=body.top_k,
        use_graph=body.use_graph,
        use_reranker=body.use_reranker,
        has_session=bool(body.session_id),
    )

    rag_response: RAGResponse = await rag_service.query(
        question=body.question,
        top_k=body.top_k,
        doc_ids=body.doc_ids,
        use_graph=body.use_graph,
        use_reranker=body.use_reranker,
        kb_id=kb_ctx.kb_id,
    )

    citations: list[CitationModel] = [
        CitationModel(**asdict(c)) for c in rag_response.citations
    ]

    # 持久化到会话历史：默认开启，无 session_id 时自动创建新会话
    final_session_id = body.session_id
    try:
        session = await ensure_session(
            db, kb_ctx.kb_id, kb_ctx.user.id, final_session_id
        )
        # 显式按 kb_id 过滤会话，纵深防御不依赖 RLS（superuser 绕过 RLS）
        await add_message(
            db, session.id, "user", body.question, kb_id=kb_ctx.kb_id
        )
        await add_message(
            db,
            session.id,
            "assistant",
            rag_response.answer,
            citations=[c.model_dump() for c in citations],
            kb_id=kb_ctx.kb_id,
        )
        await db.commit()
        final_session_id = str(session.id)
    except Exception as err:
        logger.warning("问答历史持久化失败（不阻断问答）", error=str(err))
        await db.rollback()

    logger.info(
        "KB 问答查询完成",
        kb_id=str(kb_ctx.kb_id),
        intent=rag_response.intent,
        retrieval_count=rag_response.retrieval_count,
        rerank_count=rag_response.rerank_count,
        citation_count=len(citations),
        session_id=final_session_id,
    )

    return QueryResponse(
        answer=rag_response.answer,
        intent=rag_response.intent,
        entities=rag_response.entities,
        citations=citations,
        retrieval_count=rag_response.retrieval_count,
        rerank_count=rag_response.rerank_count,
        query=body.question,
    )


@router.post("/stream")
@limiter.limit(AI_LIMIT)
async def kb_query_stream(
    request: Request,
    body: QueryRequest,
    kb_ctx: KBContext = Depends(get_kb_context),
) -> StreamingResponse:
    """知识库内 SSE 流式问答查询（viewer+）。

    通过 Server-Sent Events 协议逐块推送 LLM 生成内容，``kb_id`` 透传至
    检索层确保流式生成前的检索阶段同样限定在当前 KB。

    历史持久化：流式完成后在独立会话内追加 user + assistant 消息。
    通过 ``data: {"session_id": "...", "done": true}`` 事件回传会话 ID，
    供前端关联后续问答到同一会话。

    事件格式：
    - 文本分片：``data: {"chunk": "..."}\\n\\n``
    - 结束标记：``data: {"done": true, "session_id": "..."}\\n\\n``
    - 错误信息：``data: {"error": "..."}\\n\\n``

    Args:
        request: FastAPI 请求对象（slowapi 限流所需）。
        body: 查询请求体。
        kb_ctx: 知识库上下文。

    Returns:
        StreamingResponse: ``text/event-stream`` 类型的流式响应。
    """
    logger.info(
        "收到 KB 流式问答查询",
        kb_id=str(kb_ctx.kb_id),
        question=body.question[:100],
        top_k=body.top_k,
        has_session=bool(body.session_id),
    )

    async def event_generator():
        """SSE 事件生成器（KB 隔离 + 历史持久化 + citations返回）。"""
        full_answer: list[str] = []
        session_id_str: str | None = body.session_id
        citations_list: list[CitationModel] = []
        try:
            from app.services.rag.rag_service import _SYSTEM_PROMPT, _INTENT_ANSWER_TEMPLATES
            from app.services.llm.llm_service import llm_service

            context, rag_citations, analysis = await rag_service.retrieve(
                question=body.question,
                top_k=body.top_k,
                doc_ids=body.doc_ids,
                use_graph=body.use_graph,
                use_reranker=body.use_reranker,
                kb_id=kb_ctx.kb_id,
            )

            if not context:
                yield f"data: {json.dumps({'error': '向量检索失败，无法获取相关文档'}, ensure_ascii=False)}\n\n"
                return

            is_llamaindex = context and rag_citations and all(c.source == "llamaindex" for c in rag_citations)

            citations_list = [
                CitationModel(**asdict(c)) for c in rag_citations
            ]

            template_suffix = _INTENT_ANSWER_TEMPLATES.get(analysis.intent, "")
            stream_system_prompt = _SYSTEM_PROMPT + template_suffix if template_suffix else _SYSTEM_PROMPT

            if is_llamaindex:
                async for chunk in rag_service._stream_chunks(context):
                    full_answer.append(chunk)
                    payload: dict = {"chunk": chunk}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:
                async for chunk in llm_service.stream_generate(
                    prompt=context,
                    system_prompt=stream_system_prompt,
                ):
                    full_answer.append(chunk)
                    payload = {"chunk": chunk}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            try:
                from app.core.database import AsyncSessionLocal
                from app.api.deps import activate_rls

                async with AsyncSessionLocal() as hist_db:
                    await activate_rls(hist_db, kb_ctx.kb_id)
                    session = await ensure_session(
                        hist_db, kb_ctx.kb_id, kb_ctx.user.id, session_id_str
                    )
                    await add_message(
                        hist_db, session.id, "user", body.question, kb_id=kb_ctx.kb_id
                    )
                    await add_message(
                        hist_db,
                        session.id,
                        "assistant",
                        "".join(full_answer),
                        citations=[c.model_dump() for c in citations_list],
                        kb_id=kb_ctx.kb_id,
                    )
                    await hist_db.commit()
                    session_id_str = str(session.id)
            except Exception as persist_err:
                logger.warning("流式问答历史持久化失败", error=str(persist_err))

            done_payload: dict = {
                'done': True,
                'session_id': session_id_str,
                'citations': [c.model_dump() for c in citations_list],
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
        except Exception as err:
            logger.error(
                "KB 流式问答查询失败",
                kb_id=str(kb_ctx.kb_id),
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
@limiter.limit(DEFAULT_LIMIT)
async def kb_qa_health(
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """知识库问答引擎健康检查（viewer+）。

    Returns:
        dict: 包含状态、服务标识与当前 KB ID 的字典。
    """
    return {
        "status": "healthy",
        "service": "rag",
        "kb_id": str(kb_ctx.kb_id),
    }
