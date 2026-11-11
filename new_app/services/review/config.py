from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    agent_url: str = "http://localhost:18003"
    use_agent: bool = True
    agent_timeout_seconds: float = 300.0
    ruleset_version: str = "m5"

    model_config = SettingsConfigDict(
        env_prefix="REVIEW_", env_file=".env", extra="ignore"
    )


settings = Settings()
