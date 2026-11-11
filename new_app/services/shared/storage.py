import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


class ObjectStore(Protocol):
    async def ensure_ready(self) -> None: ...

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str: ...

    async def get_bytes(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


@dataclass(frozen=True)
class StorageConfig:
    endpoint: str
    bucket: str
    access_key: str
    secret_key: str
    local_dir: Path = Path("/tmp/hanson-new-app")


class S3ObjectStore:
    def __init__(self, config: StorageConfig) -> None:
        self.bucket = config.bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}),
        )

    async def ensure_ready(self) -> None:
        def _ensure() -> None:
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except ClientError:
                self.client.create_bucket(Bucket=self.bucket)

        await asyncio.to_thread(_ensure)

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    async def get_bytes(self, key: str) -> bytes:
        def _get() -> bytes:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)


class LocalObjectStore:
    def __init__(self, config: StorageConfig) -> None:
        self.root = config.local_dir

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        root = self.root.resolve()
        if not str(path).startswith(str(root)):
            raise ValueError(f"invalid storage key: {key}")
        return path

    async def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()


def build_store(config: StorageConfig) -> ObjectStore:
    endpoint = config.endpoint.strip()
    if endpoint.startswith("http"):
        return S3ObjectStore(config)
    return LocalObjectStore(config)
