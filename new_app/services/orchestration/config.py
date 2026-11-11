from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from services.shared.storage import StorageConfig


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://hanson:hanson@localhost:15432/hanson"
    object_storage_endpoint: str = "http://localhost:19000"
    object_storage_bucket: str = "hanson-docs"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: str = "minioadmin"
    local_storage_dir: Path = Path("/tmp/hanson-new-app")
    mock_stage_delay_seconds: float = 0.2
    stage_max_attempts: int = 2
    stage_retry_backoff_seconds: float = 0.5
    # 开发期故障注入，仅用于验证阶段重试；接入真实实现后移除。
    mock_fail_stage: str = ""
    mock_fail_times: int = 0
    ocr_url: str = "http://localhost:18002"
    ocr_backend: str = "auto"
    ocr_timeout_seconds: float = 300.0
    # 回滚开关：置 true 时 OCR 阶段回到 M1 的 fake 实现。
    ocr_use_fake: bool = False
    recipe_registry_url: str = "http://localhost:18005"
    # 回滚开关：置 true 时路由阶段回到 M1 的 fake 实现。
    route_use_fake: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    def storage_config(self) -> StorageConfig:
        return StorageConfig(
            endpoint=self.object_storage_endpoint,
            bucket=self.object_storage_bucket,
            access_key=self.object_storage_access_key,
            secret_key=self.object_storage_secret_key,
            local_dir=self.local_storage_dir,
        )


settings = Settings()
