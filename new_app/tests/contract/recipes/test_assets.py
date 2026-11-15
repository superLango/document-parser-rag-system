from __future__ import annotations

import pytest

from services.recipe_registry.assets import (
    AssetError,
    AssetFile,
    AssetManifest,
    AssetRegistry,
)

FILES = {"builtin.py": b"print('v1')\n"}


def _manifest(version: str = "1.0.0") -> AssetManifest:
    return AssetManifest(
        kind="parser",
        asset_id="parser_core",
        version=version,
        entry_modules=["builtin"],
    )


def _registry(root) -> AssetRegistry:
    return AssetRegistry(root)


def test_publish_resolve_promote_rollback(tmp_path) -> None:
    registry = _registry(tmp_path)
    ref = registry.publish(_manifest(), dict(FILES))
    assert ref.digest
    registry.promote("parser", "parser_core", "1.0.0", "stable", actor="test")
    assert registry.resolve("parser", "parser_core").version == "1.0.0"

    registry.publish(_manifest("1.0.1"), {"builtin.py": b"print('v2')\n"})
    registry.promote("parser", "parser_core", "1.0.1", "stable", actor="test")
    assert registry.resolve("parser", "parser_core").version == "1.0.1"

    ref = registry.rollback("parser", "parser_core", "stable", actor="test")
    assert ref.version == "1.0.0"
    assert registry.resolve("parser", "parser_core").version == "1.0.0"


def test_version_is_immutable(tmp_path) -> None:
    registry = _registry(tmp_path)
    registry.publish(_manifest(), dict(FILES))
    with pytest.raises(AssetError) as exc:
        registry.publish(_manifest(), {"builtin.py": b"print('changed')\n"})
    assert exc.value.code == "ASSET_VERSION_IMMUTABLE"


def test_rejects_path_escape(tmp_path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(AssetError):
        registry.publish(_manifest(), {"../evil.py": b"x"})


def test_rejects_unsupported_suffix(tmp_path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(AssetError):
        registry.publish(_manifest(), {"payload.bin": b"x"})


def test_rejects_declared_digest_mismatch(tmp_path) -> None:
    registry = _registry(tmp_path)
    manifest = _manifest()
    manifest.files = [AssetFile(path="builtin.py", sha256="0" * 64)]
    with pytest.raises(AssetError) as exc:
        registry.publish(manifest, dict(FILES))
    assert exc.value.code == "ASSET_FILE_DIGEST_MISMATCH"
