"""S3兼容存储(SeaweedFS)对象存储服务封装模块。

本模块提供对 S3兼容存储(SeaweedFS)的异步操作接口，包括：
- 文件上传（自动创建存储桶）
- 文件下载
- 文件删除
- 预签名下载 URL 生成

采用懒加载策略：boto3 客户端在首次实际使用时才创建连接，
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

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageService:
    """S3兼容存储(SeaweedFS)对象存储服务封装。

    封装 boto3 SDK 的同步操作为异步接口，通过懒加载机制
    延迟创建 boto3 客户端与初始化存储桶，确保模块导入时
    不产生网络副作用。

    Attributes:
        _client: boto3 S3 客户端实例，懒加载，首次使用时创建。
        _bucket_ready: 标记目标存储桶是否已确认存在。
    """

    def __init__(self) -> None:
        """初始化存储服务，仅保存状态不建立连接。"""
        self._client: BaseClient | None = None
        self._bucket_ready: bool = False

    def _get_client(self) -> BaseClient:
        """懒加载获取 boto3 S3 客户端实例。

        首次调用时根据配置创建 boto3 客户端，后续调用复用同一实例。
        boto3 client 构造函数本身不建立网络连接，实际的连接发生在具体操作时。

        Returns:
            BaseClient: 已配置完成的 boto3 S3 客户端实例。
        """
        if self._client is None:
            logger.info("初始化 boto3 S3 客户端", endpoint=settings.S3_ENDPOINT_URL)
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT_URL,
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
                config=Config(signature_version="s3v4"),
            )
        return self._client

    async def _ensure_bucket(self) -> None:
        """确保目标存储桶存在，不存在则创建。

        通过 _bucket_ready 标记避免重复检查，仅在首次操作时执行一次。
        """
        if self._bucket_ready:
            return
        client = self._get_client()
        # head_bucket 为同步阻塞调用，交由线程池执行
        try:
            await asyncio.to_thread(
                client.head_bucket, Bucket=settings.MINIO_BUCKET
            )
        except ClientError as err:
            # 404 / NoSuchBucket 表示桶不存在，需创建
            error_code = err.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchBucket", "NotFound"):
                logger.info(
                    "存储桶不存在，开始创建", bucket=settings.MINIO_BUCKET
                )
                await asyncio.to_thread(
                    client.create_bucket, Bucket=settings.MINIO_BUCKET
                )
            else:
                logger.error(
                    "检查存储桶失败",
                    bucket=settings.MINIO_BUCKET,
                    error=str(err),
                )
                raise
        self._bucket_ready = True

    async def upload(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """上传文件内容到 S3兼容存储(SeaweedFS)存储桶。

        自动确保存储桶存在，将字节数据上传。
        所有 boto3 同步操作均通过线程池执行，避免阻塞事件循环。

        Args:
            object_name: 对象在存储桶中的唯一标识（路径）。
            data: 待上传的字节数据。
            content_type: MIME 类型，默认为 "application/octet-stream"。

        Returns:
            str: 上传成功后的对象标识（与传入的 object_name 一致）。

        Raises:
            ClientError: boto3 操作失败时抛出。
        """
        await self._ensure_bucket()
        client = self._get_client()
        logger.info(
            "开始上传对象",
            object_name=object_name,
            content_type=content_type,
            size=len(data),
        )
        await asyncio.to_thread(
            client.put_object,
            Bucket=settings.MINIO_BUCKET,
            Key=object_name,
            Body=data,
            ContentType=content_type,
        )
        logger.info("对象上传完成", object_name=object_name)
        return object_name

    async def download(self, object_name: str) -> bytes:
        """从 S3兼容存储(SeaweedFS)下载对象内容。

        将对象完整读取为字节数据返回。

        Args:
            object_name: 对象在存储桶中的唯一标识。

        Returns:
            bytes: 对象的完整字节内容。

        Raises:
            ClientError: 对象不存在或下载失败时抛出。
        """
        client = self._get_client()
        logger.info("开始下载对象", object_name=object_name)
        response = await asyncio.to_thread(
            client.get_object, Bucket=settings.MINIO_BUCKET, Key=object_name
        )
        try:
            content: bytes = response["Body"].read()
            logger.info("对象下载完成", object_name=object_name, size=len(content))
            return content
        finally:
            # 释放底层连接，避免连接泄漏
            response["Body"].close()

    async def delete(self, object_name: str) -> bool:
        """从 S3兼容存储(SeaweedFS)删除指定对象。

        Args:
            object_name: 对象在存储桶中的唯一标识。

        Returns:
            bool: 删除成功返回 True，对象不存在也返回 True（幂等）。
        """
        client = self._get_client()
        logger.info("开始删除对象", object_name=object_name)
        try:
            await asyncio.to_thread(
                client.delete_object,
                Bucket=settings.MINIO_BUCKET,
                Key=object_name,
            )
            logger.info("对象删除完成", object_name=object_name)
            return True
        except ClientError as err:
            error_code = err.response.get("Error", {}).get("Code", "")
            # 对象不存在视为删除成功，保持幂等语义
            if error_code in ("NoSuchKey", "404", "NotFound"):
                logger.info("对象不存在，视为删除成功", object_name=object_name)
                return True
            logger.error("删除对象失败", object_name=object_name, error=str(err))
            raise

    async def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        """生成对象的预签名下载 URL。

        持有该 URL 的客户端可在有效期内直接下载对象，无需 S3 凭证。

        Args:
            object_name: 对象在存储桶中的唯一标识。
            expires: URL 有效期（秒），默认 3600 秒（1 小时）。

        Returns:
            str: 预签名下载 URL。

        Raises:
            ClientError: URL 生成失败时抛出。
        """
        client = self._get_client()
        logger.info("生成预签名下载 URL", object_name=object_name, expires=expires)
        url: str = await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params={"Bucket": settings.MINIO_BUCKET, "Key": object_name},
            ExpiresIn=expires,
        )
        logger.info("预签名 URL 生成完成", object_name=object_name)
        return url


# 模块级单例，懒加载，导入时不建立连接
storage_service = StorageService()
