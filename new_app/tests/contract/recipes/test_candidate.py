from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from services.recipe_registry.candidate import CandidateError, apply_patch, build_candidate
from services.recipe_registry.package import load_package
from services.recipe_registry.registry import DEFAULT_ROOT, RecipeRegistry

RECIPE_ID = "mechanical_properties_v1"
BASE_VERSION = "1.0.0"


def _registry(tmp_path: Path) -> RecipeRegistry:
    root = tmp_path / "recipes"
    target = root / RECIPE_ID / BASE_VERSION
    target.mkdir(parents=True)
    shutil.copy(DEFAULT_ROOT / RECIPE_ID / BASE_VERSION / "manifest.json", target / "manifest.json")
    (root / "registry.json").write_text(
        json.dumps(
            {
                "channels": {
                    "stable": {RECIPE_ID: BASE_VERSION},
                    "candidate": {},
                    "shadow": {},
                    "deprecated": {},
                },
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    return RecipeRegistry(root)


def _patch() -> list[dict]:
    return [
        {
            "op": "add",
            "path": "/bindings/measures/Z",
            "value": {"unit": "%", "family": "tensile"},
        },
        {"op": "add", "path": "/signature/tokens/-", "value": "断面收缩率"},
    ]


def test_build_candidate_preserves_stable(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    ref = build_candidate(
        registry,
        RECIPE_ID,
        BASE_VERSION,
        "1.1.0",
        _patch(),
        actor="operator",
        note="M6 test",
    )
    assert ref.version == "1.1.0"
    assert ref.channel == "candidate"
    assert registry.channels_for(RECIPE_ID)["stable"] == BASE_VERSION
    assert registry.channels_for(RECIPE_ID)["candidate"] == "1.1.0"
    candidate = registry.get(RECIPE_ID, "1.1.0")
    assert candidate.bindings["measures"]["Z"] == {"unit": "%", "family": "tensile"}
    assert "断面收缩率" in candidate.signature.tokens
    assert candidate.checksum


def test_discard_candidate_keeps_stable(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    build_candidate(
        registry,
        RECIPE_ID,
        BASE_VERSION,
        "1.1.0",
        _patch(),
        actor="operator",
    )
    result = registry.discard(RECIPE_ID, "1.1.0", actor="operator", reason="reject")
    assert result.channel is None
    assert registry.channels_for(RECIPE_ID)["stable"] == BASE_VERSION
    assert "candidate" not in registry.channels_for(RECIPE_ID)


def test_forbidden_patch_root(tmp_path: Path) -> None:
    manifest = load_package(DEFAULT_ROOT / RECIPE_ID / BASE_VERSION)
    with pytest.raises(CandidateError) as exc:
        apply_patch(
            manifest,
            [{"op": "replace", "path": "/engine_api", "value": "other"}],
            "1.1.0",
        )
    assert exc.value.code == "CANDIDATE_PATCH_FORBIDDEN"


def test_candidate_version_must_increase(tmp_path: Path) -> None:
    manifest = load_package(DEFAULT_ROOT / RECIPE_ID / BASE_VERSION)
    with pytest.raises(CandidateError) as exc:
        apply_patch(manifest, _patch(), BASE_VERSION)
    assert exc.value.code == "CANDIDATE_VERSION_INVALID"
