# ruff: noqa: B008 - FastAPI Depends 默认参数为框架标准写法（与现有端点一致）
"""S8 术语集端点：术语集 CRUD + 外部源测试/预览/同步。"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    activate_kb_context,
    get_pagination_params,
    require_not_pending,
)
from app.api.v1.endpoints.kb_documents import _require_editor
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.glossary import (
    CronValidateRequest,
    DbTablesRequest,
    PreviewSqlRequest,
    TermBaseCreateRequest,
    TermBaseUpdateRequest,
    TermBatchRequest,
    TermBatchSaveRequest,
    TermCreateRequest,
    TermReviewRequest,
    TermUpdateRequest,
    TestApiRequest,
    TestDbRequest,
)
from app.services import kb_service
from app.services.glossary import source_db, term_base_service, term_service

router = APIRouter(prefix="/kb/{kb_id}/term-bases", tags=["知识库-术语集"])


@router.post("/cron-validate")
async def validate_cron_expr(
    kb_id: uuid.UUID, payload: CronValidateRequest, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    """校验 cron 表达式并返回下次执行时间（定时同步配置预览）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    data = await term_base_service.validate_cron(payload.cron)
    return success(data=data)


@router.get("/{term_base_id}/expanded-names")
async def list_term_base_expanded_names(
    kb_id: uuid.UUID, term_base_id: uuid.UUID,
    field: str | None = Query(default=None, description="取值字段名（如 NAME/term_name），缺省用 term_name"),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    """返回术语集按指定字段展开的类别名列表（与 Schema 术语类别展开一致）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    from app.services import extraction_config_service

    names = await extraction_config_service.list_term_base_expanded_names(db, kb_id, term_base_id, field)
    return success(data={"items": names})


async def _kb_access(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    data = await kb_service.get_kb(db, current_user, kb_id)
    await activate_kb_context(db, kb_id, current_user)
    return data


async def _ensure_manual_term_base(
    db: AsyncSession, kb_id: uuid.UUID, base_id: uuid.UUID
) -> None:
    """api/db 数据源术语集只读：禁止词条级写操作（对齐原项目只读模式）。"""
    base = await term_base_service.get_term_base(db, kb_id, base_id)
    if base.source_type != "manual":
        raise BusinessException(
            code=ErrorCode.BUSINESS_INVALID_STATE,
            message="外部数据源术语集为只读，请通过同步或修改数据源维护",
        )


@router.get("")
async def list_term_bases(
    kb_id: uuid.UUID,
    request: Request,
    keyword: str | None = Query(default=None, max_length=128),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """术语集列表（成员可读）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    page = pagination["page"]
    page_size = pagination["page_size"]
    items, total = await term_base_service.list_term_bases(
        db, kb_id, keyword, page, page_size
    )
    return paginated(items=items, total=total, page=page, page_size=page_size)


@router.post("")
@audit_action(action="term_base.create", resource_type="term_base")
async def create_term_base(
    kb_id: uuid.UUID,
    payload: TermBaseCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """创建术语集（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    result = await term_base_service.create_term_base(
        db, kb_id, current_user.id, payload.model_dump()
    )
    return success(data=result, message="术语集已创建")


@router.get("/{base_id}")
async def get_term_base(
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """术语集详情（成员可读）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    data = await term_base_service.get_term_base_detail(db, kb_id, base_id)
    return success(data=data)


@router.put("/{base_id}")
@audit_action(action="term_base.update", resource_type="term_base")
async def update_term_base(
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    payload: TermBaseUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """更新术语集（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await term_base_service.update_term_base(
        db, kb_id, base_id, payload.model_dump(exclude_none=True)
    )
    return success(data=data, message="术语集已更新")


@router.delete("/{base_id}")
@audit_action(action="term_base.delete", resource_type="term_base")
async def delete_term_base(
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """删除术语集（editor+，软删并级联软删词条）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await term_base_service.delete_term_base(db, kb_id, base_id)
    return success(message="术语集已删除")


@router.post("/test-api")
async def test_api(
    kb_id: uuid.UUID,
    payload: TestApiRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """API 源连通测试（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    from app.services.glossary import source_api

    try:
        result = await source_api.fetch_rows(payload.model_dump(), limit=10)
    except (ValueError, RuntimeError, TypeError) as exc:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message=str(exc)) from exc
    return success(
        data={"ok": True, "rows": result["rows"], "columns": result["columns"],
              "total": result["total"]},
        message="API 连接成功",
    )


@router.post("/test-db")
async def test_db(
    kb_id: uuid.UUID,
    payload: TestDbRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """DB 源连通测试（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    try:
        await source_db.test_db(payload.model_dump())
    except (ValueError, RuntimeError, TypeError) as exc:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message=str(exc)) from exc
    return success(message="数据库连接成功")


@router.post("/db-tables")
async def db_tables(
    kb_id: uuid.UUID,
    payload: DbTablesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """DB 表列表（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    try:
        tables = await source_db.list_tables(payload.model_dump())
    except (ValueError, RuntimeError, TypeError) as exc:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message=str(exc)) from exc
    return success(data={"tables": tables})


@router.post("/preview-sql")
async def preview_sql(
    kb_id: uuid.UUID,
    payload: PreviewSqlRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """SQL 预览（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    try:
        result = await source_db.preview_sql(payload.model_dump())
    except (ValueError, RuntimeError, TypeError) as exc:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message=str(exc)) from exc
    return success(data=result)


@router.post("/{base_id}/sync")
@audit_action(action="term_base.sync", resource_type="term_base")
async def sync_term_base(
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """从外部源同步词条（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    result = await term_base_service.sync_term_base(db, kb_id, base_id, current_user.id)
    return success(data=result, message="同步完成")


@router.put("/{base_id}/terms/batch")
@audit_action(action="term.batch_save", resource_type="term")
async def batch_save_terms(
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    payload: TermBatchSaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """术语集内批量保存（editor+，仅 manual）：新增/更新/删除一次提交。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await _ensure_manual_term_base(db, kb_id, base_id)
    result = await term_service.batch_save_terms(
        db, kb_id, base_id, current_user.id,
        [i.model_dump() for i in payload.items],
        payload.deleted_ids,
    )
    return success(data=result, message="保存成功")

terms_router = APIRouter(prefix="/kb/{kb_id}/terms", tags=["知识库-术语"])


@terms_router.get("")
async def list_terms(
    kb_id: uuid.UUID,
    request: Request,
    term_base_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=16),
    keyword: str | None = Query(default=None, max_length=256),
    search_field: str | None = Query(default=None, max_length=128, description="字段级搜索：manual 固定字段或 api/db 动态列名"),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """术语列表（成员可读，支持术语集/分类/状态/关键词/字段级搜索）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    page = pagination["page"]
    page_size = pagination["page_size"]
    items, total = await term_service.list_terms(
        db, kb_id, page, page_size,
        term_base_id=term_base_id, category=category, status=status,
        keyword=keyword, search_field=search_field,
    )
    return paginated(items=items, total=total, page=page, page_size=page_size)


@terms_router.get("/categories")
async def list_categories(
    kb_id: uuid.UUID,
    request: Request,
    term_base_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """分类列表（成员可读）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    categories = await term_service.list_categories(db, kb_id, term_base_id)
    return success(data={"categories": categories})


@terms_router.get("/export")
async def export_terms(
    kb_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> Response:
    """导出当前 KB 术语 CSV（成员可读）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    content = await term_service.export_terms(db, kb_id)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=terms.csv"},
    )


@terms_router.get("/{term_id}")
async def get_term(
    kb_id: uuid.UUID,
    term_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """术语详情（成员可读）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    data = await term_service.get_term_detail(db, kb_id, term_id)
    return success(data=data)


@terms_router.post("")
@audit_action(action="term.create", resource_type="term")
async def create_term(
    kb_id: uuid.UUID,
    payload: TermCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """创建术语（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await _ensure_manual_term_base(db, kb_id, uuid.UUID(str(payload.term_base_id)))
    data = await term_service.create_term(db, kb_id, current_user.id, payload.model_dump())
    return success(data=data, message="术语已创建")


@terms_router.post("/batch")
@audit_action(action="term.batch_import", resource_type="term")
async def batch_import_terms(
    kb_id: uuid.UUID,
    payload: TermBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """批量导入术语（editor+，≤5000 条，幂等）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    base_id = uuid.UUID(str(payload.items[0].get("term_base_id"))) if payload.items and payload.items[0].get("term_base_id") else None
    if base_id is None:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="批量导入必须指定术语集（items[0].term_base_id）")
    await _ensure_manual_term_base(db, kb_id, base_id)
    result = await term_service.batch_import_terms(db, kb_id, base_id, current_user.id, payload.items)
    return success(data=result, message="批量导入完成")


@terms_router.put("/{term_id}")
@audit_action(action="term.update", resource_type="term")
async def update_term(
    kb_id: uuid.UUID,
    term_id: uuid.UUID,
    payload: TermUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """更新术语（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    term = await term_service.get_term(db, kb_id, term_id)
    await _ensure_manual_term_base(db, kb_id, term.term_base_id)
    data = await term_service.update_term(db, kb_id, term_id, payload.model_dump(exclude_none=True))
    return success(data=data, message="术语已更新")


@terms_router.put("/{term_id}/review")
@audit_action(action="term.review", resource_type="term")
async def review_term(
    kb_id: uuid.UUID,
    term_id: uuid.UUID,
    payload: TermReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """审核术语（editor+：approve/reject）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    term = await term_service.get_term(db, kb_id, term_id)
    await _ensure_manual_term_base(db, kb_id, term.term_base_id)
    data = await term_service.review_term(db, kb_id, term_id, payload.action, current_user.id)
    return success(data=data, message="审核完成")


@terms_router.delete("/{term_id}")
@audit_action(action="term.delete", resource_type="term")
async def delete_term(
    kb_id: uuid.UUID,
    term_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """删除术语（editor+，软删）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    term = await term_service.get_term(db, kb_id, term_id)
    await _ensure_manual_term_base(db, kb_id, term.term_base_id)
    await term_service.delete_term(db, kb_id, term_id)
    return success(message="术语已删除")
