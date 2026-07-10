"""MinIO 对象存储服务封装模块。

本模块提供对 MinIO/S3 兼容存储的异步操作接口，包括：
- 文件上传（自动创建存储桶）
- 文件下载
- 文件删除
- 预签名下载 URL 生成

采用懒加载策略：Minio 客户端在首次实际使用时才创建连接，
避免模块导入阶段即建立网络连接。

使用示例：
    from app.services.storage_service import storage_service

    # 上传文件
    object_name = await storage_service.upload("doc/123.pdf", file_bytes, "application/pdf")

    # 下载文件
    data = await storage_service.download("doc/123.pdf")

    # 获取预签名下载链接
    url = await storage_service.get_presigned_url("doc/123.pdf", expires=1800)
"""

import asyncio
from datetime import timedelta
from io import BytesIO
from typing import Any

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageService:
    """MinIO 对象存储服务封装。

    封装 MinIO SDK 的同步操作为异步接口，通过懒加载机制
    延迟创建 Minio 客户端与初始化存储桶，确保模块导入时
    不产生网络副作用。

    Attributes:
        _client: Minio 客户端实例，懒加载，首次使用时创建。
        _bucket_ready: 标记目标存储桶是否已确认存在。
    """

    def __init__(self) -> None:
        """初始化存储服务，仅保存状态不建立连接。"""
        self._client: Minio | None = None
        self._bucket_ready: bool = False

    def _get_client(self) -> Minio:
        """懒加载获取 Minio 客户端实例。

        首次调用时根据配置创建 Minio 客户端，后续调用复用同一实例。
        Minio 构造函数本身不建立网络连接，实际的连接发生在具体操作时。

        Returns:
            Minio: 已配置完成的 Minio 客户端实例。
        """
        if self._client is None:
            logger.info("初始化 Minio 客户端", endpoint=settings.MINIO_ENDPOINT)
            self._client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
        return self._client

    async def _ensure_bucket(self) -> None:
        """确保目标存储桶存在，不存在则创建。

        通过 _bucket_ready 标记避免重复检查，仅在首次操作时执行一次。
        """
        if self._bucket_ready:
            return
        client = self._get_client()
        # bucket_exists / make_bucket 为同步阻塞调用，交由线程池执行
        exists = await asyncio.to_thread(client.bucket_exists, settings.MINIO_BUCKET)
        if not exists:
            logger.info("存储桶不存在，开始创建", bucket=settings.MINIO_BUCKET)
            await asyncio.to_thread(client.make_bucket, settings.MINIO_BUCKET)
        self._bucket_ready = True

    async def upload(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """上传文件内容到 MinIO 存储桶。

        自动确保存储桶存在，将字节数据以流式方式上传。
        所有 MinIO 同步操作均通过线程池执行，避免阻塞事件循环。

        Args:
            object_name: 对象在存储桶中的唯一标识（路径）。
            data: 待上传的字节数据。
            content_type: MIME 类型，默认为 "application/octet-stream"。

        Returns:
            str: 上传成功后的对象标识（与传入的 object_name 一致）。

        Raises:
            S3Error: MinIO 操作失败时抛出。
        """
        await self._ensure_bucket()
        client = self._get_client()
        logger.info(
            "开始上传对象",
            object_name=object_name,
            content_type=content_type,
            size=len(data),
        )
        # 使用 BytesIO 将字节数据包装为流，length 必须显式指定
        stream = BytesIO(data)
        await asyncio.to_thread(
            client.put_object,
            settings.MINIO_BUCKET,
            object_name,
            stream,
            length=len(data),
            content_type=content_type,
        )
        logger.info("对象上传完成", object_name=object_name)
        return object_name

    async def download(self, object_name: str) -> bytes:
        """从 MinIO 下载对象内容。

        将对象完整读取为字节数据返回。

        Args:
            object_name: 对象在存储桶中的唯一标识。

        Returns:
            bytes: 对象的完整字节内容。

        Raises:
            S3Error: 对象不存在或下载失败时抛出。
        """
        client = self._get_client()
        logger.info("开始下载对象", object_name=object_name)
        response: Any = await asyncio.to_thread(
            client.get_object, settings.MINIO_BUCKET, object_name
        )
        try:
            content: bytes = response.read()
            logger.info("对象下载完成", object_name=object_name, size=len(content))
            return content
        finally:
            # 释放底层连接，避免连接泄漏
            response.close()
            response.release_conn()

    async def delete(self, object_name: str) -> bool:
        """从 MinIO 删除指定对象。

        Args:
            object_name: 对象在存储桶中的唯一标识。

        Returns:
            bool: 删除成功返回 True，对象不存在也返回 True（幂等）。
        """
        client = self._get_client()
        logger.info("开始删除对象", object_name=object_name)
        try:
            await asyncio.to_thread(
                client.remove_object, settings.MINIO_BUCKET, object_name
            )
            logger.info("对象删除完成", object_name=object_name)
            return True
        except S3Error as err:
            # 对象不存在视为删除成功，保持幂等语义
            if err.code == "NoSuchKey":
                logger.info("对象不存在，视为删除成功", object_name=object_name)
                return True
            logger.error("删除对象失败", object_name=object_name, error=str(err))
            raise

    async def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        """生成对象的预签名下载 URL。

        持有该 URL 的客户端可在有效期内直接下载对象，无需 MinIO 凭证。

        Args:
            object_name: 对象在存储桶中的唯一标识。
            expires: URL 有效期（秒），默认 3600 秒（1 小时）。

        Returns:
            str: 预签名下载 URL。

        Raises:
            S3Error: URL 生成失败时抛出。
        """
        client = self._get_client()
        logger.info("生成预签名下载 URL", object_name=object_name, expires=expires)
        url: str = await asyncio.to_thread(
            client.presigned_get_object,
            settings.MINIO_BUCKET,
            object_name,
            expires=timedelta(seconds=expires),
        )
        logger.info("预签名 URL 生成完成", object_name=object_name)
        return url


# 模块级单例，懒加载，导入时不建立连接
storage_service = StorageService()
