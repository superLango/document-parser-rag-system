"""Registry publish/resolve/promote/rollback/deprecate on a temp directory."""

import pytest

from services.recipe_registry.package import build_package
from services.recipe_registry.registry import RecipeRegistry, RegistryError


def _manifest(version: str = "1.0.0", profile: str = "mechanical_properties") -> dict:
    return build_package(
        {
            "recipe_id": "mechanical_properties_v1",
            "version": version,
            "profile": profile,
            "signature": {"profile": profile, "n_cols": 9},
        }
    )


def test_publish_and_list(tmp_path) -> None:
    registry = RecipeRegistry(tmp_path)
    ref = registry.publish(_manifest())
    assert ref.version == "1.0.0"
    assert ref.digest
    versions = registry.list_versions("mechanical_properties_v1")
    assert [item.version for item in versions] == ["1.0.0"]
    assert registry.list_recipes()[0]["recipe_id"] == "mechanical_properties_v1"


def test_same_version_different_content_rejected(tmp_path) -> None:
    registry = RecipeRegistry(tmp_path)
    registry.publish(_manifest())
    with pytest.raises(RegistryError) as exc:
        registry.publish(_manifest(profile="chemical_composition"))
    assert exc.value.code == "RECIPE_VERSION_IMMUTABLE"


def test_same_version_same_content_is_idempotent(tmp_path) -> None:
    registry = RecipeRegistry(tmp_path)
    first = registry.publish(_manifest())
    second = registry.publish(_manifest())
    assert first.digest == second.digest


def test_promote_and_resolve(tmp_path) -> None:
    registry = RecipeRegistry(tmp_path)
    registry.publish(_manifest())
    registry.promote(
        "mechanical_properties_v1", "1.0.0", "stable", actor="qa", note="initial"
    )
    resolved = registry.resolve("mechanical_properties_v1", "stable")
    assert resolved.version == "1.0.0"
    assert resolved.channel == "stable"


def test_rollback_returns_previous_version(tmp_path) -> None:
    registry = RecipeRegistry(tmp_path)
    registry.publish(_manifest("1.0.0"))
    registry.publish(_manifest("1.1.0", profile="mechanical_properties"))
    registry.promote("mechanical_properties_v1", "1.0.0", "stable", actor="qa")
    registry.promote("mechanical_properties_v1", "1.1.0", "stable", actor="qa")
    rolled = registry.rollback("mechanical_properties_v1", "stable", actor="qa")
    assert rolled.version == "1.0.0"
    assert registry.resolve("mechanical_properties_v1", "stable").version == "1.0.0"


def test_deprecate_moves_pointer(tmp_path) -> None:
    registry = RecipeRegistry(tmp_path)
    registry.publish(_manifest())
    registry.promote("mechanical_properties_v1", "1.0.0", "stable", actor="qa")
    ref = registry.deprecate(
        "mechanical_properties_v1", "1.0.0", actor="qa", reason="superseded"
    )
    assert ref.channel == "deprecated"
    with pytest.raises(RegistryError) as exc:
        registry.resolve("mechanical_properties_v1", "stable")
    assert exc.value.code == "RECIPE_NOT_RESOLVED"


def test_resolve_unknown_channel(tmp_path) -> None:
    registry = RecipeRegistry(tmp_path)
    with pytest.raises(RegistryError) as exc:
        registry.resolve("mechanical_properties_v1", "production")
    assert exc.value.code == "RECIPE_CHANNEL_INVALID"
