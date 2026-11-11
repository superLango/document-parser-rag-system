from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .model_gateway import ModelEndpoint


class Settings(BaseSettings):
    model: str = "Qwen3.6-35B-A3B-NVFP4"
    base_url_primary: str = ""
    base_url_secondary: str = ""
    base_url_tertiary: str = "http://192.168.1.35:9988"
    failover_seconds: float = 10.0
    cooldown_seconds: float = 30.0
    timeout_seconds: float = 300.0
    context_window: int = 65536
    max_output_tokens: int = 4096
    tokenizer_mode: str = "remote"
    session_db: Path = Path("/tmp/hanson-agent/sessions.db")
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"
    max_steps: int = 24
    max_tool_calls: int = 32
    wall_time_seconds: float = 300.0
    tools_max_result_chars: int = 4000
    watchdog_floor_mb: int = 4096
    api_key: str = ""
    enable_thinking: bool = False

    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_file=".env", extra="ignore"
    )

    def endpoints(self) -> tuple[ModelEndpoint, ...]:
        items = (
            ("primary", self.base_url_primary),
            ("secondary", self.base_url_secondary),
            ("tertiary", self.base_url_tertiary),
        )
        endpoints = tuple(
            ModelEndpoint(name=name, base_url=url.strip())
            for name, url in items
            if url and url.strip()
        )
        if endpoints:
            return endpoints
        return (ModelEndpoint(name="tertiary", base_url="http://192.168.1.35:9988"),)


settings = Settings()
