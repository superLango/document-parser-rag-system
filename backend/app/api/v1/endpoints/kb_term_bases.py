"""知识库内术语集管理端点（统一术语集：支持 manual/api/db 三种数据源）。

提供 KB 隔离的术语集（TermBase）CRUD、数据源测试、预览、导入等接口。
所有端点强制 ``Depends(get_kb_context)`` 实现知识库隔离与 RBAC 权限校验。

端点（前缀 ``/kbs/{kb_id}/term-bases``）：
- GET    /                    列出术语集（含数据源类型和术语数量）
- POST   /                    创建术语集（支持三种数据源类型，editor+）
- PUT    /{base_id}           更新术语集信息（editor+）
- DELETE /{base_id}           删除术语集（cascade 删除其下所有术语，editor+）
- POST   /test-api            测试API接口连接（无需创建术语集，editor+）
- POST   /test-db             测试数据库连接（无需创建术语集，editor+）
- POST   /db-tables           获取数据库的表列表（editor+）
- POST   /preview-sql         预览SQL查询结果（前5条，editor+）
- POST   /{base_id}/terms     获取术语集下的术语列表（支持分页，任意成员）
- PUT    /{base_id}/terms/batch  批量保存术语（新增/修改/删除，editor+）
- POST   /{base_id}/sync      从配置的数据源同步导入术语（editor+）
"""

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import KBContext, get_kb_context, get_pagination_params, require_role
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.models.knowledge_base import EDIT_ROLES
from app.models.term import SOURCE_TYPE_API, SOURCE_TYPE_DB, SOURCE_TYPE_MANUAL, Term, TermBase

router = APIRouter(prefix="/kbs/{kb_id}/term-bases", tags=["知识库-术语集"])


# ============================================================
# 请求体定义
# ============================================================
class ApiParam(BaseModel):
    """API参数配置。"""
    key: str
    value: str = ""
    in_location: Literal["query", "path", "header", "body"] = "query"
    enabled: bool = True


class ApiSourceConfig(BaseModel):
    """API数据源配置。"""
    url: str
    method: Literal["GET", "POST", "PUT", "DELETE"] = "GET"
    params: list[ApiParam] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    json_path: str = ""  # JSON路径提取数组，如"data.list"，空表示直接使用返回结果
    timeout: int = 30


class DbSourceConfig(BaseModel):
    """数据库数据源配置。"""
    db_type: Literal["mysql"] = "mysql"
    host: str
    port: int = 3306
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"
    mode: Literal["table", "sql"] = "table"
    table: str = ""
    sql_query: str = ""


class TermBaseCreateRequest(BaseModel):
    """术语集创建请求体（支持三种数据源）。"""
    name: str
    description: str = ""
    source_type: Literal["manual", "api", "db"] = SOURCE_TYPE_MANUAL
    source_config: dict[str, Any] = Field(default_factory=dict)
    columns: list[dict[str, Any]] = Field(default_factory=list)
    column_aliases: dict[str, str] = Field(default_factory=dict)
    # 创建后是否立即导入数据（api/db 类型下可设为true）
    auto_import: bool = False
    import_data: list[dict[str, Any]] | None = None


class TermBaseUpdateRequest(BaseModel):
    """术语集更新请求体。所有字段可选。"""
    name: str | None = None
    description: str | None = None
    source_config: dict[str, Any] | None = None
    columns: list[dict[str, Any]] | None = None
    column_aliases: dict[str, str] | None = None
    sync_enabled: bool | None = None


class TestApiRequest(ApiSourceConfig):
    """测试API连接请求。"""
    pass


class TestDbRequest(DbSourceConfig):
    """测试数据库连接请求。"""
    pass


class DbTablesRequest(BaseModel):
    """获取数据库表列表请求。"""
    db_type: Literal["mysql"] = "mysql"
    host: str
    port: int = 3306
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"


class PreviewSqlRequest(DbSourceConfig):
    """预览SQL查询结果请求。"""
    pass


class TermItemUpsert(BaseModel):
    """术语批量保存项。"""
    id: str | None = None
    term: str
    english_term: str = ""
    aliases: list[str] = []
    definition: str = ""
    category: str = ""
    synonyms: list[str] = []
    extras: dict[str, Any] = Field(default_factory=dict)


class TermBatchSaveRequest(BaseModel):
    """术语批量保存请求体。"""
    items: list[TermItemUpsert] = []
    deleted_ids: list[str] = []


# ============================================================
# 序列化工具
# ============================================================
def _serialize_base(tb: TermBase, term_count: int = 0) -> dict:
    """序列化 TermBase ORM 对象为响应字典。"""
    return {
        "id": str(tb.id),
        "kb_id": str(tb.kb_id),
        "name": tb.name,
        "description": tb.description or "",
        "source_type": tb.source_type,
        "source_config": tb.source_config or {},
        "columns": tb.columns or [],
        "column_aliases": tb.column_aliases or {},
        "sync_enabled": tb.sync_enabled,
        "last_synced_at": tb.last_synced_at.isoformat() if tb.last_synced_at else None,
        "term_count": term_count,
        "created_at": tb.created_at.isoformat() if tb.created_at else "",
        "updated_at": tb.updated_at.isoformat() if tb.updated_at else "",
    }


def _serialize_term(t: Term) -> dict:
    """序列化 Term ORM 对象为响应字典。"""
    return {
        "id": str(t.id),
        "term_base_id": str(t.term_base_id) if t.term_base_id else None,
        "term": t.term_name,
        "english_term": t.standard_name or "",
        "aliases": t.aliases or [],
        "definition": t.definition or "",
        "category": t.category or "",
        "synonyms": t.synonyms or [],
        "extras": t.extras or {},
        "standard_number": t.standard_number or "",
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "updated_at": t.updated_at.isoformat() if t.updated_at else "",
    }


# ============================================================
# 工具函数
# ============================================================
async def _get_term_base(
    db: AsyncSession,
    kb_id: UUID,
    base_id: UUID,
) -> TermBase:
    """获取术语集并验证 KB 归属，不存在则抛出异常。"""
    tb = (
        await db.execute(
            select(TermBase).where(
                TermBase.id == base_id,
                TermBase.kb_id == kb_id,
            )
        )
    ).scalar_one_or_none()
    if tb is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TERM_NOT_FOUND,
            message=f"术语集 {base_id} 不存在",
        )
    return tb


def _extract_json_path(data: Any, path: str) -> Any:
    """根据JSON路径提取数据。

    支持简单的点号分隔路径，如 "data.list" 或 "result.items"。
    空路径返回原数据。
    """
    if not path:
        return data
    parts = path.split(".")
    result = data
    for part in parts:
        if isinstance(result, dict):
            result = result.get(part)
        elif isinstance(result, list):
            try:
                idx = int(part)
                result = result[idx]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if result is None:
            return None
    return result


def _infer_columns(rows: list[dict]) -> list[dict]:
    """从数据行推断列定义。"""
    if not rows:
        return []
    columns = []
    sample = rows[0]
    for key in sample.keys():
        columns.append({
            "name": key,
            "type": "string",
            "label": key,
        })
    return columns


def _rows_to_terms(tb: TermBase, rows: list[dict], kb_id: UUID, reviewer_id: UUID) -> list[Term]:
    """将数据行转换为Term对象列表。

    对于 api/db 类型：
    - 所有字段均存入 extras（以原始字段名为 key）
    - term_name 设置为智能识别的名称列值，仅用于搜索
    - 不做标准字段（standard_name/definition/category/aliases）的自动映射，
      因为动态数据源的列名应由前端按原始字段名渲染表头

    名称列识别：优先匹配 name/term/value/term_name/名称 等常见命名，否则使用第一列。
    """
    now = datetime.now(timezone.utc)
    terms = []
    columns = tb.columns or []

    # 推断name列（用于term_name搜索字段）
    name_col = None
    for col in columns:
        cn = col.get("name", "").lower()
        if cn in ("name", "term", "value", "term_name", "名称", "术语名称"):
            name_col = col.get("name")
            break
    if not name_col and columns:
        name_col = columns[0].get("name")
    if not name_col and rows:
        name_col = list(rows[0].keys())[0] if rows[0] else None

    for row in rows:
        if not isinstance(row, dict):
            continue
        term_name = str(row.get(name_col, "")).strip() if name_col else ""
        if not term_name:
            continue

        # api/db 类型：所有字段都存入 extras，保留原始字段名
        extras = {}
        for k, v in row.items():
            if v is not None:
                extras[k] = v

        term = Term(
            kb_id=kb_id,
            term_base_id=tb.id,
            term_name=term_name,
            standard_name=None,
            definition=None,
            category=None,
            aliases=None,
            synonyms=None,
            extras=extras,
            status="active",
            reviewed_by=reviewer_id,
            reviewed_at=now,
        )
        terms.append(term)
    return terms


# ============================================================
# 术语集 CRUD
# ============================================================
@router.get("")
async def list_term_bases(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出当前 KB 下所有术语集（含数据源类型和术语数量统计）。"""
    rows = (
        await db.execute(
            select(TermBase, func.count(Term.id))
            .outerjoin(Term, Term.term_base_id == TermBase.id)
            .where(TermBase.kb_id == kb_ctx.kb_id)
            .group_by(TermBase.id)
            .order_by(TermBase.created_at.desc())
        )
    ).all()
    items = [_serialize_base(tb, cnt or 0) for tb, cnt in rows]
    return success(data={"items": items, "total": len(items)})


@router.post("")
async def create_term_base(
    body: TermBaseCreateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建术语集（editor+，支持三种数据源类型）。"""
    tb = TermBase(
        kb_id=kb_ctx.kb_id,
        name=body.name,
        description=body.description or None,
        source_type=body.source_type,
        source_config=body.source_config or {},
        columns=body.columns or [],
        column_aliases=body.column_aliases or {},
    )
    db.add(tb)
    await db.flush()

    # 如果提供了import_data（预览后创建），直接导入
    imported = 0
    if body.import_data and body.source_type in (SOURCE_TYPE_API, SOURCE_TYPE_DB):
        terms = _rows_to_terms(tb, body.import_data, kb_ctx.kb_id, kb_ctx.user.id)
        for term in terms:
            db.add(term)
        imported = len(terms)
        tb.last_synced_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(tb)

    count = (
        await db.execute(
            select(func.count()).select_from(Term).where(Term.term_base_id == tb.id)
        )
    ).scalar_one()

    result = _serialize_base(tb, count)
    result["imported"] = imported
    return success(data=result)


@router.put("/{base_id}")
async def update_term_base(
    base_id: UUID,
    body: TermBaseUpdateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新术语集信息（editor+）。"""
    tb = await _get_term_base(db, kb_ctx.kb_id, base_id)
    if body.name is not None:
        tb.name = body.name
    if body.description is not None:
        tb.description = body.description or None
    if body.source_config is not None:
        tb.source_config = body.source_config
    if body.columns is not None:
        tb.columns = body.columns
    if body.column_aliases is not None:
        tb.column_aliases = body.column_aliases
    if body.sync_enabled is not None:
        tb.sync_enabled = body.sync_enabled
    await db.commit()
    await db.refresh(tb)

    count = (
        await db.execute(
            select(func.count()).select_from(Term).where(Term.term_base_id == tb.id)
        )
    ).scalar_one()
    return success(data=_serialize_base(tb, count))


@router.delete("/{base_id}")
async def delete_term_base(
    base_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除术语集（cascade 删除其下所有术语，editor+）。"""
    tb = await _get_term_base(db, kb_ctx.kb_id, base_id)
    await db.delete(tb)
    await db.commit()
    return success(message="删除成功")


# ============================================================
# 数据源测试与预览接口
# ============================================================
@router.post("/test-api")
async def test_api_connection(
    body: TestApiRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
) -> dict:
    """测试API接口连接，返回接口响应（editor+，不保存）。"""
    try:
        headers = dict(body.headers)
        params = {}
        path_params = {}
        body_data = None
        json_body = None

        for p in body.params:
            if not p.enabled:
                continue
            if p.in_location == "query":
                params[p.key] = p.value
            elif p.in_location == "path":
                path_params[p.key] = p.value
            elif p.in_location == "header":
                headers[p.key] = p.value

        url = body.url
        for k, v in path_params.items():
            url = url.replace("{" + k + "}", v)

        if body.method in ("POST", "PUT"):
            if body.body:
                try:
                    json_body = json.loads(body.body)
                except json.JSONDecodeError:
                    body_data = body.body

        async with httpx.AsyncClient(timeout=body.timeout) as client:
            resp = await client.request(
                method=body.method,
                url=url,
                params=params if params else None,
                headers=headers if headers else None,
                json=json_body,
                data=body_data,
            )
            resp.raise_for_status()
            try:
                result = resp.json()
            except Exception:
                result = resp.text

        extracted = _extract_json_path(result, body.json_path)
        rows = []
        if isinstance(extracted, list):
            rows = extracted[:100]
        elif isinstance(extracted, dict):
            # 如果是dict，寻找第一个数组值
            for v in extracted.values():
                if isinstance(v, list):
                    rows = v[:100]
                    break

        return success(data={
            "status_code": resp.status_code,
            "raw_response": result if not isinstance(result, str) or len(result) < 5000 else result[:5000],
            "extracted_rows": rows[:5],
            "total_rows": len(rows),
            "columns": _infer_columns(rows),
        })
    except httpx.HTTPError as e:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message=f"API请求失败: {str(e)}",
        )
    except Exception as e:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message=f"测试失败: {str(e)}",
        )


def _get_mysql_dsn(cfg: DbSourceConfig | DbTablesRequest) -> str:
    """生成MySQL连接DSN。"""
    return f"mysql+pymysql://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.database}?charset={cfg.charset}"


@router.post("/test-db")
async def test_db_connection(
    body: TestDbRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
) -> dict:
    """测试数据库连接（editor+，不保存）。"""
    try:
        # 使用同步方式测试连接（pymysql是同步的，简单测试用同步）
        import pymysql
        conn = pymysql.connect(
            host=body.host,
            port=body.port,
            user=body.user,
            password=body.password,
            database=body.database,
            charset=body.charset,
            connect_timeout=10,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()
        cursor.close()
        conn.close()
        return success(data={
            "connected": True,
            "version": version[0] if version else "",
            "message": "数据库连接成功",
        })
    except ImportError:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message="缺少 pymysql 依赖，请联系管理员安装",
        )
    except Exception as e:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message=f"数据库连接失败: {str(e)}",
        )


@router.post("/db-tables")
async def list_db_tables(
    body: DbTablesRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
) -> dict:
    """获取数据库中的表列表（editor+）。"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=body.host,
            port=body.port,
            user=body.user,
            password=body.password,
            database=body.database,
            charset=body.charset,
            connect_timeout=10,
        )
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return success(data={"tables": tables})
    except ImportError:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message="缺少 pymysql 依赖，请联系管理员安装",
        )
    except Exception as e:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message=f"获取表列表失败: {str(e)}",
        )


@router.post("/preview-sql")
async def preview_sql(
    body: PreviewSqlRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
) -> dict:
    """预览SQL查询结果（前5条，editor+）。"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=body.host,
            port=body.port,
            user=body.user,
            password=body.password,
            database=body.database,
            charset=body.charset,
            connect_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )
        cursor = conn.cursor()

        if body.mode == "table" and body.table:
            sql = f"SELECT * FROM `{body.table}` LIMIT 5"
        elif body.mode == "sql" and body.sql_query:
            # 去除可能的分号，添加LIMIT
            sql = body.sql_query.rstrip(";").rstrip()
            # 如果已有LIMIT则不添加
            if "limit" not in sql.lower():
                sql += " LIMIT 5"
        else:
            raise BusinessException(
                code=ErrorCode.BUSINESS_VALIDATION_ERROR,
                message="请选择表或输入SQL查询",
            )

        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        cursor.close()
        conn.close()

        return success(data={
            "rows": rows,
            "columns": [{"name": c, "type": "string", "label": c} for c in columns],
            "total_preview": len(rows),
            "sql": sql,
        })
    except ImportError:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message="缺少 pymysql 依赖，请联系管理员安装",
        )
    except BusinessException:
        raise
    except Exception as e:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message=f"SQL执行失败: {str(e)}",
        )


# ============================================================
# 术语列表与批量保存
# ============================================================
@router.get("/{base_id}/terms")
async def list_terms(
    base_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, description="模糊搜索关键词"),
    search_field: str | None = Query(None, description="指定搜索字段名；为空则搜索全部字段"),
) -> dict:
    """获取术语集下的术语列表（支持分页，显式按 kb_id 过滤）。"""
    tb = await _get_term_base(db, kb_ctx.kb_id, base_id)

    page = pagination["page"]
    page_size = pagination["page_size"]

    base = select(Term).where(
        Term.kb_id == kb_ctx.kb_id,
        Term.term_base_id == base_id,
    )
    count_base = (
        select(func.count())
        .select_from(Term)
        .where(
            Term.kb_id == kb_ctx.kb_id,
            Term.term_base_id == base_id,
        )
    )

    if keyword:
        like = f"%{keyword}%"
        columns = tb.columns or []
        column_names = [c.get("name", "") for c in columns if c.get("name")]

        # 辅助：构建 extras 字段的 ilike 条件（兼容 JSON/JSONB，->> 返回文本）
        def _extras_ilike(field_name: str):
            return func.coalesce(
                cast(Term.extras.op('->>')(field_name), String),
                ''
            ).ilike(like)

        if search_field:
            # 指定字段搜索
            if tb.source_type == SOURCE_TYPE_MANUAL:
                # manual 类型固定字段映射（key: 字段标识 -> 列对象或 extras 字段名）
                fixed_field_map = {
                    "term": Term.term_name,
                    "term_name": Term.term_name,
                    "english_term": Term.standard_name,
                    "standard_name": Term.standard_name,
                    "definition": Term.definition,
                    "category": Term.category,
                    "aliases": Term.aliases,
                    "synonyms": Term.synonyms,
                }
                if search_field in fixed_field_map:
                    col = fixed_field_map[search_field]
                    if search_field in ("aliases", "synonyms"):
                        cond = func.cast(col, String).ilike(like)
                    else:
                        cond = col.ilike(like)
                else:
                    cond = _extras_ilike(search_field)
            else:
                # api/db 类型：名称列映射到 term_name，其他列在 extras
                name_col = None
                for col in columns:
                    cn = col.get("name", "").lower()
                    if cn in ("name", "term", "value", "term_name", "名称", "术语名称"):
                        name_col = col.get("name")
                        break
                if search_field == name_col:
                    cond = Term.term_name.ilike(like)
                else:
                    cond = _extras_ilike(search_field)
            base = base.where(cond)
            count_base = count_base.where(cond)
        else:
            # 未指定字段：搜索所有可搜索字段
            if tb.source_type == SOURCE_TYPE_MANUAL:
                cond = (
                    Term.term_name.ilike(like)
                    | Term.standard_name.ilike(like)
                    | Term.definition.ilike(like)
                    | Term.category.ilike(like)
                    | func.cast(Term.aliases, String).ilike(like)
                    | func.cast(Term.synonyms, String).ilike(like)
                )
            else:
                # api/db 类型：搜索 term_name + 所有 extras 列
                cond = Term.term_name.ilike(like)
                for cn in column_names:
                    cond = cond | _extras_ilike(cn)
            base = base.where(cond)
            count_base = count_base.where(cond)

    total = (await db.execute(count_base)).scalar_one()
    terms = (
        await db.execute(
            base.order_by(Term.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    # 对于 api/db 类型，确保 extras 包含所有列的值（兼容旧数据：部分列可能存在固定字段中）
    if tb.source_type != SOURCE_TYPE_MANUAL:
        columns = tb.columns or []
        # 构建列名到固定字段的映射（基于列名智能匹配）
        name_col = None
        field_map = {}  # column_name -> ('fixed_field_name', fixed_field_value_getter)
        for col in columns:
            cn = col.get("name", "").lower()
            if cn in ("name", "term", "value", "term_name", "名称", "术语名称"):
                name_col = col.get("name")
            elif cn in ("en", "english", "english_name", "standard_name", "英文名"):
                field_map[col.get("name")] = "standard_name"
            elif cn in ("desc", "description", "definition", "描述", "说明"):
                field_map[col.get("name")] = "definition"
            elif cn in ("category", "group", "type", "分类", "类别", "分组"):
                field_map[col.get("name")] = "category"

        serialized = []
        for t in terms:
            d = _serialize_term(t)
            extras = dict(d.get("extras") or {})
            # 补入名称列（旧数据中名称列在 term_name 中，不在 extras）
            if name_col and name_col not in extras:
                extras[name_col] = t.term_name or ""
            # 补入其他映射到固定字段的列
            for col_name, fixed_field in field_map.items():
                if col_name not in extras:
                    val = getattr(t, fixed_field, None)
                    if val is not None:
                        extras[col_name] = val
            # aliases 特殊处理：数组转逗号分隔
            for col in columns:
                cn = col.get("name", "").lower()
                if cn in ("alias", "aliases", "synonym", "别名") and col.get("name") not in extras:
                    aliases = t.aliases or []
                    extras[col.get("name")] = ", ".join(aliases) if aliases else ""
            d["extras"] = extras
            serialized.append(d)
        return paginated(serialized, total, page, page_size)

    return paginated([_serialize_term(t) for t in terms], total, page, page_size)


@router.put("/{base_id}/terms/batch")
async def batch_save_terms(
    base_id: UUID,
    body: TermBatchSaveRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量保存术语（editor+）。

    - items 中 id 为空的新增，有 id 的更新
    - deleted_ids 中的术语删除
    """
    tb = await _get_term_base(db, kb_ctx.kb_id, base_id)

    now = datetime.now(timezone.utc)
    created = 0
    updated = 0
    deleted = 0

    for del_id in body.deleted_ids:
        try:
            del_uuid = UUID(del_id)
        except ValueError:
            continue
        term = (
            await db.execute(
                select(Term).where(
                    Term.id == del_uuid,
                    Term.kb_id == kb_ctx.kb_id,
                    Term.term_base_id == tb.id,
                )
            )
        ).scalar_one_or_none()
        if term:
            await db.delete(term)
            deleted += 1

    for item in body.items:
        if not item.term:
            continue
        if item.id:
            try:
                term_uuid = UUID(item.id)
            except ValueError:
                continue
            term = (
                await db.execute(
                    select(Term).where(
                        Term.id == term_uuid,
                        Term.kb_id == kb_ctx.kb_id,
                        Term.term_base_id == tb.id,
                    )
                )
            ).scalar_one_or_none()
            if term:
                term.term_name = item.term
                term.standard_name = item.english_term or None
                term.aliases = item.aliases or None
                term.definition = item.definition or None
                term.category = item.category or None
                term.synonyms = item.synonyms or None
                term.extras = item.extras or {}
                term.updated_at = now
                updated += 1
                continue
        term = Term(
            kb_id=kb_ctx.kb_id,
            term_base_id=tb.id,
            term_name=item.term,
            standard_name=item.english_term or None,
            aliases=item.aliases or None,
            definition=item.definition or None,
            category=item.category or None,
            synonyms=item.synonyms or None,
            extras=item.extras or {},
            status="active",
            reviewed_by=kb_ctx.user.id,
            reviewed_at=now,
        )
        db.add(term)
        created += 1

    await db.commit()
    return success(data={
        "created": created,
        "updated": updated,
        "deleted": deleted,
    })


@router.post("/{base_id}/sync")
async def sync_from_source(
    base_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """从配置的数据源同步导入术语（editor+）。

    清空现有术语并重新从数据源导入。
    """
    tb = await _get_term_base(db, kb_ctx.kb_id, base_id)

    if tb.source_type == SOURCE_TYPE_MANUAL:
        raise BusinessException(
            code=ErrorCode.BUSINESS_VALIDATION_ERROR,
            message="手动录入类型的术语集不支持同步操作",
        )

    rows: list[dict] = []

    if tb.source_type == SOURCE_TYPE_API:
        cfg = tb.source_config or {}
        try:
            async with httpx.AsyncClient(timeout=cfg.get("timeout", 30)) as client:
                url = cfg.get("url", "")
                method = cfg.get("method", "GET")
                headers = cfg.get("headers", {})
                params = {}
                for p in cfg.get("params", []):
                    if p.get("enabled", True) and p.get("in_location") == "query":
                        params[p["key"]] = p.get("value", "")

                resp = await client.request(
                    method=method,
                    url=url,
                    params=params if params else None,
                    headers=headers if headers else None,
                )
                resp.raise_for_status()
                result = resp.json()
                extracted = _extract_json_path(result, cfg.get("json_path", ""))
                if isinstance(extracted, list):
                    rows = extracted
                elif isinstance(extracted, dict):
                    for v in extracted.values():
                        if isinstance(v, list):
                            rows = v
                            break
        except Exception as e:
            raise BusinessException(
                code=ErrorCode.BUSINESS_VALIDATION_ERROR,
                message=f"API同步失败: {str(e)}",
            )

    elif tb.source_type == SOURCE_TYPE_DB:
        cfg = tb.source_config or {}
        try:
            import pymysql
            conn = pymysql.connect(
                host=cfg.get("host", ""),
                port=cfg.get("port", 3306),
                user=cfg.get("user", ""),
                password=cfg.get("password", ""),
                database=cfg.get("database", ""),
                charset=cfg.get("charset", "utf8mb4"),
                connect_timeout=10,
                cursorclass=pymysql.cursors.DictCursor,
            )
            cursor = conn.cursor()
            if cfg.get("mode") == "table" and cfg.get("table"):
                cursor.execute(f"SELECT * FROM `{cfg['table']}`")
            elif cfg.get("mode") == "sql" and cfg.get("sql_query"):
                cursor.execute(cfg["sql_query"])
            else:
                cursor.close()
                conn.close()
                raise BusinessException(
                    code=ErrorCode.BUSINESS_VALIDATION_ERROR,
                    message="数据库配置不完整",
                )
            rows = cursor.fetchall()
            # 序列化datetime等非JSON类型
            for i, row in enumerate(rows):
                serialized = {}
                for k, v in row.items():
                    if isinstance(v, (datetime,)):
                        serialized[k] = v.isoformat()
                    elif v is None:
                        serialized[k] = ""
                    else:
                        serialized[k] = str(v) if not isinstance(v, (str, int, float, bool)) else v
                rows[i] = serialized
            cursor.close()
            conn.close()
        except ImportError:
            raise BusinessException(
                code=ErrorCode.BUSINESS_VALIDATION_ERROR,
                message="缺少 pymysql 依赖",
            )
        except BusinessException:
            raise
        except Exception as e:
            raise BusinessException(
                code=ErrorCode.BUSINESS_VALIDATION_ERROR,
                message=f"数据库同步失败: {str(e)}",
            )

    # 清空现有术语
    await db.execute(
        Term.__table__.delete().where(
            Term.term_base_id == tb.id,
            Term.kb_id == kb_ctx.kb_id,
        )
    )

    # 导入新术语
    terms = _rows_to_terms(tb, rows, kb_ctx.kb_id, kb_ctx.user.id)
    for term in terms:
        db.add(term)

    tb.last_synced_at = datetime.now(timezone.utc)
    await db.commit()

    return success(data={
        "imported": len(terms),
        "synced_at": tb.last_synced_at.isoformat(),
    })
