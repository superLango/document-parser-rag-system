from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from services.shared.storage import StorageConfig


class OcrSettings(BaseSettings):
    ocr_backend: str = "auto"
    ocr_dpi: int = 150
    glm_ocr_base_url: str = ""
    glm_ocr_model: str = ""
    glm_ocr_timeout_seconds: float = 180.0
    glm_ocr_read_timeout_seconds: float = 90.0
    glm_ocr_max_tokens: int = 4096
    glm_ocr_document_timeout_seconds: float = 300.0
    glm_ocr_page_budget_seconds: float = 20.0
    glm_ocr_max_document_timeout_seconds: float = 900.0
    glm_ocr_page_concurrency: int = 2
    # 跨文档全局闸门：GLM-OCR 现场 max-num-seqs=16，避免多文档并发时打爆队列。
    glm_ocr_max_concurrency: int = 8
    layout_base_url: str = ""
    layout_timeout_seconds: float = 15.0
    layout_only_for_vision: bool = True
    # Layout blocks drive text/table OCR instead of whole-page OCR.
    ocr_layout_first: bool = True
    layout_block_concurrency: int = 2
    layout_page_concurrency: int = 4
    layout_page_timeout_seconds: float = 600.0
    table_repairs_path: str = ""
    # W2 Tier1: borderless tables recovered from word coordinates.
    ocr_text_table_fallback: bool = True

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
