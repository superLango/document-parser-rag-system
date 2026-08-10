"""应用配置模块（pydantic-settings）。"""

from functools import lru_cache

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
    RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # ---------- 注册与初始管理员 ----------
    ALLOW_REGISTRATION: bool = True
    AUTO_CREATE_ADMIN: bool = True
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

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
