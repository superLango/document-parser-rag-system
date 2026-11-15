"""Shared contract test referenced by every recipe manifest (P1-08 一版一测试)."""

from __future__ import annotations

from pathlib import Path

from services.recipe_registry.package import RecipeManifest, load_package

RECIPES = Path(__file__).resolve().parents[3] / "services" / "recipe_registry" / "data" / "recipes"


def _manifests() -> list[Path]:
    return sorted(RECIPES.glob("*/*/manifest.json"))


def test_recipe_manifest_contract() -> None:
    """Every published recipe version loads, matches its directory and has a test."""
    paths = _manifests()
    assert paths, f"no recipe manifests under {RECIPES}"
    errors: list[str] = []
    for path in paths:
        relative = path.parent.relative_to(RECIPES)
        try:
            manifest: RecipeManifest = load_package(path.parent)
        except Exception as exc:  # noqa: BLE001 - report every broken package
            errors.append(f"{relative}: load failed: {exc}")
            continue
        if manifest.recipe_id != path.parent.parent.name:
            errors.append(f"{relative}: recipe_id mismatch {manifest.recipe_id}")
        if manifest.version != path.parent.name:
            errors.append(f"{relative}: version mismatch {manifest.version}")
        if not manifest.tests:
            errors.append(f"{relative}: tests is empty")
    assert not errors, "\n".join(errors[:20])
