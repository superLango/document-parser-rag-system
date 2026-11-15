from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    agent_url: str = "http://localhost:18003"
    use_agent: bool = True
    agent_timeout_seconds: float = 300.0
    ruleset_version: str = "m6"
    # 文档级门禁阈值（P2）。
    doc_min_pages: int = 3
    doc_unbound_ratio: float = 0.3
    doc_dup_key_limit: int = 3
    doc_unit_missing_ratio: float = 0.5
    doc_unit_min_samples: int = 5
    doc_low_coverage_ratio: float = 0.5
    doc_min_tables: int = 2

    model_config = SettingsConfigDict(
        env_prefix="REVIEW_", env_file=".env", extra="ignore"
    )


settings = Settings()
