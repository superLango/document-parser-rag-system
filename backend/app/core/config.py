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
    # 版面引擎固定 PP-DocLayoutV3（唯一引擎，2026-08 定版）
    PARSEKIT_LAYOUT_MODEL_DIR: str = str(
        Path(__file__).resolve().parents[3] / "models" / "pp_doclayoutv3"
    )
    # 置信度阈值（过滤低置信度框；调低可提升召回、调高提升精确率）
    PARSEKIT_LAYOUT_CONF_THRESHOLD: float = 0.4
    PARSEKIT_DPI: int = 200
    PARSEKIT_HEADER_FOOTER_MODE: str = "rule"  # A/B 择优后的胜出方案
    PARSEKIT_PAGE_CONCURRENCY: int = 4
    PARSEKIT_BLOCK_CONCURRENCY: int = 8
    PARSEKIT_PARTIAL_ON_PAGE_FAILURE: bool = True
    PARSEKIT_TITLE_FONT_THRESHOLD: float = 14.0
    PARSEKIT_IMAGE_MIN_AREA: float = 800.0
    PARSEKIT_OCR_ENABLED: bool = True
    PARSEKIT_OCR_FAILURE_POLICY: str = "partial"  # partial | failed（U13）
    PARSEKIT_INTERMEDIATE_RETENTION_DAYS: int = 7  # U14：pages 中间产物保留天数

    # ---------- GLM-OCR（Phase 3，U6/U7/U13） ----------
    GLMOCR_SERVER_URL: str = "http://127.0.0.1:9977/v1/chat/completions"
    GLMOCR_MODEL: str = "GLM-OCR"
    GLMOCR_MAX_TOKENS: int = 4096
    GLMOCR_TIMEOUT_SECONDS: int = 120
    GLMOCR_RETRIES: int = 2
    GLMOCR_MAX_EDGE: int = 2048
    GLMOCR_MIN_EDGE: int = 32

    # ---------- 嵌入（S3/D2：BGE-M3，dense only） ----------
    EMBEDDING_MODEL_DIR: str = str(
        Path(__file__).resolve().parents[3] / "models" / "bge-m3"
    )
    EMBEDDING_DEVICE: str = "cuda"  # cuda | cpu
    EMBEDDING_FP16: bool = True
    EMBEDDING_BATCH_SIZE: int = 16  # 原版实测最优（batch_size=16）
    EMBEDDING_MAX_LENGTH: int = 8192  # BGE-M3 最大序列（大表格块友好）
    EMBEDDING_DIM: int = 1024  # BGE-M3 输出维度（D2 已确认）

    # ---------- BM25（S5/D4：jieba 词法检索，零 LLM） ----------
    BM25_K1: float = 1.5
    BM25_B: float = 0.75

    # ---------- 检索（S6/D6：dense 双路 + BM25 + RRF） ----------
    RETRIEVAL_TITLE_WEIGHT: float = 0.2
    RETRIEVAL_CONTENT_WEIGHT: float = 0.8
    RETRIEVAL_RRF_K: float = 60.0
    RETRIEVAL_DENSE_WEIGHT: float = 1.0
    RETRIEVAL_KEYWORD_WEIGHT: float = 1.2
    RETRIEVAL_TOP_K: int = 10
    RETRIEVAL_CANDIDATE_MULT: int = 2
    # 索引嵌入单路超时（秒），防任务悬挂
    INDEX_EMBED_TIMEOUT: int = 120

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
