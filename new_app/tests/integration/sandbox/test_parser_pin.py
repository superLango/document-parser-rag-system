from __future__ import annotations

import hashlib
import io
import json

import pytest
from hanson_contracts import ParserAssetRef

from services.recipe_registry.assets import AssetFile, AssetManifest, compute_checksum
from services.sandbox import workspace as workspace_module
from services.sandbox.config import Settings

BUNDLE = b"PARSER_REVISION = 'test'\n"


def _detail() -> dict:
    manifest = AssetManifest(
        kind="parser",
        asset_id="parser_core",
        version="9.9.9",
        files=[AssetFile(path="builtin.py", sha256=hashlib.sha256(BUNDLE).hexdigest())],
    )
    manifest.checksum = compute_checksum(manifest, {"builtin.py": BUNDLE})
    return {
        "manifest": manifest.model_dump(mode="json"),
        "files": {"builtin.py": BUNDLE.decode("utf-8")},
    }


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    detail = _detail()

    def fake_urlopen(request, timeout=5):  # noqa: ANN001, ARG001
        calls.append(request if isinstance(request, str) else request.full_url)
        return io.BytesIO(json.dumps(detail).encode("utf-8"))

    monkeypatch.setattr(workspace_module.urllib.request, "urlopen", fake_urlopen)


def test_pinned_parser_version_bypasses_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_urlopen(monkeypatch, calls)
    settings = Settings(recipe_registry_url="http://registry:8005")
    metadata, files = workspace_module._fetch_parser_asset(
        settings, ParserAssetRef(version="9.9.9")
    )
    assert metadata["version"] == "9.9.9"
    assert metadata["pinned"] is True
    assert files["builtin.py"] == BUNDLE
    assert calls == [
        "http://registry:8005/internal/assets/parser/parser_core/versions/9.9.9"
    ]


def test_pinned_parser_digest_mismatch_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_urlopen(monkeypatch, [])
    settings = Settings(recipe_registry_url="http://registry:8005")
    with pytest.raises(workspace_module.WorkspaceError):
        workspace_module._fetch_parser_asset(
            settings, ParserAssetRef(version="9.9.9", digest="deadbeef")
        )
