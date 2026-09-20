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

    # ---------- 一站式任务状态回调 ----------
    # 2026-09-20：回调地址改为 172.16.1.33（原 192.168.0.141）；可用环境变量覆盖
    INTEGRATION_STATUS_CALLBACK_URL: str = (
        "http://172.16.1.33/oapi/aiDocParse/receiveParseStatus"
    )
    INTEGRATION_STATUS_CALLBACK_TIMEOUT_SECONDS: int = 10
    INTEGRATION_STATUS_CALLBACK_MAX_ATTEMPTS: int = 3

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
    # 分块阶段丢弃被重复识别的表格（同一张表输出两份 → 抽取结果重复）。
    # 判定只看表格自身归一化文本，与文档领域无关；置 False 可回退旧行为。
    CHUNK_TABLE_DEDUPE_ENABLED: bool = True

    # ---------- 任务派发自愈（outbox 卡住重投） ----------
    # 已派发但 worker 在此时长内仍未开工（DocumentTask 仍为 queued）的 outbox 行会被重置重投。
    PARSE_DISPATCH_RETRY_AFTER_SECONDS: int = 60
    # cron 派发器每轮自动回收卡住的 outbox 行（worker 重启 / Redis 作业丢失后自愈）。
    TASK_STUCK_REAPER_ENABLED: bool = True
    # 回收判定阈值：claimed/enqueued 超过该时长且关联任务仍为 queued 才重投。
    TASK_STUCK_REAPER_SECONDS: int = 300

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

    # ---------- 模型预热（启动时异步加载/检测，避免流程中模型不可用） ----------
    MODEL_WARMUP_ENABLED: bool = True  # 后端启动时执行模型预热
    # 跳过外部 vLLM 预热（llm_qwen/glm_ocr）：容器化部署时 OCR/LLM 独立运行
    MODEL_WARMUP_SKIP_EXTERNAL: bool = True
    RERANKER_MODEL_DIR: str = str(
        Path(__file__).resolve().parents[3] / "models" / "bge-reranker-v2-m3"
    )
    LLM_SERVER_URL: str = "http://127.0.0.1:9988/v1"  # Qwen3.6 vLLM 服务
    LLM_SERVER_MODEL: str = "Qwen3.6-35B-A3B-FP8"
    # LLM 上下文窗口（tokens）：按部署模型调整，当前服务为 131072（128K）
    LLM_CONTEXT_WINDOW_TOKENS: int = 131072

    # ---------- BM25（S5/D4：jieba 词法检索，零 LLM） ----------
    BM25_K1: float = 1.5
    BM25_B: float = 0.75

    # ---------- 抽取脚本（E3：kb_tools 内部嵌入端点回调地址） ----------
    SCRIPT_EMBED_BASE_URL: str = "http://127.0.0.1:8000"

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

    # ---------- 专业术语集（S8） ----------
    TERM_SYNC_CRON_HOURS: str = "3"  # 术语集定时同步小时（逗号分隔，如 "2,14"）
    TERM_SYNC_BATCH_LIMIT: int = 20  # 单轮同步术语集数量上限
    TERM_SOURCE_CONNECT_TIMEOUT: int = 10  # 外部数据源连接超时（秒）
    TERM_SOURCE_MAX_RESPONSE_MB: int = 5  # 外部数据源响应体上限（MB）
    TERM_SYNC_IMPORT_LIMIT: int = 5000  # 单术语集同步/批量导入词条上限

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
