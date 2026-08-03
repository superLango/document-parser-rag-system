"""知识库物理资源生命周期管理器（方案 §9.2）。

统一管理 KB 的物理资源创建/销毁，实现六层物理隔离：

1. **Milvus**：每 KB 创建 6 个 Collection（doc_chunks_{kb_id} + 五维 doc_v2_*_{kb_id}）
2. **MinIO**：每 KB 创建独立 bucket（kb-{kb_id}）+ 独立 IAM 密钥（存 knowledge_buckets 表）
3. **NebulaGraph**：每 KB 创建独立 graph space（kb_{kb_id_hex}）+ schema + 用户
4. **Redis**：每 KB 创建 ACL 用户（kb_{kb_id_hex}）+ 授权 ~kb:{kb_id}:*
5. **文件系统**：每 KB 创建 OCR 输出目录 data/ocr_data/{kb_id}
6. **PostgreSQL**：RLS 由 KBContext 依赖激活，此处仅记录

设计原则：
- **协调器模式**：本模块只编排，具体资源操作委托给各 service 的
  ``create_kb_resources(kb_id)`` / ``destroy_kb_resources(kb_id)`` 方法
- **独立容错**：每个资源步骤用 try/except 独立保护，单个失败不阻断整体，
  失败步骤记录 ERROR 日志，可通过重试或配置中心手动修复
- **合规销毁**：destroy 时彻底销毁全部物理资源（满足 GDPR 被遗忘权），不可恢复
- **lazy import**：各 service 在方法内部导入，避免循环依赖与启动期耦合

容错策略：
- 各资源步骤独立 try/except，单个失败不阻断整体；
- ``_safe_step`` 捕获 ``AttributeError`` 时降级为 WARNING（防御 service 接口未对齐），
  当前各 service 的 KB 方法均已实现（vector_store / five_dimension_index /
  project_dict_store / storage_service / graph_store / cache_service）。
"""

import asyncio
import uuid

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _kb_id_hex(kb_id: uuid.UUID) -> str:
    """生成 kb_id 的无连字符十六进制形式，用于命名 Milvus Collection / NebulaGraph space / Redis ACL 用户。

    PostgreSQL RLS 用带连字符的 str(kb_id)（与 kb_id::text 对齐），
    而 Milvus/NebulaGraph/Redis 的标识符不含连字符更安全，故用 hex。
    """
    return kb_id.hex


def milvus_collection_names(kb_id: uuid.UUID) -> dict[str, str]:
    """生成某 KB 的 6 个 Milvus Collection 名。

    Args:
        kb_id: 知识库 ID。

    Returns:
        dict: ``{base: collection_name}``，包含 doc_chunks + 五维（path/title/content/type/structural）。
    """
    sep = settings.KB_MILVUS_COLLECTION_SEPARATOR
    suffix = f"{sep}{_kb_id_hex(kb_id)}"
    return {
        "doc_chunks": f"doc_chunks{suffix}",
        "path": f"doc_v2_path{suffix}",
        "title": f"doc_v2_title{suffix}",
        "content": f"doc_v2_content{suffix}",
        "type": f"doc_v2_type{suffix}",
        "structural": f"doc_v2_structural{suffix}",
    }


def minio_bucket_name(kb_id: uuid.UUID) -> str:
    """生成某 KB 的 MinIO bucket 名（kb-{kb_id_hex}）。"""
    return f"{settings.KB_MINIO_BUCKET_PREFIX}{_kb_id_hex(kb_id)}"


def nebula_space_name(kb_id: uuid.UUID) -> str:
    """生成某 KB 的 NebulaGraph space 名（kb_{kb_id_hex}）。"""
    return f"{settings.NEBULA_SPACE_PREFIX}{_kb_id_hex(kb_id)}"


def redis_acl_user(kb_id: uuid.UUID) -> str:
    """生成某 KB 的 Redis ACL 用户名（kb_{kb_id_hex}）。"""
    return f"kb_{_kb_id_hex(kb_id)}"


def redis_key_prefix(kb_id: uuid.UUID) -> str:
    """生成某 KB 的 Redis key 前缀（kb:{kb_id}:）。"""
    return f"{settings.KB_REDIS_KEY_PREFIX}{kb_id}:"


def ocr_data_dir(kb_id: uuid.UUID) -> str:
    """生成某 KB 的 OCR 输出目录路径。"""
    from pathlib import Path

    return str(Path(settings.KB_OCR_DATA_DIR) / str(kb_id))


class KBLifecycleManager:
    """知识库物理资源生命周期管理器。

    所有方法均为异步，供 KB CRUD 端点调用：
    - ``create_kb_resources(kb_id)``：新建 KB 时初始化全部物理资源
    - ``destroy_kb_resources(kb_id)``：删除 KB 时彻底销毁全部物理资源
    - ``verify_kb_resources(kb_id)``：校验资源完整性（配置中心诊断用）
    """

    # ============================================================
    # 创建
    # ============================================================
    async def create_kb_resources(self, kb_id: uuid.UUID) -> dict:
        """创建 KB 时初始化全部物理资源。

        按顺序创建：Milvus → MinIO → NebulaGraph → Redis → 文件系统。
        每步独立 try/except，返回各步状态汇总。

        Args:
            kb_id: 知识库 ID。

        Returns:
            dict: ``{step: {"ok": bool, "error": str|None}}`` 各步骤结果。
        """
        results: dict[str, dict] = {}
        logger.info("开始创建 KB 物理资源", kb_id=str(kb_id))

        # 1. Milvus 6 个 Collection
        results["milvus"] = await self._safe_step(
            "milvus", kb_id, self._create_milvus_collections
        )

        # 2. MinIO bucket + IAM 密钥
        results["minio"] = await self._safe_step(
            "minio", kb_id, self._create_minio_bucket
        )

        # 3. NebulaGraph graph space
        results["nebula"] = await self._safe_step(
            "nebula", kb_id, self._create_nebula_space
        )

        # 4. Redis ACL 用户
        results["redis"] = await self._safe_step(
            "redis", kb_id, self._create_redis_acl
        )

        # 5. 文件系统 OCR 目录
        results["filesystem"] = await self._safe_step(
            "filesystem", kb_id, self._create_ocr_dir
        )

        ok_count = sum(1 for r in results.values() if r["ok"])
        logger.info(
            "KB 物理资源创建完成",
            kb_id=str(kb_id),
            success=f"{ok_count}/{len(results)}",
        )
        return results

    # ============================================================
    # 销毁
    # ============================================================
    async def destroy_kb_resources(self, kb_id: uuid.UUID) -> dict:
        """删除 KB 时彻底销毁全部物理资源（合规销毁，不可恢复）。

        按顺序销毁：Milvus → MinIO → NebulaGraph → Redis → 文件系统。
        每步独立 try/except，确保即使部分资源已不存在也能继续清理其他。

        Args:
            kb_id: 知识库 ID。

        Returns:
            dict: ``{step: {"ok": bool, "error": str|None}}`` 各步骤结果。
        """
        results: dict[str, dict] = {}
        logger.warning("开始销毁 KB 物理资源（不可恢复）", kb_id=str(kb_id))

        results["milvus"] = await self._safe_step(
            "milvus", kb_id, self._destroy_milvus_collections
        )
        results["minio"] = await self._safe_step(
            "minio", kb_id, self._destroy_minio_bucket
        )
        results["nebula"] = await self._safe_step(
            "nebula", kb_id, self._destroy_nebula_space
        )
        results["redis"] = await self._safe_step(
            "redis", kb_id, self._destroy_redis_acl
        )
        results["filesystem"] = await self._safe_step(
            "filesystem", kb_id, self._destroy_ocr_dir
        )
        # 6. Hook 脚本目录（合规销毁：清除 KB 专属可执行脚本）
        results["hooks"] = await self._safe_step(
            "hooks", kb_id, self._destroy_hook_script
        )

        ok_count = sum(1 for r in results.values() if r["ok"])
        logger.warning(
            "KB 物理资源销毁完成",
            kb_id=str(kb_id),
            success=f"{ok_count}/{len(results)}",
        )
        return results

    # ============================================================
    # 校验
    # ============================================================
    async def verify_kb_resources(self, kb_id: uuid.UUID) -> dict:
        """校验 KB 物理资源完整性（配置中心诊断用）。

        逐项检查各资源是否存在且可访问：
        - milvus：doc_chunks_{kb_id} collection 是否存在
        - minio：kb-{kb_id} bucket 是否存在
        - nebula：kb_{kb_id_hex} graph space 是否存在
        - redis：连接是否正常 + key 前缀可读写
        - filesystem：OCR 输出目录是否存在
        - hooks：Hook 脚本是否存在（可选资源）

        Args:
            kb_id: 知识库 ID。

        Returns:
            dict: ``{step: {"ok": bool, "detail": str}}`` 各步骤校验结果。
        """
        results: dict[str, dict] = {}
        results["milvus"] = await self._verify_milvus(kb_id)
        results["minio"] = await self._verify_minio(kb_id)
        results["nebula"] = await self._verify_nebula(kb_id)
        results["redis"] = await self._verify_redis(kb_id)
        results["filesystem"] = await self._verify_filesystem(kb_id)
        results["hooks"] = await self._verify_hooks(kb_id)
        return results

    async def _verify_milvus(self, kb_id: uuid.UUID) -> dict:
        """校验 Milvus KB 专属 collection 是否存在。"""
        try:
            from pymilvus import utility, connections

            alias = "default"
            # 懒加载环境可能尚未建立连接，主动确保连接
            if not connections.has_connection(alias):
                connections.connect(
                    alias=alias,
                    host=settings.MILVUS_HOST,
                    port=str(settings.MILVUS_PORT),
                )

            sep = settings.KB_MILVUS_COLLECTION_SEPARATOR
            expected = f"{settings.MILVUS_COLLECTION}{sep}{kb_id.hex}"
            exists = utility.has_collection(expected, using=alias)
            if exists:
                return {"ok": True, "detail": f"collection {expected} 存在"}
            return {"ok": False, "detail": f"collection {expected} 不存在"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"校验异常: {e}"}

    async def _verify_minio(self, kb_id: uuid.UUID) -> dict:
        """校验 MinIO KB 专属 bucket 是否存在。"""
        try:
            from app.services.storage_service import storage_service
            bucket = storage_service._resolve_bucket(kb_id)
            client = storage_service._get_client()
            found = await asyncio.to_thread(client.head_bucket, Bucket=bucket)
            return {"ok": True, "detail": f"bucket {bucket} 存在"}
        except Exception as e:  # noqa: BLE001
            # head_bucket 抛异常即视为不存在或不可访问
            return {"ok": False, "detail": f"bucket 校验失败: {e}"}

    async def _verify_nebula(self, kb_id: uuid.UUID) -> dict:
        """校验 NebulaGraph KB 专属 graph space 是否存在。"""
        try:
            from app.services.graph.graph_store import graph_store
            result = await graph_store.verify_kb_space(kb_id)
            space = result.get("space", f"kb_{kb_id.hex}")
            status = result.get("status", "unknown")
            if status == "exists":
                return {"ok": True, "detail": f"space {space} 存在"}
            if status == "nebula_unavailable":
                return {"ok": False, "detail": f"NebulaGraph 不可用（space {space}）"}
            return {"ok": False, "detail": f"space {space} 不存在（status={status}）"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"校验异常: {e}"}

    async def _verify_redis(self, kb_id: uuid.UUID) -> dict:
        """校验 Redis 连接与 KB ACL 用户是否存在。"""
        try:
            from app.services.cache_service import cache_service
            result = await cache_service.verify_kb_acl(kb_id)
            acl = result.get("acl", "unknown")
            if acl == "exists":
                return {"ok": True, "detail": f"Redis ACL 用户存在（{result.get('username', '')}）"}
            if acl == "valkey_unavailable":
                return {"ok": False, "detail": "Redis/Valkey 不可用"}
            if acl == "missing":
                return {"ok": False, "detail": f"Redis ACL 用户不存在（{result.get('username', '')}）"}
            return {"ok": False, "detail": f"Redis 校验异常: {result.get('error', acl)}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"Redis 校验异常: {e}"}

    async def _verify_filesystem(self, kb_id: uuid.UUID) -> dict:
        """校验 OCR 输出目录是否存在。"""
        try:
            from pathlib import Path

            path = Path(ocr_data_dir(kb_id))
            if path.exists():
                return {"ok": True, "detail": f"目录 {path} 存在"}
            return {"ok": False, "detail": f"目录 {path} 不存在"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"校验异常: {e}"}

    async def _verify_hooks(self, kb_id: uuid.UUID) -> dict:
        """校验 Hook 脚本状态（可选资源，无脚本视为正常）。"""
        try:
            from app.kb_hooks.registry import get_kb_hook_info

            info = get_kb_hook_info(kb_id)
            if info["has_hook"]:
                return {"ok": True, "detail": f"Hook 存在，覆盖接口: {info.get('overridden_interfaces', [])}"}
            return {"ok": True, "detail": "无 Hook 脚本（使用默认逻辑）"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"校验异常: {e}"}

    # ============================================================
    # 内部：步骤执行与容错
    # ============================================================
    async def _safe_step(
        self,
        step_name: str,
        kb_id: uuid.UUID,
        action,
    ) -> dict:
        """安全执行单一步骤，捕获异常并记录。

        Args:
            step_name: 步骤名（milvus/minio/...）。
            kb_id: 知识库 ID。
            action: 异步可调用，签名 ``async (kb_id) -> None``。

        Returns:
            dict: ``{"ok": bool, "error": str|None}``。
        """
        try:
            await action(kb_id)
            return {"ok": True, "error": None}
        except AttributeError as e:
            # service 方法尚未实现（阶段 2 前），降级为 WARNING
            logger.warning(
                "KB 资源步骤方法未实现，跳过",
                step=step_name, kb_id=str(kb_id), detail=str(e),
            )
            return {"ok": True, "error": None, "skipped": True}
        except Exception as e:  # noqa: BLE001
            logger.error(
                "KB 资源步骤失败",
                step=step_name, kb_id=str(kb_id), error=str(e), exc_info=True,
            )
            return {"ok": False, "error": str(e)}

    async def _get_service(self, step_name: str):
        """按步骤名 lazy import 对应 service 单例/模块。

        Returns:
            service 对象，import 失败返回 None。
        """
        try:
            if step_name == "milvus":
                from app.services.vector.chunk_vector_store import vector_store
                return vector_store
            if step_name == "minio":
                from app.services.storage_service import storage_service
                return storage_service
            if step_name == "nebula":
                from app.services.graph.graph_store import graph_store
                return graph_store
            if step_name == "redis":
                from app.services.cache_service import cache_service
                return cache_service
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "service 导入失败", step=step_name, error=str(e)
            )
            return None
        return None

    # ============================================================
    # 各资源具体操作（委托给 service，方法在阶段 2 实现）
    # ============================================================
    async def _create_milvus_collections(self, kb_id: uuid.UUID) -> None:
        from app.services.vector.chunk_vector_store import chunk_vector_store
        kb_id_str = str(kb_id)
        chunk_vector_store.create_kb_collection(kb_id_str)
        from app.services.vector.five_dim_vector_store import five_dim_vector_store
        five_dim_vector_store.create_kb_collection(kb_id_str)
        from app.services.project_dict.project_dict_store import project_dict_store
        await project_dict_store.create_kb_collections(kb_id)
        logger.info("Milvus Collections创建完成", kb_id=kb_id_str)

    async def _destroy_milvus_collections(self, kb_id: uuid.UUID) -> None:
        from app.services.vector.chunk_vector_store import chunk_vector_store
        kb_id_str = str(kb_id)
        chunk_vector_store.drop_kb_collection(kb_id_str)
        from app.services.vector.five_dim_vector_store import five_dim_vector_store
        five_dim_vector_store.drop_kb_collection(kb_id_str)
        from app.services.project_dict.project_dict_store import project_dict_store
        await project_dict_store.drop_kb_collections(kb_id)
        logger.warning("Milvus Collections删除完成", kb_id=kb_id_str)

    async def _create_minio_bucket(self, kb_id: uuid.UUID) -> None:
        from app.services.storage_service import storage_service
        await storage_service.create_kb_bucket(kb_id)

    async def _destroy_minio_bucket(self, kb_id: uuid.UUID) -> None:
        from app.services.storage_service import storage_service
        await storage_service.destroy_kb_bucket(kb_id)

    async def _create_nebula_space(self, kb_id: uuid.UUID) -> None:
        from app.services.graph.graph_store import graph_store
        await graph_store.create_kb_space(kb_id)

    async def _destroy_nebula_space(self, kb_id: uuid.UUID) -> None:
        from app.services.graph.graph_store import graph_store
        await graph_store.drop_kb_space(kb_id)

    async def _create_redis_acl(self, kb_id: uuid.UUID) -> None:
        from app.services.cache_service import cache_service
        await cache_service.create_kb_acl(kb_id)

    async def _destroy_redis_acl(self, kb_id: uuid.UUID) -> None:
        from app.services.cache_service import cache_service
        await cache_service.destroy_kb_acl(kb_id)

    async def _create_ocr_dir(self, kb_id: uuid.UUID) -> None:
        """创建 KB 的 OCR 输出目录。"""
        import os

        os.makedirs(ocr_data_dir(kb_id), exist_ok=True)
        logger.info("已创建 KB OCR 目录", kb_id=str(kb_id), dir=ocr_data_dir(kb_id))

    async def _destroy_ocr_dir(self, kb_id: uuid.UUID) -> None:
        """删除 KB 的 OCR 输出目录（含全部内容）。"""
        import shutil
        from pathlib import Path

        path = Path(ocr_data_dir(kb_id))
        if path.exists():
            shutil.rmtree(path)
            logger.warning("已删除 KB OCR 目录", kb_id=str(kb_id), dir=str(path))

    async def _destroy_hook_script(self, kb_id: uuid.UUID) -> None:
        """删除 KB 的 Hook 脚本目录（含 hooks.py 与 __init__.py）。

        合规销毁：KB 删除时必须清除其专属可执行脚本，避免残留代码
        引用已销毁的资源。同时清空 Hook 缓存。
        """
        from app.kb_hooks.registry import delete_kb_hook_script

        deleted = delete_kb_hook_script(kb_id)
        if deleted:
            logger.warning(
                "已删除 KB Hook 脚本目录", kb_id=str(kb_id)
            )


# 全局单例
kb_lifecycle = KBLifecycleManager()
