"""Runtime settings.

No model endpoint is required for the framework demo. The default backends are
mock; real GLM-OCR / Qwen adapters read the same environment variables later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    ocr_backend: str
    extractor_backend: str
    glm_ocr_base_url: str | None
    glm_ocr_model: str
    qwen_base_url: str | None
    qwen_model: str
    api_key: str | None
    request_timeout: float
    ocr_dpi: int = 200
    glm_ocr_fallback_base_url: str | None = None
    qwen_fallback_base_url: str | None = None
    sft_fallback_base_url: str | None = None
    model_failover_probe_seconds: float = 60.0
    layout_service_url: str | None = None
    layout_service_fallback_url: str | None = None
    layout_service_fallback_urls: tuple[str, ...] = ()
    layout_timeout_seconds: float = 60.0
    layout_service_token: str | None = None
    model_retries: int = 2
    glm_ocr_max_tokens: int = 4096
    glm_ocr_stream: bool = True
    glm_ocr_timeout: float = 90.0
    qwen_max_tokens: int = 4096
    qwen_stream: bool = True
    qwen_concurrency: int = 4
    ocr_page_concurrency: int = 4
    ocr_block_concurrency: int = 8
    ocr_max_inflight: int = 16
    ocr_table_inflight: int = 2
    extractor_prompt_style: str = "native"
    sft_max_tokens: int = 512
    sft_row_limit: int = 30
    sft_rules_first: bool = False
    sft_base_url: str | None = None
    sft_model: str = "Qwen3.5-9B-adapter-v2"
    glm_ocr_max_edge: int = 2048
    glm_ocr_min_edge: int = 32
    qwen_enable_thinking: bool = False
    business_dictionary_path: str = "configs/business_dictionary.hanson.json"
    business_dictionary_override_path: str | None = (
        "configs/business_dictionary.local.json"
    )
    business_alignment: bool = True
    dictionary_category_mode: str = "advisory"
    recipe_routing: bool = False
    orchestrate: bool = False
    sandbox: bool = True
    sandbox_timeout: float = 0.0
    tool_timeout_seconds: float = 900.0

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.environ.get("METAL_DOC_HOME", Path(__file__).resolve().parents[1]))
        data_dir = Path(os.environ.get("METAL_DOC_DATA", root / "data"))
        return cls(
            project_root=root,
            data_dir=data_dir,
            ocr_backend=os.environ.get("METAL_DOC_OCR", "mock").strip().lower(),
            extractor_backend=os.environ.get("METAL_DOC_EXTRACTOR", "mock").strip().lower(),
            glm_ocr_base_url=os.environ.get("GLM_OCR_BASE_URL"),
            glm_ocr_model=os.environ.get("GLM_OCR_MODEL", "GLM-OCR"),
            qwen_base_url=os.environ.get("QWEN_BASE_URL"),
            qwen_model=os.environ.get("QWEN_MODEL", "Qwen3.5-9B"),
            api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("MODEL_API_KEY"),
            request_timeout=float(os.environ.get("MODEL_TIMEOUT", "120")),
            ocr_dpi=int(os.environ.get("OCR_DPI", "200")),
            glm_ocr_fallback_base_url=os.environ.get(
                "GLM_OCR_FALLBACK_BASE_URL"
            ),
            qwen_fallback_base_url=os.environ.get("QWEN_FALLBACK_BASE_URL"),
            sft_fallback_base_url=os.environ.get("SFT_FALLBACK_BASE_URL"),
            model_failover_probe_seconds=float(
                os.environ.get("MODEL_FAILOVER_PROBE_SECONDS", "60")
            ),
            layout_service_url=os.environ.get("LAYOUT_SERVICE_URL"),
            layout_service_fallback_url=os.environ.get("LAYOUT_SERVICE_FALLBACK_URL"),
            layout_service_fallback_urls=_env_urls(
                os.environ.get("LAYOUT_SERVICE_FALLBACK_URLS")
            ),
            layout_timeout_seconds=float(
                os.environ.get("LAYOUT_TIMEOUT", "60")
            ),
            layout_service_token=os.environ.get("LAYOUT_SERVICE_TOKEN"),
            model_retries=int(os.environ.get("MODEL_RETRIES", "2")),
            glm_ocr_max_tokens=int(os.environ.get("GLM_OCR_MAX_TOKENS", "4096")),
            glm_ocr_stream=_env_bool("GLM_OCR_STREAM", True),
            glm_ocr_timeout=float(os.environ.get("GLM_OCR_TIMEOUT", "90")),
            qwen_max_tokens=int(os.environ.get("QWEN_MAX_TOKENS", "4096")),
            qwen_stream=_env_bool("QWEN_STREAM", True),
            qwen_concurrency=int(os.environ.get("QWEN_CONCURRENCY", "4")),
            ocr_page_concurrency=int(
                os.environ.get("OCR_PAGE_CONCURRENCY", "4")
            ),
            ocr_block_concurrency=int(
                os.environ.get("OCR_BLOCK_CONCURRENCY", "8")
            ),
            ocr_max_inflight=int(os.environ.get("OCR_MAX_INFLIGHT", "16")),
            ocr_table_inflight=int(os.environ.get("OCR_TABLE_INFLIGHT", "2")),
            extractor_prompt_style=os.environ.get(
                "METAL_DOC_EXTRACTOR_PROMPT", "native"
            )
            .strip()
            .lower(),
            sft_max_tokens=int(os.environ.get("METAL_DOC_SFT_MAX_TOKENS", "512")),
            sft_row_limit=int(os.environ.get("METAL_DOC_SFT_ROW_LIMIT", "30")),
            sft_rules_first=_env_bool("METAL_DOC_SFT_RULES_FIRST", False),
            sft_base_url=os.environ.get("SFT_BASE_URL"),
            sft_model=os.environ.get("SFT_MODEL", "Qwen3.5-9B-adapter-v2"),
            glm_ocr_max_edge=int(os.environ.get("GLM_OCR_MAX_EDGE", "2048")),
            glm_ocr_min_edge=int(os.environ.get("GLM_OCR_MIN_EDGE", "32")),
            qwen_enable_thinking=_env_bool("QWEN_ENABLE_THINKING", False),
            business_dictionary_path=os.environ.get(
                "BUSINESS_DICTIONARY_SNAPSHOT",
                "configs/business_dictionary.hanson.json",
            ),
            business_dictionary_override_path=(
                os.environ.get(
                    "BUSINESS_DICTIONARY_OVERRIDE",
                    "configs/business_dictionary.local.json",
                )
                or None
            ),
            business_alignment=_env_bool("METAL_DOC_ALIGNMENT", True),
            dictionary_category_mode=os.environ.get(
                "METAL_DOC_DICTIONARY_CATEGORY_MODE", "advisory"
            )
            .strip()
            .lower(),
            recipe_routing=_env_bool("METAL_DOC_RECIPE_ROUTING", False),
            orchestrate=_env_bool("METAL_DOC_ORCHESTRATE", False),
            # Each job runs in a fresh interpreter so patched rule code is used
            # without restarting the worker; set 0 to run in-process.
            sandbox=_env_bool("METAL_DOC_SANDBOX", True),
            sandbox_timeout=float(os.environ.get("METAL_DOC_SANDBOX_TIMEOUT", "0")),
            tool_timeout_seconds=float(
                os.environ.get("METAL_DOC_TOOL_TIMEOUT", "900")
            ),
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_urls(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated URL list, preserving order and dropping blanks."""

    if not value:
        return ()
    return tuple(
        item.strip().rstrip("/") for item in value.split(",") if item.strip()
    )
