"""PP-DocLayoutV3 官方版/V1/V2 模型配置兼容性测试。"""

import hashlib
import os
import stat
import subprocess
from pathlib import Path

import pytest
from app.core.config import settings
from app.services.parsekit import ParseOptions
from app.services.parsekit.errors import LayoutModelUnavailable
from app.services.parsekit.layout_ppdoc import (
    DEFAULT_MODEL_VARIANT,
    EXPECTED_SHA256,
    MODEL_SHA256_BY_VARIANT,
    PPDocLayoutEngine,
)

MODEL_DIR_BY_VARIANT = {
    "official": "pp_doclayoutv3",
    "v1": "pp_doclayoutv3_finetuned_v1",
    "v2": "pp_doclayoutv3_finetuned_v2",
}


def test_finetuned_v2_model_is_runtime_default() -> None:
    project_root = Path(__file__).resolve().parents[2]
    expected = project_root / "models" / "pp_doclayoutv3_finetuned_v2"

    assert DEFAULT_MODEL_VARIANT == "v2"
    assert EXPECTED_SHA256 == MODEL_SHA256_BY_VARIANT["v2"]
    assert Path(settings.PARSEKIT_LAYOUT_MODEL_DIR) == expected
    assert Path(ParseOptions.from_settings().layout_model_dir) == expected


@pytest.mark.parametrize("variant", ["official", "v1", "v2"])
def test_supported_layout_model_hashes_are_locked(variant: str) -> None:
    project_root = Path(__file__).resolve().parents[2]
    model_dir = project_root / "models" / MODEL_DIR_BY_VARIANT[variant]
    weight = model_dir / "model.safetensors"

    assert weight.is_file()
    digest = hashlib.sha256(weight.read_bytes()).hexdigest()
    assert digest == MODEL_SHA256_BY_VARIANT[variant]
    engine = PPDocLayoutEngine(model_dir, device="cpu")
    assert engine.model_variant == variant


def test_unknown_layout_model_hash_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "model.safetensors").write_bytes(b"unknown-layout-model")

    with pytest.raises(LayoutModelUnavailable, match="仅支持"):
        PPDocLayoutEngine(tmp_path, device="cpu")


@pytest.mark.parametrize("variant", ["official", "v1", "v2"])
def test_layout_model_selector_updates_only_target_setting(
    tmp_path: Path,
    variant: str,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    fake_backend = tmp_path / "backend"
    fake_models = tmp_path / "models"
    fake_backend.mkdir()
    fake_models.mkdir()
    env_file = fake_backend / ".env"
    env_file.write_text(
        "SECRET_KEY=keep-me\n"
        "PARSEKIT_LAYOUT_MODEL_DIR=/old/model\n"
        "OTHER_SETTING=keep-me-too\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    model_dir_name = MODEL_DIR_BY_VARIANT[variant]
    (fake_models / model_dir_name).symlink_to(
        project_root / "models" / model_dir_name,
        target_is_directory=True,
    )

    result = subprocess.run(
        ["bash", str(project_root / "scripts" / "select_layout_model.sh"), variant],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HANSONDOC_PROJECT_ROOT": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "SECRET_KEY=keep-me",
        f"PARSEKIT_LAYOUT_MODEL_DIR={fake_models / model_dir_name}",
        "OTHER_SETTING=keep-me-too",
    ]
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert not list(fake_backend.glob(".env.layout-model.*"))


def test_layout_threshold_matches_xanylabeling_default() -> None:
    assert settings.PARSEKIT_LAYOUT_CONF_THRESHOLD == 0.5
    assert ParseOptions().layout_conf_threshold == 0.5
    assert ParseOptions.from_settings().layout_conf_threshold == 0.5


@pytest.mark.parametrize(
    ("model_label", "block_type"),
    [
        ("display_formula", "formula"),
        ("inline_formula", "formula"),
        ("vertical_text", "text"),
        ("header_image", None),
        ("footer_image", None),
    ],
)
def test_finetuned_model_labels_are_mapped(
    model_label: str,
    block_type: str | None,
) -> None:
    assert PPDocLayoutEngine.LABEL_MAP[model_label] == block_type
