"""微调 PP-DocLayoutV3 模型配置兼容性测试。"""

from pathlib import Path

import pytest
from app.core.config import settings
from app.services.parsekit import ParseOptions
from app.services.parsekit.layout_ppdoc import PPDocLayoutEngine


def test_finetuned_model_is_runtime_default() -> None:
    project_root = Path(__file__).resolve().parents[2]
    expected = project_root / "models" / "pp_doclayoutv3_finetuned_v1"

    assert Path(settings.PARSEKIT_LAYOUT_MODEL_DIR) == expected
    assert Path(ParseOptions.from_settings().layout_model_dir) == expected


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
