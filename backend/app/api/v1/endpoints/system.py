"""系统级端点（阶段 1.6）。

提供系统健康检查与信息查询接口（前缀 ``/system``）：

- GET /system/health          基础健康检查（轻量，探针用）
- GET /system/health/deep     深度健康检查（并行检查所有依赖）
- GET /system/health/models   模型服务健康（LLM/Embedding/OCR）
- GET /system/health/storage  存储服务健康（PostgreSQL/Redis/MinIO/Milvus/Nebula）
- GET /system/info            系统信息（版本/配置摘要）

健康检查端点对已认证用户开放（非超管可见状态，但不暴露敏感配置）。
"""

import asyncio
import platform
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.response import success
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/system", tags=["系统管理"])


async def _check_postgres(db: AsyncSession) -> dict:
    """检查 PostgreSQL 连接。"""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy", "latency_ms": None}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unhealthy", "error": str(exc)[:200]}


async def _check_redis() -> dict:
    """检查 Redis 连接。"""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        pong = await client.ping()
        await client.aclose()
        return {"status": "healthy" if pong else "unhealthy"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unhealthy", "error": str(exc)[:200]}


async def _check_milvus() -> dict:
    """检查 Milvus 连接。"""
    try:
        from pymilvus import connections

        if not connections.has_connection("default"):
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=str(settings.MILVUS_PORT),
                timeout=3,
            )
        return {"status": "healthy", "host": f"{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "error": str(exc)[:200]}


async def _check_minio() -> dict:
    """检查 MinIO 连接。"""
    try:
        from app.services.infra.storage_service import storage_service

        client = storage_service._get_client()
        await asyncio.to_thread(client.list_buckets)
        return {"status": "healthy", "endpoint": settings.MINIO_ENDPOINT}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unhealthy", "error": str(exc)[:200]}


async def _check_nebula() -> dict:
    """检查 NebulaGraph 连接。"""
    try:
        from app.services.graph.graph_store import graph_store

        connected = graph_store._try_connect()
        return {"status": "healthy" if connected else "unavailable"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unhealthy", "error": str(exc)[:200]}


async def _check_llm() -> dict:
    """检查 LLM 抽取服务（端口 9988）。"""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"http://localhost:9988/health")
            return {"status": "healthy" if resp.status_code < 500 else "unhealthy"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "error": str(exc)[:200]}


async def _check_embedding() -> dict:
    """检查 Embedding 服务（轻量检查，不加载模型）。"""
    try:
        return {"status": "healthy", "model": "bge-m3 (lazy-load)"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unhealthy", "error": str(exc)[:200]}


async def _check_ocr_layout() -> dict:
    """检查 OCR 版面分析模型（PP-DocLayoutV3）是否可用。"""
    try:
        from app.services.ocr import ocr_service
        loop = asyncio.get_event_loop()
        available = await loop.run_in_executor(None, ocr_service.is_layout_model_available)
        if available:
            from app.services.ocr.ocr_config import ocr_config
            return {
                "status": "healthy",
                "model": "PP-DocLayoutV3",
                "model_dir": ocr_config.layout_model_dir,
            }
        else:
            return {"status": "unavailable", "error": "版面分析模型未加载或初始化失败"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "error": str(exc)[:200]}


async def _check_ocr_vllm() -> dict:
    """检查 OCR vLLM 服务（端口 9977）。"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get("http://localhost:9977/health")
            return {"status": "healthy" if resp.status_code < 500 else "unhealthy"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "error": str(exc)[:200]}


@router.get("/health")
async def health() -> dict:
    """基础健康检查（轻量，探针用）。"""
    return success(data={"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


@router.get("/health/deep")
async def deep_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """深度健康检查（并行检查所有依赖，带超时保护）。

    并行执行 PostgreSQL/Redis/MinIO/Milvus/Nebula/LLM/Embedding 检查，
    返回各项状态汇总与整体状态（任一 unhealthy 则整体 degraded）。
    """
    async def _safe_check(coro, name: str) -> dict:
        try:
            return await asyncio.wait_for(coro, timeout=5.0)
        except asyncio.TimeoutError:
            return {"status": "timeout", "error": f"{name} check timed out"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    checks = await asyncio.gather(
        _safe_check(_check_postgres(db), "postgres"),
        _safe_check(_check_redis(), "redis"),
        _safe_check(_check_minio(), "minio"),
        _safe_check(_check_milvus(), "milvus"),
        _safe_check(_check_nebula(), "nebula"),
        _safe_check(_check_llm(), "llm"),
        _safe_check(_check_embedding(), "embedding"),
    )
    names = ["postgres", "redis", "minio", "milvus", "nebula", "llm", "embedding"]
    result = {name: check for name, check in zip(names, checks)}

    unhealthy = [n for n, c in result.items() if c.get("status") != "healthy"]
    overall = "healthy" if not unhealthy else ("degraded" if len(unhealthy) < len(names) else "unhealthy")
    return success(data={"status": overall, "checks": result, "timestamp": datetime.now(timezone.utc).isoformat()})


@router.get("/health/models")
async def models_health(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """模型服务健康检查（LLM/Embedding/OCR版面分析/OCR vLLM）。"""
    llm, embedding, ocr_layout, ocr_vllm = await asyncio.gather(
        _check_llm(), _check_embedding(), _check_ocr_layout(), _check_ocr_vllm()
    )
    return success(data={
        "llm": llm,
        "embedding": embedding,
        "ocr_layout": ocr_layout,
        "ocr_vllm": ocr_vllm,
    })


@router.get("/health/storage")
async def storage_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """存储服务健康检查（PostgreSQL/Redis/MinIO/Milvus/Nebula）。"""
    pg, redis, minio, milvus, nebula = await asyncio.gather(
        _check_postgres(db), _check_redis(), _check_minio(), _check_milvus(), _check_nebula()
    )
    return success(data={
        "postgres": pg, "redis": redis, "minio": minio, "milvus": milvus, "nebula": nebula
    })


@router.get("/info")
async def system_info(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """系统信息（版本/运行环境/配置摘要，脱敏不暴露密钥）。"""
    return success(data={
        "app_name": "HansonDOC RAG",
        "version": "2.0.0",
        "env": settings.APP_ENV,
        "debug": settings.DEBUG,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "components": {
            "milvus": f"{settings.MILVUS_HOST}:{settings.MILVUS_PORT}",
            "minio": settings.MINIO_ENDPOINT,
            "nebula": f"{settings.NEBULA_GRAPHD_HOST}:{settings.NEBULA_GRAPHD_PORT}",
            "redis": settings.REDIS_URL.split("@")[-1] if "@" in settings.REDIS_URL else "configured",
            "llm_service": "localhost:9988",
        },
        "features": {
            "kb_isolation": True,
            "domain_templates": ["material_testing", "medical_device", "contract", "general_qa"],
            "hook_mechanism": True,
            "rbac": True,
            "audit_log": True,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ============================================================
# 资源清理端点（阶段 3 - 资源清理）
# ============================================================
@router.post("/cleanup")
async def run_cleanup(
    current_user: User = Depends(get_current_active_user),
    dry_run: bool = Query(False, description="True=仅预览不删除"),
) -> dict:
    """执行资源清理（超管专属）。

    清理项：过期任务 / 审计日志归档 / 孤儿向量 / 孤儿图谱节点 / 临时文件。
    ``dry_run=True`` 时仅统计不删除，便于预览。
    """
    if not current_user.is_superuser:
        from app.core.exceptions import PermissionException, ErrorCode
        raise PermissionException(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            message="仅超管可执行资源清理",
        )
    from app.tasks.cleanup_tasks import run_full_cleanup
    results = await run_full_cleanup(dry_run=dry_run)
    return success(data=results)


@router.get("/cleanup/dry-run")
async def cleanup_dry_run(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """预览资源清理结果（仅统计不删除，超管专属）。"""
    if not current_user.is_superuser:
        from app.core.exceptions import PermissionException, ErrorCode
        raise PermissionException(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            message="仅超管可预览资源清理",
        )
    from app.tasks.cleanup_tasks import run_full_cleanup
    results = await run_full_cleanup(dry_run=True)
    return success(data=results)


@router.get("/check-ocr-layout")
async def check_ocr_layout_model(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """检查 OCR 版面分析模型（PP-DocLayoutV3）是否可用。

    供知识库配置页面调用，当启用版面分析开关时校验模型可用性。
    返回模型状态与路径信息。
    """
    result = await _check_ocr_layout()
    return success(data=result)


@router.get("/check-nebula-graph")
async def check_nebula_graph(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """检查 NebulaGraph 图数据库可用性。

    供系统监控页面调用，返回连接状态、graphd 版本、space 数量等信息。
    服务不可用时返回 ``status=unavailable``，前端据此展示降级提示。
    """
    from app.services.graph.graph_store import graph_store

    # 5 秒超时保护，避免卡死
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_probe_nebula_detail, graph_store),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        return success(data={
            "status": "timeout",
            "host": settings.NEBULA_GRAPHD_HOST,
            "port": settings.NEBULA_GRAPHD_PORT,
            "message": "NebulaGraph 健康检查超时（5s）",
        })
    return success(data=result)


def _probe_nebula_detail(graph_store) -> dict:
    """同步探测 NebulaGraph 详细状态（在线程中执行）。"""
    if not graph_store._try_connect():
        return {
            "status": "unavailable",
            "host": settings.NEBULA_GRAPHD_HOST,
            "port": settings.NEBULA_GRAPHD_PORT,
            "message": "NebulaGraph 服务不可用，图谱功能将优雅降级",
        }

    info: dict = {
        "status": "healthy",
        "host": settings.NEBULA_GRAPHD_HOST,
        "port": settings.NEBULA_GRAPHD_PORT,
    }
    try:
        session = graph_store._get_session()
        try:
            # 获取 graphd 版本
            resp = session.execute("SHOW HOSTS;")
            if resp.is_succeeded():
                info["host_count"] = len(resp.rows())
            # 获取 space 数量
            resp = session.execute("SHOW SPACES;")
            if resp.is_succeeded():
                info["space_count"] = len(resp.rows())
                info["spaces"] = [
                    v.get_sVal().decode()
                    for row in resp.rows()
                    for v in row.values
                    if hasattr(v, "get_sVal")
                ][:20]
        finally:
            session.release()
    except Exception as exc:  # noqa: BLE001
        info["status"] = "degraded"
        info["error"] = str(exc)[:200]
    return info
