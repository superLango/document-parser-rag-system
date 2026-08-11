"""对象存储抽象（Phase 1）：本地磁盘 / MinIO 驱动。"""

import io
import uuid
from pathlib import Path
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageDriver(Protocol):
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...

    def presigned_url(self, key: str, expires: int = 3600) -> str | None: ...


class LocalDiskDriver:
    """开发/测试用本地磁盘驱动（键为相对路径，禁止越界）。"""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.LOCAL_STORAGE_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if not str(target).startswith(str(self.root)):
            raise ValueError("非法存储路径")
        return target

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def delete(self, key: str) -> None:
        target = self._resolve(key)
        if target.exists():
            target.unlink()

    def delete_prefix(self, prefix: str) -> None:
        base = self._resolve(prefix)
        if base.exists():
            import shutil

            shutil.rmtree(base)

    def presigned_url(self, key: str, expires: int = 3600) -> str | None:
        return None


class MinioDriver:
    """MinIO 驱动（D4）。桶按 KB 命名：kb-{kb_id_hex}。"""

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
    ) -> None:
        from minio import Minio

        self.client = Minio(
            endpoint or settings.MINIO_ENDPOINT,
            access_key=access_key or settings.MINIO_ACCESS_KEY,
            secret_key=secret_key or settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE if secure is None else secure,
        )

    def _bucket(self, kb_id: uuid.UUID | str) -> str:
        hex_id = kb_id.hex if isinstance(kb_id, uuid.UUID) else str(kb_id).replace("-", "")
        return f"kb-{hex_id}"

    def _ensure_bucket(self, bucket: str) -> None:
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        parts = key.split("/", 1)
        bucket, object_name = parts[0], parts[1] if len(parts) > 1 else key
        self._ensure_bucket(bucket)
        self.client.put_object(
            bucket,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )

    def get(self, key: str) -> bytes:
        bucket, object_name = key.split("/", 1)
        response = self.client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete(self, key: str) -> None:
        bucket, object_name = key.split("/", 1)
        self.client.remove_object(bucket, object_name)

    def delete_prefix(self, prefix: str) -> None:
        bucket, object_prefix = prefix.split("/", 1)
        for obj in self.client.list_objects(bucket, prefix=object_prefix, recursive=True):
            self.client.remove_object(bucket, obj.object_name)

    def presigned_url(self, key: str, expires: int = 3600) -> str | None:
        bucket, object_name = key.split("/", 1)
        return self.client.presigned_get_object(bucket, object_name, expires=expires)


_driver: StorageDriver | None = None


def get_storage_driver() -> StorageDriver:
    global _driver
    if _driver is None:
        if settings.STORAGE_DRIVER == "local":
            _driver = LocalDiskDriver()
        else:
            _driver = MinioDriver()
        logger.info("存储驱动已初始化", driver=settings.STORAGE_DRIVER)
    return _driver


def document_object_key(kb_id: uuid.UUID, task_id: str, filename: str) -> str:
    """Phase 1 对象键：{bucket}/originals/{task_id}/{filename}。"""
    safe_name = Path(filename).name
    return f"kb-{kb_id.hex}/originals/{task_id}/{safe_name}"


def put_object(key: str, data: bytes, content_type: str | None = None) -> None:
    """写入对象（Phase 2：解析产物落库）。"""
    get_storage_driver().put(key, data, content_type=content_type)


def delete_prefix(key: str) -> None:
    """删除对象前缀（Phase 4：U14 中间产物清理）。"""
    get_storage_driver().delete_prefix(key)


def get_object(key: str) -> bytes:
    """读取对象（Phase 2：解析管线读取原始 PDF/产物）。"""
    return get_storage_driver().get(key)


async def put_original(
    kb_id: uuid.UUID, task_id: str, filename: str, data: bytes
) -> str:
    driver = get_storage_driver()
    key = document_object_key(kb_id, task_id, filename)
    driver.put(key, data, content_type="application/pdf")
    return key


async def delete_document_objects(kb_id: uuid.UUID, object_key: str) -> None:
    """删除原始 PDF 及该任务的全部解析产物（result.md/layout.json/pages）。"""
    driver = get_storage_driver()
    parts = object_key.split("/")
    ocr_prefix = None
    if len(parts) >= 4 and parts[1] == "originals":
        ocr_prefix = f"{parts[0]}/ocr/{parts[2]}/"
    targets = [object_key]
    if ocr_prefix:
        targets.append(ocr_prefix)
    for key in targets:
        try:
            if key.endswith("/"):
                driver.delete_prefix(key)
            else:
                driver.delete(key)
        except Exception as exc:  # noqa: BLE001 - 单个对象删除失败不中断
            logger.warning(
                "删除对象失败", object_key=key, error=str(exc)[:200]
            )
