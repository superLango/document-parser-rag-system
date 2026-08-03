"""知识库内全文搜索端点模块（阶段 2 - 全文搜索）。

基于 PostgreSQL ``tsvector`` 生成列（``documents.search_vector``）+ GIN 索引，
提供跨文档的全文检索能力，``ts_headline`` 高亮命中片段。

- ``GET /kbs/{kb_id}/search``  全文搜索文档（viewer+）

知识库隔离要点：
- ``get_kb_context`` 已激活 RLS，``documents`` 表查询自动按 ``kb_id`` 过滤，
  全文搜索天然限定在当前 KB。
- ``search_vector`` 生成列覆盖 ``filename`` 与 ``parsed_text``，支持文件名与正文命中。
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DEFAULT_LIMIT, KBContext, get_db, get_kb_context, limiter
from app.core.logging import get_logger
from app.models.document import Document
from app.core.response import success

logger = get_logger(__name__)

router = APIRouter(prefix="/kbs/{kb_id}/search", tags=["知识库-全文搜索"])

# 单次返回最大条数
_MAX_RESULTS = 50


@router.get("")
@limiter.limit(DEFAULT_LIMIT)
async def search_documents(
    request: Request,
    q: str = Query(..., min_length=1, description="搜索关键词"),
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=_MAX_RESULTS, description="返回条数上限"),
) -> dict:
    """全文搜索当前 KB 内文档（viewer+）。

    使用 PostgreSQL ``tsvector`` 全文检索：
    - ``plainto_tsquery`` 处理用户输入（避免复杂查询语法注入）
    - ``ts_rank`` 按相关度排序
    - ``ts_headline`` 生成高亮片段（``<mark>`` 标签包裹命中词）

    RLS 已按 kb_id 过滤，搜索范围自动限定在当前 KB。

    Args:
        q: 搜索关键词。
        kb_ctx: 知识库上下文。
        db: 异步数据库会话。
        limit: 返回条数上限。

    Returns:
        dict: 含 ``items`` 与 ``total`` 的搜索结果列表。
    """
    # 构造 tsquery（plainto_tsquery 自动处理特殊字符，避免注入）
    tsquery = func.plainto_tsquery("simple", q)

    # ts_headline 生成高亮片段（取 parsed_text 前 2000 字符内匹配，避免全文字符串处理开销）
    headline = func.ts_headline(
        "simple",
        Document.parsed_text,
        tsquery,
        "StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=10, MaxFragments=3",
    )

    # 文件名高亮（短文本，单片段）
    filename_headline = func.ts_headline(
        "simple",
        Document.filename,
        tsquery,
        "StartSel=<mark>, StopSel=</mark>, MaxWords=20, MinWords=1, MaxFragments=1",
    )

    # 相关度排序
    rank = func.ts_rank(Document.search_vector, tsquery)

    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    stmt = (
        select(
            Document.id,
            Document.filename,
            Document.file_type,
            Document.status,
            Document.created_at,
            headline.label("snippet"),
            filename_headline.label("filename_highlight"),
            rank.label("rank"),
        )
        .where(
            Document.search_vector.op("@@")(tsquery),
            Document.kb_id == kb_ctx.kb_id,
        )
        .order_by(rank.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    items: list[dict] = []
    for row in rows:
        items.append({
            "id": str(row.id),
            "filename": row.filename,
            "filename_highlight": row.filename_highlight or row.filename,
            "file_type": row.file_type,
            "status": row.status,
            "snippet": row.snippet or "",
            "rank": float(row.rank) if row.rank is not None else 0.0,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        })

    logger.info(
        "KB 全文搜索",
        kb_id=str(kb_ctx.kb_id),
        query=q[:80],
        result_count=len(items),
    )

    return success(data={"items": items, "total": len(items), "query": q})
