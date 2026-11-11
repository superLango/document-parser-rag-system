from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()
