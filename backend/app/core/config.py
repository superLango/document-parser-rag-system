"""应用配置模块。

本模块使用 pydantic-settings 从环境变量（或 .env 文件）加载全部配置项，
作为整个后端服务的统一配置入口。配置项涵盖：

- 应用基础信息（名称、环境、调试开关）
- PostgreSQL 数据库连接
- Redis 缓存
- MinIO 对象存储
- Neo4j 图数据库
- Milvus 向量数据库
- JWT 鉴权
- Ollama 大模型服务
- PaddleOCR 模型路径
- 文件上传限制
- Celery 异步任务队列

使用方式：
    from app.core.config import settings
    settings.DATABASE_URL

注意：
    生产环境下敏感字段（密码、密钥等）应通过真实环境变量注入，
    而非提交到 .env 文件。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """后端服务配置类。

    所有字段与 backend/.env.example 中定义的环境变量一一对应。
    通过 pydantic-settings 自动完成类型校验与转换。
    """

    # ---------------------------------------------------------------
    # 应用基础配置
    # ---------------------------------------------------------------
    APP_NAME: str = Field(default="DocumentParser", description="应用名称")
    APP_ENV: str = Field(default="development", description="运行环境")
    DEBUG: bool = Field(default=True, description="是否开启调试模式")

    # ---------------------------------------------------------------
    # PostgreSQL 数据库配置
    # ---------------------------------------------------------------
    POSTGRES_HOST: str = Field(default="localhost", description="PostgreSQL 主机地址")
    POSTGRES_PORT: int = Field(default=5432, description="PostgreSQL 端口")
    POSTGRES_DB: str = Field(default="docparser", description="PostgreSQL 数据库名")
    POSTGRES_USER: str = Field(default="postgres", description="PostgreSQL 用户名")
    POSTGRES_PASSWORD: str = Field(default="change_me", description="PostgreSQL 密码")
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:change_me@localhost:5432/docparser",
        description="异步数据库连接字符串（asyncpg 驱动）",
    )

    # ---------------------------------------------------------------
    # Redis 配置
    # ---------------------------------------------------------------
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0", description="Redis 连接字符串"
    )

    # ---------------------------------------------------------------
    # MinIO 对象存储配置
    # ---------------------------------------------------------------
    MINIO_ENDPOINT: str = Field(default="localhost:9000", description="MinIO 服务端点")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin", description="MinIO 访问密钥")
    MINIO_SECRET_KEY: str = Field(
        default="change_me_minio", description="MinIO 访问密钥（保密）"
    )
    MINIO_BUCKET: str = Field(default="documents", description="MinIO 默认存储桶名")
    MINIO_SECURE: bool = Field(default=False, description="是否启用 HTTPS 访问 MinIO")

    # ---------------------------------------------------------------
    # Neo4j 图数据库配置
    # ---------------------------------------------------------------
    NEO4J_URI: str = Field(default="bolt://localhost:7687", description="Neo4j 连接 URI")
    NEO4J_USER: str = Field(default="neo4j", description="Neo4j 用户名")
    NEO4J_PASSWORD: str = Field(
        default="change_me_neo4j", description="Neo4j 密码（保密）"
    )

    # ---------------------------------------------------------------
    # Milvus 向量数据库配置
    # ---------------------------------------------------------------
    MILVUS_HOST: str = Field(default="localhost", description="Milvus 主机地址")
    MILVUS_PORT: int = Field(default=19530, description="Milvus 端口")
    MILVUS_COLLECTION: str = Field(
        default="doc_chunks", description="Milvus 默认集合名"
    )

    # ---------------------------------------------------------------
    # 嵌入模型配置（bge-m3 Dense+Sparse 向量）
    # ---------------------------------------------------------------
    EMBEDDING_MODEL_PATH: str = Field(
        default="/home/hanson/doc_parse_project/models/bge-m3",
        description="bge-m3 嵌入模型目录路径",
    )
    EMBEDDING_BATCH_SIZE: int = Field(
        default=4, description="嵌入批量大小（防止显存溢出）"
    )

    # ---------------------------------------------------------------
    # JWT 鉴权配置
    # ---------------------------------------------------------------
    SECRET_KEY: str = Field(
        default="change_me_secret_key_at_least_32_chars",
        description="JWT 签名密钥（保密，生产环境必须替换）",
    )
    ALGORITHM: str = Field(default="HS256", description="JWT 签名算法")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=1440, description="访问令牌过期时间（分钟）"
    )

    # ---------------------------------------------------------------
    # Ollama 大模型服务配置
    # ---------------------------------------------------------------
    OLLAMA_HOST: str = Field(
        default="http://localhost:11434", description="Ollama 服务地址"
    )
    OLLAMA_MODEL: str = Field(default="gemma2:2b", description="Ollama 默认模型名")

    # ---------------------------------------------------------------
    # OCR 配置
    # ---------------------------------------------------------------
    PADDLE_OCR_MODEL_DIR: str = Field(
        default="/app/models/PaddlePaddle/PaddleOCR-VL",
        description="PaddleOCR 模型目录路径",
    )

    # ---------------------------------------------------------------
    # 文件上传配置
    # ---------------------------------------------------------------
    MAX_FILE_SIZE: int = Field(
        default=524288000, description="允许上传的最大文件大小（字节），默认 500MB"
    )
    ALLOWED_EXTENSIONS: str = Field(
        default=".pdf,.png,.jpg,.jpeg,.tiff,.bmp",
        description="允许上传的文件扩展名（逗号分隔）",
    )

    # ---------------------------------------------------------------
    # Celery 异步任务队列配置
    # ---------------------------------------------------------------
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/1", description="Celery 消息代理地址"
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/2", description="Celery 结果后端地址"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def allowed_extensions_list(self) -> list[str]:
        """将逗号分隔的扩展名字符串转为列表。

        Returns:
            list[str]: 扩展名列表，例如 [".pdf", ".png"]。
        """
        return [ext.strip() for ext in self.ALLOWED_EXTENSIONS.split(",") if ext.strip()]


# 模块级单例配置对象，供整个应用直接导入使用
settings = Settings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回全局 Settings 单例。

    使用 lru_cache 缓存以避免重复解析环境变量，便于在测试中覆盖。

    Returns:
        Settings: 全局配置实例。
    """
    return Settings()
