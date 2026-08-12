"""DB 数据源客户端（aiomysql）。

支持 MySQL：连接测试、表列表、SQL 预览、行拉取；超时与行数限制。
调用前需通过 security.validate_source_host 校验主机。
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

from .security import decrypt_secrets, validate_source_host

logger = get_logger(__name__)

_TIMEOUT = settings.TERM_SOURCE_CONNECT_TIMEOUT


def _conn_kwargs(cfg: dict) -> dict:
    """从配置构造 aiomysql 连接参数。"""
    validate_source_host(cfg.get("host", ""))
    return {
        "host": cfg["host"],
        "port": int(cfg.get("port") or 3306),
        "user": cfg.get("user", ""),
        "password": cfg.get("password", ""),
        "db": cfg.get("database", ""),
        "charset": cfg.get("charset") or "utf8mb4",
        "connect_timeout": _TIMEOUT,
    }


async def _connect(cfg: dict):
    import aiomysql

    kwargs = _conn_kwargs(cfg)
    try:
        return await aiomysql.connect(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"数据库连接失败：{exc}") from exc


async def test_db(config: dict) -> dict[str, Any]:
    """连接测试：SELECT 1。"""
    conn = await _connect(decrypt_secrets(config))
    try:
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"数据库连接测试失败：{exc}") from exc
        return {"ok": True}
    finally:
        conn.close()


async def list_tables(config: dict) -> list[str]:
    """列出数据库表名。"""
    conn = await _connect(decrypt_secrets(config))
    try:
        try:
            async with conn.cursor() as cur:
                await cur.execute("SHOW TABLES")
                return [r[0] for r in await cur.fetchall()]
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"数据库表查询失败：{exc}") from exc
    finally:
        conn.close()


def _json_safe(value: Any) -> Any:
    """将数据库行值转为 JSONB 可安全存储的类型。"""
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return repr(value)
    return value


def _with_limit(sql: str, limit: int) -> str:
    stripped = sql.rstrip().rstrip(";").strip()
    if stripped.lower().endswith("limit") or "limit" in stripped.lower()[-30:]:
        return stripped
    return f"{stripped} LIMIT {limit}"


async def _query_rows(cfg: dict, sql: str, limit: int) -> tuple[list[dict], list[dict]]:
    conn = await _connect(cfg)
    try:
        try:
            async with conn.cursor() as cur:
                await cur.execute(_with_limit(sql, limit))
                cols = [d[0] for d in cur.description or []]
                raw = await cur.fetchall()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"数据库查询失败：{exc}") from exc
        rows = [dict(zip(cols, (_json_safe(v) for v in r))) for r in raw]
        columns = [
            {"name": c, "type": "string", "label": c} for c in cols
        ]
        return rows, columns
    finally:
        conn.close()


async def preview_sql(config: dict, limit: int = 5) -> dict[str, Any]:
    """SQL 预览（前 limit 条）。"""
    cfg = decrypt_secrets(config)
    sql = cfg.get("sql_query") or cfg.get("sql") or ""
    if not sql.strip():
        raise RuntimeError("SQL 不能为空")
    rows, columns = await _query_rows(cfg, sql, limit)
    return {"rows": rows, "columns": columns, "total": len(rows)}


async def fetch_rows(config: dict, limit: int = 1000) -> dict[str, Any]:
    """按模式（table/sql）拉取行数据。"""
    cfg = decrypt_secrets(config)
    mode = cfg.get("mode") or "table"
    if mode == "table":
        table = cfg.get("table") or ""
        if not table.strip():
            raise RuntimeError("表名不能为空")
        sql = f"SELECT * FROM `{table}`"
    else:
        sql = cfg.get("sql_query") or cfg.get("sql") or ""
        if not sql.strip():
            raise RuntimeError("SQL 不能为空")
    rows, columns = await _query_rows(cfg, sql, limit)
    return {"rows": rows, "columns": columns, "total": len(rows)}
