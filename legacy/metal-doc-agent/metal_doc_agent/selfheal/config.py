"""Self-heal runtime settings (env driven, default off)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


OCR_BACKEND_ALIASES = {"glm-ocr": "glm", "glm_ocr": "glm"}


def normalize_ocr_backend(value: str | None) -> str:
    """Map a trace adapter name (``glm-ocr``) to a Settings backend key."""

    text = str(value or "mock").strip().lower()
    return OCR_BACKEND_ALIASES.get(text, text)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SelfHealSettings:
    enabled: bool
    root: Path
    db_path: Path
    project_root: Path
    repo_root: Path
    data_dir: Path
    model_base_url: str | None
    model_name: str
    model_timeout: float
    code_agent: bool
    auto_merge: bool
    auto_learn: bool
    test_command: str
    max_iterations: int
    max_audit_tables: int
    max_audit_records: int
    regression_runs: Path | None

    @property
    def jobs_root(self) -> Path:
        return self.root / "jobs"

    @property
    def overlays_root(self) -> Path:
        return self.root / "overlays"

    @property
    def patches_root(self) -> Path:
        return self.root / "patches"

    def ensure_dirs(self) -> None:
        for path in (self.root, self.jobs_root, self.overlays_root, self.patches_root):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, project_root: str | Path | None = None) -> "SelfHealSettings":
        root_project = Path(
            project_root
            or os.environ.get("METAL_DOC_HOME")
            or Path(__file__).resolve().parents[2]
        )
        data_dir = Path(os.environ.get("METAL_DOC_DATA", root_project / "data"))
        root = Path(os.environ.get("SELFHEAL_ROOT", data_dir / "selfheal"))
        db_path = Path(os.environ.get("SELFHEAL_DB", root / "selfheal.db"))
        regression = os.environ.get("SELFHEAL_REGRESSION_RUNS")
        return cls(
            enabled=_env_bool("SELFHEAL_ENABLED", False),
            root=root,
            db_path=db_path,
            project_root=root_project,
            repo_root=Path(os.environ.get("SELFHEAL_REPO_ROOT", root_project)),
            data_dir=data_dir,
            model_base_url=(
                os.environ.get("SELFHEAL_MODEL_URL")
                or os.environ.get("QWEN_BASE_URL")
            ),
            model_name=(
                os.environ.get("SELFHEAL_MODEL")
                or os.environ.get("QWEN_MODEL")
                or "Qwen3.6-35B-A3B-NVFP4"
            ),
            model_timeout=float(os.environ.get("SELFHEAL_MODEL_TIMEOUT", "300")),
            code_agent=_env_bool("SELFHEAL_CODE_AGENT", True),
            auto_merge=_env_bool("SELFHEAL_AUTO_MERGE", True),
            auto_learn=_env_bool("SELFHEAL_AUTO_LEARN", True),
            test_command=os.environ.get(
                "SELFHEAL_TEST_COMMAND",
                "python -m pytest -q tests/test_selfheal_agent.py "
                "tests/test_selfheal_pipeline.py tests/test_selfheal_l2_l3.py",
            ),
            max_iterations=int(os.environ.get("SELFHEAL_MAX_ITERATIONS", "3")),
            max_audit_tables=int(os.environ.get("SELFHEAL_MAX_AUDIT_TABLES", "20")),
            max_audit_records=int(os.environ.get("SELFHEAL_MAX_AUDIT_RECORDS", "200")),
            regression_runs=Path(regression) if regression else None,
        )
