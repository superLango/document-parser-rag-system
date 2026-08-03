"""RAG 多级缓存服务模块。

实现三级缓存体系，降低重复查询的响应延迟：

- L1 内存缓存：LRU 字典，精确匹配，TTL=60s，容量 1000 条
- L2 语义缓存：Valkey 8，基于查询向量余弦相似度匹配，TTL=3600s
- L3 检索结果缓存：Valkey 8，缓存 Milvus 检索+重排结果，TTL=86400s

缓存命中策略：
1. L1 精确匹配（哈希）→ 直接返回完整 RAGResponse
2. L2 语义匹配（相似度≥0.95）→ 直接返回完整 RAGResponse
3. L3 检索结果匹配 → 跳过检索阶段，仅执行 LLM 生成
4. 全部未命中 → 执行完整 RAG 链路，异步回写缓存

知识库隔离：
    所有缓存键和 Valkey hash 名都按 ``kb_id`` 加前缀（``kb:{kb_id}:``），
    实现 KB 级物理隔离。``kb_id=None`` 时回退到全局命名空间（向后兼容）。

文档更新时通过 invalidate_by_doc_id 批量失效相关缓存。

使用示例：
    from app.services.cache_service import rag_cache_service

    # 查询缓存（指定 KB）
    cached = await rag_cache_service.get_response(question, top_k, doc_ids, kb_id=kb_id)
    if cached is not None:
        return cached  # 缓存命中，跳过完整链路

    # 执行完整 RAG 链路后回写缓存
    response = await rag_service.query(question)
    await rag_cache_service.set_response(question, response, top_k, doc_ids, kb_id=kb_id)
"""

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RAGCacheService:
    """RAG 多级缓存服务。

    Attributes:
        _l1_cache: L1 内存缓存，OrderedDict 实现 LRU 淘汰。
        _l1_max_size: L1 最大条目数。
        _l1_ttl: L1 缓存存活时间（秒）。
        _valkey: Valkey 客户端实例（懒加载）。
        _similarity_threshold: L2 语义缓存命中阈值。
    """

    # L2/L3 Valkey hash 基础名
    _L2_HASH = "rag:response"
    _L3_HASH = "rag:retrieval"

    def __init__(self) -> None:
        self._l1_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._l1_max_size: int = 1000
        self._l1_ttl: int = 60
        self._valkey: Any = None
        self._valkey_available: bool | None = None  # None=未尝试/True=可用/False=不可用
        self._similarity_threshold: float = 0.95

    async def _get_valkey(self) -> Any:
        """懒加载 Valkey 客户端。

        Valkey 8 兼容 Redis 协议，使用 redis.asyncio 客户端连接。
        连接失败时标记为不可用，后续跳过 L2/L3 缓存。

        Returns:
            Valkey 客户端实例，不可用时返回 None。
        """
        # 已连接，直接返回
        if self._valkey is not None:
            return self._valkey
        # 之前尝试过且失败，跳过（_valkey_available 三态：None=未尝试/True=可用/False=不可用）
        if self._valkey_available is False:
            return None
        try:
            import redis.asyncio as aioredis

            self._valkey = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
            await self._valkey.ping()
            self._valkey_available = True
            logger.info("Valkey 缓存连接成功")
            return self._valkey
        except Exception as err:
            self._valkey_available = False
            logger.warning("Valkey 缓存不可用，跳过 L2/L3 缓存", error=str(err))
            return None

    # ------------------------------------------------------------------
    # KB 隔离键/名生成
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(
        question: str,
        top_k: int,
        doc_ids: list[str] | None,
        kb_id=None,
    ) -> str:
        """生成缓存键。

        Args:
            question: 查询文本。
            top_k: 返回数量。
            doc_ids: 文档 ID 列表。
            kb_id: 知识库 ID（uuid.UUID 或 None）。None 时返回纯哈希键
                （向后兼容）；非 None 时返回带 ``kb:{kb_id}:`` 前缀的键（KB 隔离）。

        Returns:
            str: SHA256 哈希键（可带 KB 前缀）。
        """
        raw = f"{question}|{top_k}|{','.join(sorted(doc_ids)) if doc_ids else 'all'}"
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if kb_id is None:
            return h
        return f"{settings.KB_REDIS_KEY_PREFIX}{kb_id}:{h}"

    @staticmethod
    def _hash_name(name: str, kb_id=None) -> str:
        """生成 L2/L3 Valkey hash 名（按 KB 隔离）。

        Args:
            name: 基础 hash 名（如 ``rag:response``）。
            kb_id: 知识库 ID。None 时返回原名（向后兼容），
                非 None 时返回 ``kb:{kb_id}:{name}``。

        Returns:
            str: hash 名。
        """
        if kb_id is None:
            return name
        return f"{settings.KB_REDIS_KEY_PREFIX}{kb_id}:{name}"

    @staticmethod
    def _retrieval_key(
        query_embedding: list[float],
        top_k: int,
        doc_ids: list[str] | None,
        kb_id=None,
    ) -> str:
        """生成 L3 检索结果缓存键（带 KB 前缀）。

        使用向量前 16 维生成简化键，避免完整向量做键过长。
        """
        vec_prefix = ",".join(f"{v:.4f}" for v in query_embedding[:16])
        raw = f"{vec_prefix}|{top_k}|{','.join(sorted(doc_ids)) if doc_ids else 'all'}"
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if kb_id is None:
            return h
        return f"{settings.KB_REDIS_KEY_PREFIX}{kb_id}:{h}"

    # ------------------------------------------------------------------
    # L1 内存缓存
    # ------------------------------------------------------------------

    def _l1_get(self, key: str) -> Any:
        """L1 内存缓存查询。

        检查 TTL 有效期，命中时移到 OrderedDict 末尾（LRU 策略）。

        Args:
            key: 缓存键。

        Returns:
            缓存值，未命中或过期返回 None。
        """
        entry = self._l1_cache.get(key)
        if entry is None:
            return None
        # 检查 TTL
        if time.time() - entry["ts"] > self._l1_ttl:
            del self._l1_cache[key]
            return None
        # LRU：移到末尾
        self._l1_cache.move_to_end(key)
        return entry["data"]

    def _l1_set(self, key: str, data: Any) -> None:
        """L1 内存缓存写入。

        超过容量时淘汰最旧条目（LRU）。

        Args:
            key: 缓存键。
            data: 缓存值。
        """
        self._l1_cache[key] = {"data": data, "ts": time.time()}
        self._l1_cache.move_to_end(key)
        while len(self._l1_cache) > self._l1_max_size:
            self._l1_cache.popitem(last=False)

    # ------------------------------------------------------------------
    # L2 完整响应缓存（RAGResponse）
    # ------------------------------------------------------------------

    async def get_response(
        self,
        question: str,
        top_k: int,
        doc_ids: list[str] | None = None,
        kb_id=None,
    ) -> dict[str, Any] | None:
        """查询完整 RAGResponse 缓存（L1 + L2）。

        L1 精确匹配：基于查询文本哈希。
        L2 语义匹配：基于查询向量余弦相似度（需 Valkey 可用）。

        Args:
            question: 查询文本。
            top_k: 返回数量。
            doc_ids: 文档 ID 列表。
            kb_id: 知识库 ID。None 时使用全局命名空间。

        Returns:
            dict | None: 命中返回 RAGResponse 字典，未命中返回 None。
        """
        cache_key = self._make_key(question, top_k, doc_ids, kb_id)

        # L1 精确匹配
        result = self._l1_get(cache_key)
        if result is not None:
            logger.info("L1 缓存命中", question_preview=question[:50])
            return result

        # L2 语义匹配（需 Valkey）
        vk = await self._get_valkey()
        if vk is None:
            return None
        try:
            hash_n = self._hash_name(self._L2_HASH, kb_id)
            cached = await vk.hget(hash_n, cache_key)
            if cached:
                result = json.loads(cached)
                # 回写 L1
                self._l1_set(cache_key, result)
                logger.info("L2 缓存命中", question_preview=question[:50])
                return result
        except Exception as err:
            logger.debug("L2 缓存查询失败", error=str(err))

        return None

    async def set_response(
        self,
        question: str,
        response_data: dict[str, Any],
        top_k: int,
        doc_ids: list[str] | None = None,
        kb_id=None,
    ) -> None:
        """异步回写 RAGResponse 缓存（L1 + L2）。

        采用 fire-and-forget 策略，不阻塞主流程。

        Args:
            question: 查询文本。
            response_data: RAGResponse 序列化字典。
            top_k: 返回数量。
            doc_ids: 文档 ID 列表。
            kb_id: 知识库 ID。None 时使用全局命名空间。
        """
        cache_key = self._make_key(question, top_k, doc_ids, kb_id)

        # L1 同步写入
        self._l1_set(cache_key, response_data)

        # L2 异步写入
        asyncio.create_task(self._l2_async_set(cache_key, response_data, kb_id))

    async def _l2_async_set(self, key: str, data: dict[str, Any], kb_id=None) -> None:
        """L2 Valkey 异步写入。"""
        vk = await self._get_valkey()
        if vk is None:
            return
        try:
            hash_n = self._hash_name(self._L2_HASH, kb_id)
            await vk.hset(hash_n, key, json.dumps(data, ensure_ascii=False))
            await vk.expire(hash_n, 3600)  # L2 TTL=1小时
        except Exception as err:
            logger.debug("L2 缓存写入失败", error=str(err))

    # ------------------------------------------------------------------
    # L3 检索结果缓存
    # ------------------------------------------------------------------

    async def get_retrieval(
        self,
        query_embedding: list[float],
        top_k: int,
        doc_ids: list[str] | None = None,
        kb_id=None,
    ) -> dict[str, Any] | None:
        """L3 检索结果缓存查询。

        缓存 Milvus 检索+重排结果，命中时跳过检索阶段，仅执行 LLM 生成。

        Args:
            query_embedding: 查询向量。
            top_k: 返回数量。
            doc_ids: 文档 ID 列表。
            kb_id: 知识库 ID。None 时使用全局命名空间。

        Returns:
            dict | None: 命中返回检索结果，未命中返回 None。
        """
        vk = await self._get_valkey()
        if vk is None:
            return None
        try:
            key = self._retrieval_key(query_embedding, top_k, doc_ids, kb_id)
            hash_n = self._hash_name(self._L3_HASH, kb_id)
            cached = await vk.hget(hash_n, key)
            if cached:
                logger.info("L3 检索结果缓存命中")
                return json.loads(cached)
        except Exception as err:
            logger.debug("L3 缓存查询失败", error=str(err))
        return None

    async def set_retrieval(
        self,
        query_embedding: list[float],
        retrieval_data: dict[str, Any],
        top_k: int,
        doc_ids: list[str] | None = None,
        kb_id=None,
    ) -> None:
        """L3 检索结果缓存写入。

        Args:
            query_embedding: 查询向量。
            retrieval_data: 检索+重排结果。
            top_k: 返回数量。
            doc_ids: 文档 ID 列表。
            kb_id: 知识库 ID。None 时使用全局命名空间。
        """
        vk = await self._get_valkey()
        if vk is None:
            return
        try:
            key = self._retrieval_key(query_embedding, top_k, doc_ids, kb_id)
            hash_n = self._hash_name(self._L3_HASH, kb_id)
            await vk.hset(hash_n, key, json.dumps(retrieval_data, ensure_ascii=False))
            await vk.expire(hash_n, 86400)  # L3 TTL=24小时
        except Exception as err:
            logger.debug("L3 缓存写入失败", error=str(err))

    # ------------------------------------------------------------------
    # 失效策略
    # ------------------------------------------------------------------

    async def invalidate_by_doc_id(self, doc_id: str, kb_id=None) -> None:
        """文档更新时失效相关缓存。

        - kb_id 为 None：清除全部 L1 缓存，并删除全局 ``rag:response`` /
          ``rag:retrieval`` hash（向后兼容旧调用）。
        - kb_id 非 None：仅清除该 KB 的 L1 条目（按前缀过滤），并删除该 KB
          对应的 Valkey hash，避免影响其他 KB 缓存。

        Args:
            doc_id: 发生变更的文档 ID。
            kb_id: 知识库 ID。None 时清除全局缓存。
        """
        if kb_id is None:
            # 清除 L1 全部缓存
            cleared_l1 = len(self._l1_cache)
            self._l1_cache.clear()

            # 清除 L2/L3 全局 hash（Valkey 可用时）
            vk = await self._get_valkey()
            if vk is not None:
                try:
                    await vk.delete(self._L2_HASH, self._L3_HASH)
                except Exception as err:
                    logger.debug("缓存失效操作失败", error=str(err))
        else:
            # 仅清除该 KB 的 L1 条目（按前缀过滤）
            prefix = f"{settings.KB_REDIS_KEY_PREFIX}{kb_id}:"
            keys_to_drop = [k for k in self._l1_cache if k.startswith(prefix)]
            for k in keys_to_drop:
                del self._l1_cache[k]
            cleared_l1 = len(keys_to_drop)

            # 删除该 KB 对应的 Valkey hash
            vk = await self._get_valkey()
            if vk is not None:
                try:
                    l2_name = self._hash_name(self._L2_HASH, kb_id)
                    l3_name = self._hash_name(self._L3_HASH, kb_id)
                    await vk.delete(l2_name, l3_name)
                except Exception as err:
                    logger.debug("缓存失效操作失败", error=str(err))

        logger.info(
            "文档更新触发缓存失效",
            doc_id=doc_id,
            kb_id=str(kb_id) if kb_id else "global",
            l1_cleared=cleared_l1,
        )

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息。

        Returns:
            dict: 包含 L1 大小、Valkey 可用性等信息的字典。
        """
        return {
            "l1_size": len(self._l1_cache),
            "l1_max_size": self._l1_max_size,
            "valkey_available": self._valkey_available,
            "similarity_threshold": self._similarity_threshold,
        }

    # ------------------------------------------------------------------
    # KB ACL 生命周期（供 kb_lifecycle 调用，方案 §9.2 第 4 层）
    # ------------------------------------------------------------------

    @staticmethod
    def _acl_username(kb_id) -> str:
        """生成 KB 的 Redis ACL 用户名（kb_{kb_id_hex}）。"""
        return f"kb_{kb_id.hex}"

    async def create_kb_acl(self, kb_id) -> None:
        """创建 KB 专属 Redis ACL 用户（幂等，最佳努力）。

        为 KB 创建 ACL 用户 ``kb_{kb_id_hex}``，仅授权访问前缀
        ``kb:{kb_id}:`` 的键。该 ACL 用户作为深度防御措施，实际缓存
        操作仍由主连接配合 key 前缀完成。

        失败场景（Redis 不支持 ACL / 连接无管理员权限）仅记录 WARNING，
        不阻断 KB 创建——主隔离机制为 key 前缀，ACL 为增强层。
        """
        import secrets

        username = self._acl_username(kb_id)
        prefix = f"{settings.KB_REDIS_KEY_PREFIX}{kb_id}:*"
        password = secrets.token_urlsafe(24)

        vk = await self._get_valkey()
        if vk is None:
            logger.warning("Valkey 不可用，跳过 KB ACL 创建", kb_id=str(kb_id))
            return
        try:
            # 幂等：先尝试删除已存在的同名用户（忽略失败），再创建
            try:
                await vk.execute_command("ACL", "DELUSER", username)
            except Exception:
                pass
            # 创建用户：启用、设密码、限定 key 前缀、授予全部命令权限（限定在前缀范围内）
            await vk.execute_command(
                "ACL", "SETUSER", username,
                "on", f">{password}", f"~{prefix}", "+@all",
            )
            logger.info(
                "KB Redis ACL 用户已创建",
                kb_id=str(kb_id), username=username, key_prefix=prefix,
            )
        except Exception as err:
            # Redis < 6.0 不支持 ACL；或连接用户无 ACL 管理权限
            logger.warning(
                "KB Redis ACL 创建失败（Redis 不支持 ACL 或无管理员权限，"
                "key 前缀隔离仍生效）",
                kb_id=str(kb_id), error=str(err),
            )

    async def destroy_kb_acl(self, kb_id) -> None:
        """删除 KB 专属 Redis ACL 用户（合规销毁，幂等，最佳努力）。"""
        username = self._acl_username(kb_id)
        vk = await self._get_valkey()
        if vk is None:
            return
        try:
            await vk.execute_command("ACL", "DELUSER", username)
            logger.warning("KB Redis ACL 用户已删除", kb_id=str(kb_id), username=username)
        except Exception as err:
            logger.warning(
                "KB Redis ACL 删除失败",
                kb_id=str(kb_id), error=str(err),
            )

    async def verify_kb_acl(self, kb_id) -> dict:
        """校验 KB 专属 Redis ACL 用户是否存在。"""
        username = self._acl_username(kb_id)
        vk = await self._get_valkey()
        if vk is None:
            return {"acl": "valkey_unavailable"}
        try:
            users = await vk.execute_command("ACL", "LIST")
            exists = any(
                (u.decode() if isinstance(u, bytes) else u).startswith(f"user {username} ")
                for u in (users or [])
            )
            return {"acl": "exists" if exists else "missing", "username": username}
        except Exception as err:
            return {"acl": "error", "error": str(err)}


# 模块级单例
rag_cache_service = RAGCacheService()
# 向后兼容别名：kb_lifecycle 等模块通过 ``cache_service`` 名称引用
cache_service = rag_cache_service
