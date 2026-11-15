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
    # 仅 dev 环境生效的开发期延迟/故障注入。
    environment: str = "dev"
    mock_stage_delay_seconds: float = 0.2
    stage_max_attempts: int = 2
    stage_retry_backoff_seconds: float = 0.5
    # 开发期故障注入，仅用于验证阶段重试；接入真实实现后移除。
    mock_fail_stage: str = ""
    mock_fail_times: int = 0
    ocr_url: str = "http://localhost:18002"
    ocr_backend: str = "auto"
    ocr_timeout_seconds: float = 900.0
    # 表级质量低于该值的表不进入配方匹配（0 表示不启用）。
    min_table_quality: float = 0.25
    # 回滚开关：置 true 时 OCR 阶段回到 M1 的 fake 实现。
    ocr_use_fake: bool = False
    recipe_registry_url: str = "http://localhost:18005"
    # 回滚开关：置 true 时路由阶段回到 M1 的 fake 实现。
    route_use_fake: bool = False
    # 低置信表是否调用 RouterAgent；只处理高质量性能/成分表，其余转人工。
    route_agent_enabled: bool = True
    # top1-top2 低于该值时转人工复核（0 表示不启用，仅记录 margin）。
    route_margin_threshold: float = 0.0
    sandbox_url: str = "http://localhost:18004"
    sandbox_timeout_seconds: float = 300.0
    sandbox_run_timeout_seconds: int = 120
    sandbox_cpu: float = 1.0
    sandbox_memory_mb: int = 512
    sandbox_pids: int = 128
    sandbox_template_id: str = "product_full"
    sandbox_template_version: str = "1.0.0"
    sandbox_engine_image: str = "hanson-sandbox-runtime:local"
    sandbox_engine_version: str = "sandbox-engine/1"
    parser_asset_id: str = "parser_core"
    # 回滚开关：置 true 时沙箱阶段回到 M1 的 fake 实现。
    sandbox_use_fake: bool = False
    review_url: str = "http://localhost:18006"
    review_timeout_seconds: float = 300.0
    # 回滚开关：置 true 时 review 阶段回到 M1 的 fake 实现。
    review_use_fake: bool = False
    # 人工审核门：REVIEW_PASSED 后必须经 HUMAN_REVIEW 才能进入 STRUCTURED_READY。
    human_review_required: bool = True
    # review 失败后自动触发 feedback 修复并重跑沙箱的有界循环。
    # 默认关闭：反馈只进入问题台账，不在创建时自动处理/重跑。
    auto_repair_enabled: bool = False
    auto_repair_max_attempts: int = 2
    # P1-01: DOC-* 反馈自动处理预算；超预算转人工，不再消耗模型额度。
    auto_feedback_enabled: bool = False
    auto_feedback_max_items: int = 3
    auto_feedback_token_budget: int = 64000
    auto_feedback_wall_time_seconds: float = 300.0
    # P1-07: 表格解析引擎独立灰度开关（与配方/OCR 回滚开关互不影响）。
    table_engine: str = "stable"  # stable | candidate
    table_engine_canary_percent: int = 0  # 0-100；生产灰度从 10 开始
    table_engine_auto_rollback: bool = True
    # P1-12/Phase 2: 版本画像与漂移自适应（默认关闭，验收后开启）。
    edition_profile_enabled: bool = False
    edition_profile_dir: str = ""
    # L3 代码补丁审批令牌；为空时审批端点直接拒绝（fail closed）。
    internal_api_token: str = ""
    agent_url: str = "http://localhost:18003"
    feedback_timeout_seconds: float = 300.0
    # P2: deterministic coverage too low -> ask the agent for prose-only items.
    model_fallback_enabled: bool = False
    model_fallback_max_items: int = 5
    model_fallback_token_budget: int = 32000
    model_fallback_timeout_seconds: float = 120.0
    # 跨标准抽取：检测被引标准的要求并在本地标准库中补全。
    cross_standard_enabled: bool = True
    cross_standard_max_tasks: int = 12
    cross_standard_max_sources: int = 3
    cross_standard_agent_enabled: bool = True
    cross_standard_agent_max_items: int = 8
    cross_standard_agent_timeout_seconds: float = 120.0
    # shadow 灰度：连续多少份文档双跑无回退后视为通过。
    shadow_required_documents: int = 10
    # 方案 B：满额后默认停在 ready 等人工二次确认；显式开启才自动晋升。
    shadow_auto_promote: bool = False
    # 批次超时（秒）；0 表示不超时。超时后置 expired，反馈回到 verified。
    shadow_timeout_seconds: int = 604800

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @property
    def simulation_mode(self) -> bool:
        return any(
            (
                self.ocr_use_fake,
                self.route_use_fake,
                self.sandbox_use_fake,
                self.review_use_fake,
            )
        )

    def storage_config(self) -> StorageConfig:
        return StorageConfig(
            endpoint=self.object_storage_endpoint,
            bucket=self.object_storage_bucket,
            access_key=self.object_storage_access_key,
            secret_key=self.object_storage_secret_key,
            local_dir=self.local_storage_dir,
        )


settings = Settings()
