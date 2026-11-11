from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from services.shared.storage import StorageConfig


class OcrSettings(BaseSettings):
    ocr_backend: str = "auto"
    ocr_dpi: int = 150
    glm_ocr_base_url: str = ""
    glm_ocr_model: str = ""
    glm_ocr_timeout_seconds: float = 180.0
    layout_base_url: str = ""
    layout_timeout_seconds: float = 60.0
    table_repairs_path: str = ""

    object_storage_endpoint: str = "http://localhost:19000"
    object_storage_bucket: str = "hanson-docs"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: str = "minioadmin"
    local_storage_dir: Path = Path("/tmp/hanson-new-app")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def storage_config(self) -> StorageConfig:
        return StorageConfig(
            endpoint=self.object_storage_endpoint,
            bucket=self.object_storage_bucket,
            access_key=self.object_storage_access_key,
            secret_key=self.object_storage_secret_key,
            local_dir=self.local_storage_dir,
        )


settings = OcrSettings()
