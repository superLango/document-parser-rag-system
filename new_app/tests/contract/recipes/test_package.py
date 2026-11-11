"""Recipe package manifest validation and digest immutability."""

import pytest

from services.recipe_registry.package import (
    RecipeManifest,
    RecipePackageError,
    build_package,
    compute_digest,
    validate_manifest,
)


def _manifest(**overrides) -> dict:
    payload = {
        "schema_version": "2.0",
        "recipe_id": "mechanical_properties_v1",
        "version": "1.0.0",
        "engine_api": "recipe-engine/1",
        "profile": "mechanical_properties",
        "signature": {"profile": "mechanical_properties", "n_cols": 9, "tokens": ["牌号"]},
        "bindings": {"row_key": ["牌号"]},
    }
    payload.update(overrides)
    return payload


def test_build_package_fills_checksum() -> None:
    manifest = build_package(_manifest())
    assert manifest.checksum
    assert manifest.checksum == compute_digest(manifest)


def test_digest_changes_when_content_changes() -> None:
    first = build_package(_manifest())
    second = build_package(_manifest(profile="chemical_composition"))
    assert first.checksum != second.checksum


def test_invalid_recipe_id_rejected() -> None:
    with pytest.raises(RecipePackageError) as exc:
        build_package(_manifest(recipe_id="Bad-Id"))
    assert exc.value.code == "RECIPE_ID_INVALID"


def test_invalid_version_rejected() -> None:
    with pytest.raises(RecipePackageError) as exc:
        build_package(_manifest(version="1"))
    assert exc.value.code == "RECIPE_VERSION_INVALID"


def test_incompatible_engine_rejected() -> None:
    with pytest.raises(RecipePackageError) as exc:
        build_package(_manifest(engine_api="recipe-engine/0"))
    assert exc.value.code == "RECIPE_ENGINE_INCOMPATIBLE"


def test_checksum_mismatch_rejected() -> None:
    payload = _manifest(checksum="deadbeef")
    with pytest.raises(RecipePackageError) as exc:
        build_package(payload)
    assert exc.value.code == "RECIPE_CHECKSUM_MISMATCH"


def test_validate_is_idempotent() -> None:
    manifest = validate_manifest(RecipeManifest.model_validate(_manifest()))
    again = validate_manifest(manifest)
    assert again.checksum == manifest.checksum
