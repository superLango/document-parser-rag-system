"""Production startup checks (fail fast instead of silently degrading)."""

from __future__ import annotations

from metal_doc_agent.settings import Settings

from .config import PlatformSettings

PLACEHOLDER_SECRETS = {
    "change-me",
    "change-me-in-production",
    "test-secret",
    "test-secret-key",
    "e2e-secret",
}


def startup_issues(
    settings: PlatformSettings, engine_settings: Settings
) -> list[str]:
    """Return blocking issues for a production deployment (empty means ok)."""

    if not settings.production:
        return []

    issues: list[str] = []
    if len(settings.secret_key) < 32 or settings.secret_key in PLACEHOLDER_SECRETS:
        issues.append(
            "HANSON_SECRET_KEY must be a non-placeholder secret of at least 32 characters"
        )
    if not settings.database_url.startswith("postgresql"):
        issues.append(
            "production requires PostgreSQL (set HANSON_DATABASE_URL=postgresql+psycopg://...)"
        )
    if settings.db_auto_create:
        issues.append(
            "production must not create tables automatically; run alembic upgrade head "
            "and set HANSON_DB_AUTO_CREATE=false"
        )
    if settings.inline_jobs:
        issues.append(
            "production must run parsing in workers; set HANSON_INLINE_JOBS=false"
        )
    if engine_settings.ocr_backend == "mock":
        issues.append("production must not use the mock OCR backend (set METAL_DOC_OCR=glm)")
    elif engine_settings.ocr_backend == "glm":
        if not engine_settings.glm_ocr_base_url:
            issues.append("GLM_OCR_BASE_URL is required when METAL_DOC_OCR=glm")
        if not engine_settings.layout_service_url:
            issues.append(
                "LAYOUT_SERVICE_URL is required for PDF parsing when METAL_DOC_OCR=glm"
            )
    if engine_settings.extractor_backend == "mock":
        issues.append(
            "production must not use the mock extractor (set METAL_DOC_EXTRACTOR=qwen)"
        )
    elif engine_settings.extractor_backend == "qwen" and not engine_settings.qwen_base_url:
        issues.append("QWEN_BASE_URL is required when METAL_DOC_EXTRACTOR=qwen")
    if (
        engine_settings.extractor_prompt_style == "sft_m2"
        and not engine_settings.sft_base_url
    ):
        issues.append("SFT_BASE_URL is required when METAL_DOC_EXTRACTOR_PROMPT=sft_m2")
    if not engine_settings.project_root.exists():
        issues.append(
            f"engine root does not exist: {engine_settings.project_root}"
        )
    return issues


def validate_startup(
    settings: PlatformSettings, engine_settings: Settings
) -> None:
    issues = startup_issues(settings, engine_settings)
    if issues:
        lines = "\n".join(f" - {issue}" for issue in issues)
        raise RuntimeError(f"production startup checks failed:\n{lines}")
