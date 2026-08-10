"""应用配置模块（pydantic-settings）。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """后端服务配置。"""

    # ---------- 应用 ----------
    APP_NAME: str = "HansonDOC RAG"
    APP_ENV: str = "development"
    DEBUG: bool = True
    VERSION: str = "3.0.0"
    CORS_ORIGINS: str = "*"
    ADMIN_IP_WHITELIST: str = ""

    # ---------- PostgreSQL ----------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "hanson_doc_rag"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "change_me"
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:change_me@localhost:5432/hanson_doc_rag"
    )

    # ---------- Redis ----------
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---------- JWT ----------
    SECRET_KEY: str = "change_me_secret_key_at_least_32_chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---------- 密码与登录安全 ----------
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_REQUIRE_UPPER: bool = True
    PASSWORD_REQUIRE_LOWER: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = False
    PASSWORD_HISTORY_SIZE: int = 5
    PASSWORD_EXPIRE_DAYS: int = 90
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCK_MINUTES: int = 30
    AUTH_LIMIT: str = "5/minute"
    INVITATION_EXPIRE_HOURS: int = 72
    REGISTRATION_DEFAULT_PENDING: bool = False
    RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # ---------- 注册与初始管理员 ----------
    ALLOW_REGISTRATION: bool = True
    AUTO_CREATE_ADMIN: bool = True
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # ---------- 对象存储（Phase 1） ----------
    STORAGE_DRIVER: str = "minio"  # minio | local
    LOCAL_STORAGE_DIR: str = "./data/storage"
    MINIO_ENDPOINT: str = "127.0.0.1:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET_PREFIX: str = "hansondoc"

    # ---------- 任务编排（Phase 1） ----------
    TASK_EXECUTOR: str = "sync"  # sync（开发） | arq（生产，需 Redis）
    TASK_DISPATCH_INTERVAL_SECONDS: int = 2
    TASK_MAX_ATTEMPTS: int = 3
    TASK_HEARTBEAT_SECONDS: int = 10
    DOCUMENT_MAX_SIZE_MB: int = 100

    # ---------- 文档解析管线（Phase 2 parsekit） ----------
    PARSEKIT_LAYOUT_ENGINE: str = "doclayout"  # doclayout（生产，权重已部署） | rule（快速/测试）
    PARSEKIT_LAYOUT_MODEL_DIR: str = str(
        Path(__file__).resolve().parents[3] / "models" / "doclayout_yolo"
    )
    PARSEKIT_DPI: int = 200
    PARSEKIT_HEADER_FOOTER_MODE: str = "rule"  # A/B 择优后的胜出方案
    PARSEKIT_PAGE_CONCURRENCY: int = 4
    PARSEKIT_BLOCK_CONCURRENCY: int = 8
    PARSEKIT_PARTIAL_ON_PAGE_FAILURE: bool = True
    PARSEKIT_TITLE_FONT_THRESHOLD: float = 14.0
    PARSEKIT_IMAGE_MIN_AREA: float = 800.0
    PARSEKIT_OCR_ENABLED: bool = True
    PARSEKIT_OCR_FAILURE_POLICY: str = "partial"  # partial | failed（U13）

    # ---------- GLM-OCR（Phase 3，U6/U7/U13） ----------
    GLMOCR_SERVER_URL: str = "http://127.0.0.1:9977/v1/chat/completions"
    GLMOCR_MODEL: str = "GLM-OCR"
    GLMOCR_MAX_TOKENS: int = 4096
    GLMOCR_TIMEOUT_SECONDS: int = 120
    GLMOCR_RETRIES: int = 2
    GLMOCR_MAX_EDGE: int = 2048
    GLMOCR_MIN_EDGE: int = 32

    # ---------- 审计与可观测性 ----------
    AUDIT_LOG_RETENTION_DAYS: int = 90
    ENABLE_METRICS: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
