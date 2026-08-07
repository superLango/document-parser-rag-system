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
- GLM-OCR 自托管配置
- 文件上传限制
- arq 异步任务队列（基于 Redis）

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
    APP_NAME: str = Field(default="Hansight", description="应用名称")
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
    S3_ENDPOINT_URL: str = Field(
        default="http://localhost:9000", description="S3兼容存储端点URL（SeaweedFS）"
    )

    # ---------------------------------------------------------------
    # NebulaGraph 图数据库配置（替代 Neo4j，原生多 graph space 物理隔离）
    # 每个 KB 独占一个 graph space（{prefix}{kb_id_hex}），物理隔离、独立销毁
    # ---------------------------------------------------------------
    NEBULA_GRAPHD_HOST: str = Field(default="localhost", description="NebulaGraph graphd 主机")
    NEBULA_GRAPHD_PORT: int = Field(default=9669, description="NebulaGraph graphd 端口")
    NEBULA_USER: str = Field(default="root", description="NebulaGraph 用户名")
    NEBULA_PASSWORD: str = Field(default="nebula", description="NebulaGraph 密码（保密）")
    NEBULA_SPACE_PREFIX: str = Field(default="kb_", description="KB graph space 命名前缀")
    NEBULA_GLOBAL_SPACE: str = Field(default="global", description="全局 graph space 名（kb_id=None 时使用，向后兼容）")

    # ---------------------------------------------------------------
    # 知识库（KnowledgeBase）隔离配置
    # ---------------------------------------------------------------
    KB_DEFAULT_DOMAIN: str = Field(default="material_testing", description="默认领域编码")
    KB_MINIO_BUCKET_PREFIX: str = Field(default="kb-", description="KB MinIO bucket 命名前缀")
    KB_MILVUS_COLLECTION_SEPARATOR: str = Field(default="_", description="KB Milvus Collection 名分隔符（{base}{sep}{kb_id}）")
    KB_REDIS_KEY_PREFIX: str = Field(default="kb:", description="KB Redis key 前缀")
    KB_OCR_DATA_DIR: str = Field(default="data/ocr_data", description="KB OCR 输出根目录（按 kb_id 子目录隔离）")

    # ---------------------------------------------------------------
    # Neo4j 图数据库配置（兼容保留，待阶段 2.5 graph_store 迁移 NebulaGraph 后删除）
    # ---------------------------------------------------------------
    NEO4J_URI: str = Field(default="bolt://localhost:7687", description="Neo4j 连接 URI（兼容保留）")
    NEO4J_USER: str = Field(default="neo4j", description="Neo4j 用户名（兼容保留）")
    NEO4J_PASSWORD: str = Field(
        default="change_me_neo4j", description="Neo4j 密码（兼容保留）"
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
        default=16, description="嵌入批量大小（P2.2 优化：从 4 提升到 16，利用批量推理加速）"
    )

    # ---------------------------------------------------------------
    # vLLM 大语言模型配置
    # ---------------------------------------------------------------
    LLM_MODEL_PATH: str = Field(
        default="/home/hanson/doc_parse_project/models/Qwen/Qwen3___5-9B",
        description="vLLM 大语言模型权重目录路径",
    )
    # 远程 vLLM OpenAI 兼容 API 配置（设置后优先使用 API 模式，无需本地安装 vllm）
    LLM_API_BASE: str | None = Field(
        default="http://localhost:9988/v1",
        description="远程 vLLM OpenAI 兼容 API 地址（9988端口为通用LLM）",
    )
    LLM_API_MODEL: str = Field(
        default="Qwem3.6-35B-A3B-FP8",
        description="远程 API 使用的模型名称（与vLLM served-model-name一致）",
    )
    # 轻量模型配置（统一使用9988端口模型）
    LLM_LIGHT_MODEL: str = Field(
        default="Qwem3.6-35B-A3B-FP8",
        description="轻量模型名称（统一使用9988端口vLLM模型）",
    )

    # ---------------------------------------------------------------
    # 重排模型配置（bge-reranker-v2-m3 CrossEncoder）
    # ---------------------------------------------------------------
    RERANKER_MODEL_DIR: str = Field(
        default="models/bge-reranker-v2-m3",
        description="CrossEncoder重排模型路径",
    )

    # ---------------------------------------------------------------
    # RAG 编排配置
    # ---------------------------------------------------------------
    RAG_TOP_K: int = Field(default=5, description="RAG检索默认返回数量")
    RAG_RERANK_POOL: int = Field(default=15, description="RAG重排候选池大小")
    RAG_MAX_CONTEXT_LENGTH: int = Field(default=8192, description="RAG上下文最大token数")

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
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, description="刷新令牌过期时间（天），用于静默续期 access token"
    )

    # ---------------------------------------------------------------
    # Ollama 大模型服务配置
    # ---------------------------------------------------------------
    OLLAMA_HOST: str = Field(
        default="http://localhost:11434", description="Ollama 服务地址"
    )
    OLLAMA_MODEL: str = Field(default="gemma2:2b", description="Ollama 默认模型名")

    # ---------------------------------------------------------------
    # 结构化抽取 LLM 配置（vLLM OpenAI 兼容）
    # 切换 provider 只需改 EXTRACTION_PROVIDER + 对应 *_API_BASE/*_MODEL_ID
    # ---------------------------------------------------------------
    EXTRACTION_PROVIDER: str = Field(
        default="openai",
        description="结构化抽取 LLM provider（ollama/openai）；openai 兼容 vLLM",
    )
    # OpenAI/vLLM 兼容模式（EXTRACTION_PROVIDER=openai 时生效）
    EXTRACTION_API_BASE: str = Field(
        default="http://localhost:9988/v1",
        description="抽取 LLM OpenAI 兼容端点（vLLM served-model-name 对应地址）",
    )
    EXTRACTION_API_KEY: str = Field(
        default="EMPTY",
        description="抽取 LLM API Key（自托管 vLLM 用 EMPTY）",
    )
    EXTRACTION_MODEL_ID: str = Field(
        default="Qwem3.6-35B-A3B-FP8",
        description="抽取 LLM 模型 ID（必须与 vLLM --served-model-name 完全一致）",
    )
    EXTRACTION_MAX_CONCURRENCY: int = Field(
        default=12,
        description=(
            "多类别并行抽取并发上限（application 层 asyncio.Semaphore）。"
            "与 EXTRACTION_LANGEXTRACT_MAX_WORKERS 共同决定 vLLM inflight 请求数："
            "inflight = MAX_CONCURRENCY × LANGEXTRACT_MAX_WORKERS。"
            "当前 12 × 1 = 12，匹配 vLLM --max-num-seqs=12，无排队。"
            "10 个大类全部并行抽取，每类别内分块串行处理。"
        ),
    )
    EXTRACTION_MAX_OUTPUT_TOKENS: int = Field(
        default=32768,
        description=(
            "抽取单次生成最大 token 数（openai max_tokens）。"
            "max_char_buffer=20000时化学成分切2 chunks，每chunk约248条≈14000 tokens < 32768 ✅。"
            "约束：max_tokens + prompt_tokens ≤ max-model-len=65536。"
            "实测 prompt 约 16000 tokens（max_char_buffer=20000），32768 输出，总和 48768 < 65536 ✅。"
            "需确保 vLLM --max-num-batched-tokens ≥ max_tokens（当前 32768 ✅）。"
        ),
    )
    EXTRACTION_TEMPERATURE: float = Field(
        default=0.1,
        description="抽取温度（低温度提升结构化输出稳定性）",
    )
    # LangExtract output_schema 强约束模式开关
    EXTRACTION_OUTPUT_SCHEMA_MODE: str = Field(
        default="auto",
        description=(
            "LangExtract output_schema 强约束模式："
            "auto=有 schema 走 schema，无 schema 走 examples（推荐）；"
            "always=强制 schema（未注册类别回退到 examples）；"
            "never=完全禁用，回滚到纯 examples 模式"
        ),
    )
    # P2 阶段：低风险参数调优
    EXTRACTION_PASSES: int = Field(
        default=1,
        description=(
            "抽取轮数：1=单轮（默认，快速），2=双轮（+10-15%召回率，2x token 成本+耗时）。"
            "多轮抽取会重新处理文本以发现遗漏的实体，首轮结果优先。"
            "注意：双轮抽取耗时约 6x，建议仅在长文档漏抽严重时启用。"
        ),
    )
    EXTRACTION_CONTEXT_WINDOW_CHARS: int = Field(
        default=1000,
        description=(
            "跨分块上下文窗口字符数：0=禁用，1000=推荐值。"
            "将前一 chunk 的末尾 N 字符作为当前 chunk 的 additional_context，"
            "用于跨块共指消解（如 '该牌号'、'上述材料' 等代词解析）。"
        ),
    )
    EXTRACTION_MAX_CHAR_BUFFER: int = Field(
        default=20000,
        description=(
            "LangExtract 分块字符数上限：将召回文本按此值切分为多个 chunks，"
            "每 chunk 触发一次 LLM 调用。"
            "实测 Qwen tokenizer ratio=0.52 tokens/char。"
            "max_tokens=16384, prompt≈16000 tokens + 16384 = 32384 < 65536 ✅。"
            "化学成分40000字符切2 chunks，每chunk约248条≈14000 tokens < 16384 ✅。"
            "降低max_char_buffer从40000到20000，让长表切2 chunks，减少单次生成时间。"
            "原默认 1000 会导致 30000 字符文本切成 30 chunks，LLM 调用 30x。"
        ),
    )
    EXTRACTION_LANGEXTRACT_MAX_WORKERS: int = Field(
        default=1,
        description=(
            "LangExtract 内部分块并行线程数（ThreadPoolExecutor max_workers）。"
            "与 EXTRACTION_MAX_CONCURRENCY 共同决定 vLLM inflight 请求数："
            "inflight = MAX_CONCURRENCY × LANGEXTRACT_MAX_WORKERS。"
            "当前 10 × 1 = 10 ≤ 12，匹配 vLLM --max-num-seqs=12，无排队。"
            "10 大类全并行，每类别内分块串行处理。"
        ),
    )
    # P3 阶段：Prompt 校验收紧
    EXTRACTION_PROMPT_VALIDATION_LEVEL: str = Field(
        default="warning",
        description=(
            "Prompt 校验级别：off=禁用，warning=告警（默认），error=严格（不合规直接 raise）。"
            "注意：error 模式要求 examples 与 output_schema 格式完全对齐，"
            "当前因 examples 用扁平字段模式、output_schema 用类+属性模式，"
            "切换到 error 会导致抽取失败。建议修复 examples 后再启用。"
        ),
    )

    # ---------------------------------------------------------------
    # 任务2：Prompt 结构优化与 Prefix Caching
    # ---------------------------------------------------------------
    EXTRACTION_PROMPT_STATIC_PREFIX_ENABLED: bool = Field(
        default=True,
        description=(
            "是否启用静态前缀 Prompt 结构（将白名单从 description 移到 additional_context）。"
            "启用后所有类别的 description 以相同静态前缀开头，最大化 vLLM prefix cache 命中率。"
        ),
    )
    EXTRACTION_PROMPT_CACHE_WARMUP_ENABLED: bool = Field(
        default=True,
        description="是否启用低峰期 Prompt 缓存预热（arq cron 任务）",
    )
    EXTRACTION_PROMPT_CACHE_WARMUP_CRON_HOUR: int = Field(
        default=1,
        description="Prompt 缓存预热执行小时（24h 制，默认凌晨 1 点）",
    )

    # ---------------------------------------------------------------
    # 任务1：召回阶段 gliclass 类别过滤
    # ---------------------------------------------------------------
    EXTRACTION_RECALL_CLASSIFY_FILTER_ENABLED: bool = Field(
        default=True,
        description=(
            "召回阶段是否启用 gliclass 零样本分类过滤。"
            "启用后对每个召回分块进行类别判断，过滤掉不属于当前类别的分块，"
            "减少跨类混入。失败时降级为无过滤（保留原行为）。"
        ),
    )
    EXTRACTION_RECALL_CLASSIFY_THRESHOLD: float = Field(
        default=0.5,
        description="gliclass 类别过滤置信度阈值（0.0-1.0，越低越宽松）",
    )
    EXTRACTION_RECALL_MIN_CHUNKS: int = Field(
        default=1,
        description="过滤后最小保留分块数（保底召回，避免空召回）",
    )
    GLICLASS_MODEL_PATH: str = Field(
        default="models/gliclass-multilang-mini",
        description="gliclass 零样本分类模型路径",
    )
    GLICLASS_BATCH_SIZE: int = Field(
        default=16,
        description="gliclass 批量推理大小",
    )
    GLICLASS_MAX_LENGTH: int = Field(
        default=512,
        description="gliclass 最大 token 长度（mdeberta-v3 max_position_embeddings=512）",
    )

    # ---------------------------------------------------------------
    # 任务3：语义分块与知识图谱
    # ---------------------------------------------------------------
    EXTRACTION_SEMANTIC_CHUNKING_ENABLED: bool = Field(
        default=False,
        description=(
            "是否启用语义分块（替代 LangExtract 默认字符切分）。"
            "默认关闭，需任务1的 gliclass 类别过滤先就绪。"
        ),
    )
    EXTRACTION_SEMANTIC_CHUNK_SIZE: int = Field(
        default=8000,
        description="语义分块目标字符数上限",
    )
    EXTRACTION_SEMANTIC_CHUNK_MIN_SIZE: int = Field(
        default=1000,
        description="语义分块最小字符数下限",
    )
    EXTRACTION_CHUNK_SUMMARY_ENABLED: bool = Field(
        default=False,
        description="是否为每个语义块生成上下文摘要（需额外 LLM 调用）",
    )
    # Ollama 模式（EXTRACTION_PROVIDER=ollama 时生效，保留以支持回滚）
    EXTRACTION_OLLAMA_MODEL: str = Field(
        default="qwen3.6:35b",
        description="Ollama 模式下的模型 ID（回滚用）",
    )
    EXTRACTION_OLLAMA_NUM_CTX: int = Field(
        default=32768,
        description="Ollama 模式下的上下文窗口大小",
    )
    EXTRACTION_OLLAMA_TIMEOUT: int = Field(
        default=300,
        description="Ollama 模式下的请求超时秒数",
    )
    # 方案 11：文档大类识别阈值
    # （基础三表已移除，由术语集替代，相关阈值不再需要）
    # PROJECT_DICT_DOC_DETECT_MIN_HITS 已移除

    # ---------------------------------------------------------------
    # OCR 配置（GLM-OCR 自托管模式）
    # ---------------------------------------------------------------
    # OCR 任务输出根目录（每次任务在 data/ocr_data/{task_id}/ 下保存源文件与结果）
    OCR_OUTPUT_DIR: str = Field(
        default="./data/ocr_data",
        description="OCR 任务输出根目录",
    )

    # OCR 文本清洗等级：light / medium / deep
    OCR_CLEAN_LEVEL: str = Field(
        default="medium",
        description="OCR 文本清洗等级（light/medium/deep）",
    )

    # ---------------------------------------------------------------
    # 五维向量索引配置（层级感知重建 + 单 Collection 多向量字段）
    # ---------------------------------------------------------------
    # 五维向量 Collection 名称（单 Collection，5 个向量字段）
    FIVE_DIM_VECTOR_COLLECTION: str = Field(
        default="doc_five_dim",
        description="五维向量 Collection 名称",
    )
    # 子块最大字符数（bge-m3 max_length=8192，留余量）
    VECTOR_CHILD_MAX_CHARS: int = Field(
        default=2000,
        description="子块最大字符数",
    )

    # ---------------------------------------------------------------
    # GLM-OCR 引擎配置（vLLM 服务，默认 9977 端口）
    # ---------------------------------------------------------------
    # GLM-OCR 0.9B 参数，BF16 约 1.8GB 显存。
    # 预处理 pipeline：倾斜校正 + 条件增强 + PP-DocLayoutV3 版面分析
    # + 区域级 GLM-OCR 识别。去水印跳过（模型内置水印鲁棒性）。
    GLMOCR_SERVER_URL: str = Field(
        default="http://localhost:9977/v1",
        description="GLM-OCR vLLM 服务 OpenAI 兼容端点",
    )
    GLMOCR_MODEL: str = Field(
        default="GLM-OCR",
        description="GLM-OCR 模型名（vLLM --served-model-name，大小写敏感）",
    )
    GLMOCR_API_KEY: str = Field(
        default="",
        description="GLM-OCR API Key（自托管 vLLM 通常为空）",
    )
    GLMOCR_PDF_DPI: int = Field(
        default=200,
        description="GLM-OCR PDF 渲染 DPI（官方默认 200，独立工具方法使用）",
    )
    GLMOCR_MAX_CONCURRENCY: int = Field(
        default=12,
        description=(
            "GLM-OCR vLLM 并发请求数（区域级并行上限）。"
            "建议设为 vLLM --max-num-seqs 的 60-80%。"
            "当前 vLLM --max-num-seqs=16，故设为 12。"
        ),
    )
    GLMOCR_MAX_TOKENS: int = Field(
        default=4096,
        description=(
            "GLM-OCR 单次识别最大输出 token 数。"
            "表格场景需要 4096（含 HTML 标签），文本场景 2048 足够。"
        ),
    )
    GLMOCR_MODE: str = Field(
        default="fullpage",
        description="GLM-OCR 识别模式：fullpage=整页 markdown 输出（推荐，表格/脚注/顺序最优），layout=版面分析+区域识别",
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
    # arq 异步任务队列配置（基于 Redis）
    # ---------------------------------------------------------------
    # arq 使用 Redis database=1 作为任务队列，与原 Celery broker 一致。
    # Redis 连接参数复用 REDIS_URL 中的主机与端口配置。

    # ---------------------------------------------------------------
    # Milvus 五维向量集合配置（基础三表已移除，由术语集替代）
    # 原检测项目字典（三元基础表）同步/白名单/向量集合配置已移除
    # ---------------------------------------------------------------

    # ---------------------------------------------------------------
    # v3 结构化抽取配置（EXTRACTION_V3_* 前缀，独立于 v1/v2）
    # 以 services/vector/ 五维向量为底座，双线路 LLM 抽取
    # LLM 基线：Qwen3.5-9B-FP8-dynamic（vLLM max-num-seqs=32, MTP-1）
    # ---------------------------------------------------------------
    # LLM 端点（vLLM OpenAI 兼容）
    EXTRACTION_V3_LLM_API_BASE: str = Field(
        default="http://localhost:9988/v1",
        description="v3 抽取 LLM OpenAI 兼容端点（vLLM served-model-name 对应地址）",
    )
    EXTRACTION_V3_LLM_MODEL: str = Field(
        default="Qwem3.6-35B-A3B-FP8",
        description="v3 抽取 LLM 模型 ID（必须与 vLLM --served-model-name 完全一致）",
    )
    EXTRACTION_V3_LLM_API_KEY: str = Field(
        default="EMPTY",
        description="v3 抽取 LLM API Key（自托管 vLLM 用 EMPTY）",
    )
    EXTRACTION_V3_LLM_MAX_CONCURRENCY: int = Field(
        default=24,
        description=(
            "v3 LLM 调用总并发上限（全局 Semaphore）。"
            "vLLM --max-num-seqs=32，留 8 余量给调度和重试。"
            "LangExtract 线路：8 类别 × 3 workers = 24；"
            "glm-ocr 线路：24 类别 × 1 = 24。"
        ),
    )
    EXTRACTION_V3_LLM_MAX_OUTPUT_TOKENS: int = Field(
        default=32768,
        description=(
            "v3 抽取单次生成最大 token 数。"
            "约束：max_tokens + prompt_tokens ≤ max-model-len=65536。"
            "大表格场景需 32768 防止截断。"
        ),
    )
    EXTRACTION_V3_LLM_TEMPERATURE: float = Field(
        default=0.0,
        description="v3 抽取温度（glmocr 线路用 0.0 保证结构化输出稳定性）",
    )
    EXTRACTION_V3_LLM_TOP_P: float = Field(
        default=0.1,
        description="v3 抽取 top_p（glmocr 线路用 0.1）",
    )
    EXTRACTION_V3_LLM_TOP_K: int = Field(
        default=20,
        description="v3 抽取 top_k（glmocr 线路 extra_body 参数）",
    )

    # 抽取引擎选择
    EXTRACTION_V3_EXTRACTION_ENGINE: str = Field(
        default="BaseExtract",
        description=(
            "v3 抽取引擎：BaseExtract=线路 B（短/长文本分流+分批串行，小模型上更稳定）；"
            "LangExtract=线路 A（output_schema 强约束+类别内并发，质量更高）"
        ),
    )
    EXTRACTION_V3_EXTRACTION_FALLBACK_TO_GLMOCR: bool = Field(
        default=True,
        description="LangExtract 线路失败时是否降级到 glmocr 线路",
    )

    # Phase 2 类别构建
    EXTRACTION_V3_CATEGORY_CONFIDENCE_THRESHOLD: float = Field(
        default=0.35,
        description=(
            "Phase 2 类别置信度阈值。"
            "feature 的 item+method 作为 query 检索 doc_five_dim，"
            "max(hits.score) < 此值或无召回则剔除该 feature。"
        ),
    )
    EXTRACTION_V3_CATEGORY_CONCURRENCY: int = Field(
        default=8,
        description=(
            "Phase 2/3/4 feature 间调度并发上限。"
            "LangExtract 线路：8（8×3=24 匹配 LLM 并发）；"
            "glmocr 线路：动态调整为 24（24×1=24）。"
        ),
    )

    # Phase 3 向量检索
    EXTRACTION_V3_RETRIEVAL_TOP_K: int = Field(
        default=20,
        description="Phase 3 hybrid_search 融合后最终返回的记录数",
    )
    EXTRACTION_V3_RETRIEVAL_PER_DIM_TOP_K: int = Field(
        default=30,
        description="Phase 3 每维独立检索的 top_k（Milvus 要求 ≥ 最终 top_k）",
    )
    EXTRACTION_V3_RETRIEVAL_RERANK_ENABLED: bool = Field(
        default=True,
        description="是否启用 bge-reranker-v2-m3 重排序",
    )
    EXTRACTION_V3_RETRIEVAL_RERANK_TOP_K: int = Field(
        default=15,
        description="重排序后保留的记录数",
    )
    EXTRACTION_V3_CONTEXT_MAX_TOKENS: int = Field(
        default=28000,
        description="Phase 3 上下文最大 token 数（预留 32K 给 prompt+输出）",
    )
    EXTRACTION_V3_HYBRID_SEARCH_WEIGHTS: str = Field(
        default="path:0.15,title:0.20,content:0.45,type:0.05,structural:0.15",
        description="五维 hybrid_search 权重（逗号分隔 key:value）",
    )

    # Phase 4 LLM 抽取
    EXTRACTION_V3_LANGEXTRACT_PASSES: int = Field(
        default=2,
        description="LangExtract 线路多轮抽取轮数（1=单轮快速，2=双轮+召回率）",
    )
    EXTRACTION_V3_LANGEXTRACT_MAX_WORKERS: int = Field(
        default=3,
        description=(
            "LangExtract 类别内分块并发数。"
            "langextract 内部将长文本分块，max_workers 控制分块 LLM 调用并发。"
            "8 类别 × 3 workers = 24，匹配 vLLM max-num-seqs=32。"
        ),
    )
    EXTRACTION_V3_LANGEXTRACT_CONTEXT_WINDOW_CHARS: int = Field(
        default=28000,
        description="LangExtract 跨块共指消解窗口字符数",
    )
    EXTRACTION_V3_LANGEXTRACT_MAX_CHAR_BUFFER: int = Field(
        default=40000,
        description="LangExtract 单次 LLM 输入字符上限（减少分块数）",
    )
    EXTRACTION_V3_LARGE_TABLE_THRESHOLD: int = Field(
        default=8000,
        description="glmocr 线路长文本阈值（≥此值触发表格边界感知分批）",
    )
    EXTRACTION_V3_LARGE_TABLE_BATCH_CHARS: int = Field(
        default=6000,
        description="glmocr 线路单批字符上限（大表按行切分时每批目标字符数）",
    )
    EXTRACTION_V3_GLMOCR_CONTEXT_TRUNCATE: int = Field(
        default=32000,
        description="glmocr 线路单次 LLM 输入字符截断保护",
    )
    EXTRACTION_V3_BATCH_OVERLAP_CHARS: int = Field(
        default=500,
        description="glmocr 线路批间重叠字符数（共指消解）",
    )

    # 后处理
    EXTRACTION_V3_ITEM_NORMALIZE_SIM_THRESHOLD: float = Field(
        default=0.90,
        description="项目名向量归一化相似度阈值（≥此值视为匹配）",
    )
    EXTRACTION_V3_CROSS_VALIDATE_THRESHOLD: float = Field(
        default=0.35,
        description="跨类校验向量相似度阈值（<此值标记 _unverified）",
    )
    EXTRACTION_V3_DEDUP_SIM_THRESHOLD: float = Field(
        default=0.95,
        description="模糊去重向量相似度阈值（>此值视为重复）",
    )
    EXTRACTION_V3_EDIT_DISTANCE_THRESHOLD: float = Field(
        default=0.85,
        description="项目名编辑距离匹配阈值",
    )

    # ---------------------------------------------------------------
    # 生产级安全策略（阶段 1.1 / 3.2）
    # ---------------------------------------------------------------
    PASSWORD_MIN_LENGTH: int = Field(default=8, description="密码最小长度")
    PASSWORD_REQUIRE_UPPER: bool = Field(default=True, description="密码需含大写字母")
    PASSWORD_REQUIRE_LOWER: bool = Field(default=True, description="密码需含小写字母")
    PASSWORD_REQUIRE_DIGIT: bool = Field(default=True, description="密码需含数字")
    PASSWORD_REQUIRE_SPECIAL: bool = Field(default=False, description="密码需含特殊字符")
    PASSWORD_HISTORY_SIZE: int = Field(default=5, description="密码历史保留条数（禁止复用最近 N 个旧密码）")
    PASSWORD_EXPIRE_DAYS: int = Field(default=90, description="密码过期天数（0=不过期）")
    LOGIN_MAX_FAILURES: int = Field(default=5, description="连续登录失败上限（达到后锁定账户）")
    LOGIN_LOCK_MINUTES: int = Field(default=30, description="账户锁定时长（分钟）")
    RESET_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="密码重置令牌有效期（分钟）")
    CORS_ORIGINS: str = Field(default="*", description="允许的 CORS 来源（逗号分隔，生产环境应严格限定）")
    ADMIN_IP_WHITELIST: str = Field(default="", description="管理端 IP 白名单（逗号分隔，空=不限制）")
    AUDIT_LOG_RETENTION_DAYS: int = Field(default=90, description="审计日志保留天数")

    # ---------------------------------------------------------------
    # 一体化公开接口配置
    # ---------------------------------------------------------------
    PUBLIC_KB_ID: str | None = Field(
        default=None,
        description="公开一体化接口默认知识库ID（需预先配置好抽取配置：Schema/Prompt/术语集/LLM端点）",
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
