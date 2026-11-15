"""Versioned parsing assets: parser bundles and rule packs.

Extends the recipe registry with a second asset family.  Parsing code and rules
are published as immutable versions with channel pointers, exactly like
recipes, so the sandbox can hot-load them per run without rebuilding the
engine image.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

CHANNELS = ("stable", "candidate", "shadow", "deprecated")
KINDS = ("parser", "rules")
DEFAULT_ROOT = Path(__file__).resolve().parent / "data" / "assets"
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
ALLOWED_SUFFIXES = {".py", ".json"}
MAX_BUNDLE_BYTES = 1024 * 1024


class AssetError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AssetFile(BaseModel):
    path: str
    sha256: str


class AssetManifest(BaseModel):
    schema_version: str = "1.0"
    kind: str
    asset_id: str
    version: str
    runtime_api: str = "sandbox-engine/1"
    python: str = "3.12"
    stdlib_only: bool = True
    entry_modules: list[str] = Field(default_factory=list)
    files: list[AssetFile] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    checksum: str = ""
    created_at: str = ""


class AssetRef(BaseModel):
    kind: str
    asset_id: str
    version: str
    digest: str
    channel: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _version_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def _canonical(manifest: AssetManifest) -> bytes:
    data = manifest.model_dump(mode="json")
    data.pop("checksum", None)
    data.pop("created_at", None)
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def compute_checksum(manifest: AssetManifest, files: dict[str, bytes]) -> str:
    digest = hashlib.sha256(_canonical(manifest))
    for path in sorted(files):
        digest.update(path.encode("utf-8"))
        digest.update(hashlib.sha256(files[path]).digest())
    return digest.hexdigest()


def _safe_path(path: str) -> str:
    if not path or path.startswith("/") or "\\" in path:
        raise AssetError("ASSET_FILE_INVALID", f"invalid file path: {path}")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise AssetError("ASSET_FILE_INVALID", f"invalid file path: {path}")
    if Path(path).suffix not in ALLOWED_SUFFIXES:
        raise AssetError("ASSET_FILE_INVALID", f"unsupported file type: {path}")
    return path


def validate_manifest(manifest: AssetManifest, files: dict[str, bytes]) -> AssetManifest:
    if manifest.kind not in KINDS:
        raise AssetError("ASSET_KIND_INVALID", f"unknown asset kind: {manifest.kind}")
    if not ASSET_ID_RE.match(manifest.asset_id):
        raise AssetError("ASSET_ID_INVALID", f"invalid asset_id: {manifest.asset_id}")
    if not SEMVER_RE.match(manifest.version):
        raise AssetError("ASSET_VERSION_INVALID", f"invalid version: {manifest.version}")
    if manifest.runtime_api != "sandbox-engine/1":
        raise AssetError(
            "ASSET_RUNTIME_INCOMPATIBLE",
            f"unsupported runtime_api: {manifest.runtime_api}",
        )
    total = sum(len(content) for content in files.values())
    if total > MAX_BUNDLE_BYTES:
        raise AssetError(
            "ASSET_BUNDLE_TOO_LARGE",
            f"bundle exceeds {MAX_BUNDLE_BYTES} bytes: {total}",
        )
    declared = {item.path: item.sha256 for item in manifest.files}
    for path, content in files.items():
        _safe_path(path)
        actual = hashlib.sha256(content).hexdigest()
        if path in declared and declared[path] != actual:
            raise AssetError(
                "ASSET_FILE_DIGEST_MISMATCH",
                f"{path} declared={declared[path]} actual={actual}",
            )
        if path not in declared:
            manifest.files.append(AssetFile(path=path, sha256=actual))
    missing = [path for path in declared if path not in files]
    if missing:
        raise AssetError(
            "ASSET_FILE_MISSING", f"declared files are missing: {', '.join(missing)}"
        )
    manifest.checksum = compute_checksum(manifest, files)
    return manifest


class AssetRegistry:
    """File-backed registry shared by parser bundles and rule packs."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT
        self.path = self.root / "registry.json"
        self._lock = threading.Lock()
        self.state = self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> dict:
        state: dict = {
            "schema_version": "1.0",
            "updated_at": "",
            "channels": {channel: {} for channel in CHANNELS},
            "history": [],
        }
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
            state["updated_at"] = str(data.get("updated_at") or "")
            channels = data.get("channels") or {}
            for channel in CHANNELS:
                state["channels"][channel] = dict(channels.get(channel) or {})
            state["history"] = list(data.get("history") or [])
        return state

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state["updated_at"] = _now()
        payload = json.dumps(self.state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)

    def _key(self, kind: str, asset_id: str) -> str:
        return f"{kind}:{asset_id}"

    def _directory(self, kind: str, asset_id: str, version: str) -> Path:
        return self.root / kind / asset_id / version

    # -- read -------------------------------------------------------------
    def _read(
        self, kind: str, asset_id: str, version: str
    ) -> tuple[AssetManifest, dict[str, bytes]]:
        directory = self._directory(kind, asset_id, version)
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise AssetError(
                "ASSET_NOT_FOUND", f"{kind}/{asset_id}@{version} does not exist"
            )
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = AssetManifest.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise AssetError("ASSET_MANIFEST_INVALID", str(exc)) from exc
        files: dict[str, bytes] = {}
        for item in manifest.files:
            path = directory / item.path
            if not path.is_file():
                raise AssetError(
                    "ASSET_FILE_MISSING", f"{item.path} missing in {kind}/{asset_id}@{version}"
                )
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item.sha256:
                raise AssetError(
                    "ASSET_FILE_DIGEST_MISMATCH", f"{item.path} checksum mismatch"
                )
            files[item.path] = content
        expected = compute_checksum(manifest, files)
        if manifest.checksum and manifest.checksum != expected:
            raise AssetError(
                "ASSET_CHECKSUM_MISMATCH",
                f"declared={manifest.checksum} computed={expected}",
            )
        manifest.checksum = expected
        return manifest, files

    def get(self, kind: str, asset_id: str, version: str) -> tuple[AssetManifest, dict[str, bytes]]:
        return self._read(kind, asset_id, version)

    def resolve(self, kind: str, asset_id: str, channel: str = "stable") -> AssetRef:
        if channel not in CHANNELS:
            raise AssetError("ASSET_CHANNEL_INVALID", f"unknown channel: {channel}")
        version = self.state["channels"][channel].get(self._key(kind, asset_id))
        if not version:
            raise AssetError(
                "ASSET_NOT_RESOLVED", f"{kind}/{asset_id} has no pointer in {channel}"
            )
        manifest, _ = self._read(kind, asset_id, version)
        return AssetRef(
            kind=kind,
            asset_id=asset_id,
            version=version,
            digest=manifest.checksum,
            channel=channel,
        )

    def list_versions(self, kind: str, asset_id: str) -> list[AssetRef]:
        base = self.root / kind / asset_id
        if not base.is_dir():
            return []
        refs: list[AssetRef] = []
        for child in sorted(base.iterdir()):
            if not (child / "manifest.json").exists():
                continue
            manifest, _ = self._read(kind, asset_id, child.name)
            refs.append(
                AssetRef(
                    kind=kind,
                    asset_id=asset_id,
                    version=manifest.version,
                    digest=manifest.checksum,
                    channel=self.channel_of(kind, asset_id, manifest.version),
                )
            )
        return refs

    def channel_of(self, kind: str, asset_id: str, version: str) -> str | None:
        key = self._key(kind, asset_id)
        for channel in CHANNELS:
            if self.state["channels"][channel].get(key) == version:
                return channel
        return None

    def channels_for(self, kind: str, asset_id: str) -> dict[str, str]:
        key = self._key(kind, asset_id)
        return {
            channel: version
            for channel in CHANNELS
            if (version := self.state["channels"][channel].get(key))
        }

    def governance(self) -> list[dict]:
        issues: list[dict] = []
        stable_map = self.state["channels"]["stable"]
        for key, candidate in self.state["channels"]["candidate"].items():
            stable = stable_map.get(key)
            if stable and _version_key(candidate) < _version_key(stable):
                issues.append(
                    {
                        "code": "ASSET_CANDIDATE_BEHIND_STABLE",
                        "asset": key,
                        "stable": stable,
                        "candidate": candidate,
                    }
                )
        return issues

    def list_assets(self, kind: str | None = None) -> list[dict]:
        assets: list[dict] = []
        kinds = [kind] if kind else list(KINDS)
        for item in kinds:
            base = self.root / item
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_dir():
                    continue
                versions = self.list_versions(item, child.name)
                if not versions:
                    continue
                assets.append(
                    {
                        "kind": item,
                        "asset_id": child.name,
                        "channels": self.channels_for(item, child.name),
                        "versions": [ref.model_dump() for ref in versions],
                    }
                )
        return assets

    def history(self, kind: str, asset_id: str) -> list[dict]:
        key = self._key(kind, asset_id)
        return [
            item
            for item in self.state["history"]
            if item.get("asset") == key
        ]

    # -- write ------------------------------------------------------------
    def publish(self, manifest: AssetManifest, files: dict[str, bytes]) -> AssetRef:
        manifest = validate_manifest(manifest, files)
        directory = self._directory(manifest.kind, manifest.asset_id, manifest.version)
        target = directory / "manifest.json"
        key = self._key(manifest.kind, manifest.asset_id)
        with self._lock:
            if target.exists():
                existing, _ = self._read(
                    manifest.kind, manifest.asset_id, manifest.version
                )
                if existing.checksum != manifest.checksum:
                    raise AssetError(
                        "ASSET_VERSION_IMMUTABLE",
                        f"{key}@{manifest.version} exists with a different digest",
                    )
                return AssetRef(
                    kind=manifest.kind,
                    asset_id=manifest.asset_id,
                    version=manifest.version,
                    digest=existing.checksum,
                    channel=self.channel_of(
                        manifest.kind, manifest.asset_id, manifest.version
                    ),
                )
            directory.mkdir(parents=True, exist_ok=True)
            for path, content in sorted(files.items()):
                target_file = directory / path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_bytes(content)
            manifest.created_at = manifest.created_at or _now()
            target.write_text(
                json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return AssetRef(
            kind=manifest.kind,
            asset_id=manifest.asset_id,
            version=manifest.version,
            digest=manifest.checksum,
            channel=self.channel_of(manifest.kind, manifest.asset_id, manifest.version),
        )

    def promote(
        self,
        kind: str,
        asset_id: str,
        version: str,
        channel: str,
        *,
        actor: str,
        note: str = "",
    ) -> AssetRef:
        if channel not in CHANNELS:
            raise AssetError("ASSET_CHANNEL_INVALID", f"unknown channel: {channel}")
        if channel == "deprecated":
            raise AssetError(
                "ASSET_CHANNEL_INVALID", "use deprecate for the deprecated channel"
            )
        if not actor.strip():
            raise AssetError("ASSET_ACTOR_REQUIRED", "actor is required")
        manifest, _ = self._read(kind, asset_id, version)
        key = self._key(kind, asset_id)
        if channel == "candidate":
            stable = self.state["channels"]["stable"].get(key)
            if stable and _version_key(version) < _version_key(stable):
                raise AssetError(
                    "ASSET_CANDIDATE_BEHIND_STABLE",
                    f"candidate {key}@{version} is behind stable {stable}",
                )
        with self._lock:
            previous = self.state["channels"][channel].get(key)
            if previous == version:
                raise AssetError(
                    "ASSET_ALREADY_PROMOTED", f"{key}@{version} is already {channel}"
                )
            self.state["channels"][channel][key] = version
            self.state["history"].append(
                {
                    "kind": "promote",
                    "asset": key,
                    "channel": channel,
                    "from_version": previous,
                    "to_version": version,
                    "digest": manifest.checksum,
                    "actor": actor,
                    "note": note,
                    "at": _now(),
                }
            )
            self._save()
        return AssetRef(
            kind=kind,
            asset_id=asset_id,
            version=version,
            digest=manifest.checksum,
            channel=channel,
        )

    def rollback(
        self,
        kind: str,
        asset_id: str,
        channel: str,
        *,
        actor: str,
        note: str = "",
    ) -> AssetRef:
        if channel not in CHANNELS:
            raise AssetError("ASSET_CHANNEL_INVALID", f"unknown channel: {channel}")
        if not actor.strip():
            raise AssetError("ASSET_ACTOR_REQUIRED", "actor is required")
        key = self._key(kind, asset_id)
        with self._lock:
            current = self.state["channels"][channel].get(key)
            if not current:
                raise AssetError(
                    "ASSET_NOT_RESOLVED", f"{key} has no pointer in {channel}"
                )
            target: str | None = None
            for item in reversed(self.state["history"]):
                if (
                    item.get("kind") == "promote"
                    and item.get("asset") == key
                    and item.get("channel") == channel
                    and item.get("to_version") == current
                ):
                    target = item.get("from_version")
                    break
            if not target:
                raise AssetError(
                    "ASSET_ROLLBACK_UNAVAILABLE",
                    f"no previous version for {key} in {channel}",
                )
            manifest, _ = self._read(kind, asset_id, target)
            self.state["channels"][channel][key] = target
            self.state["history"].append(
                {
                    "kind": "rollback",
                    "asset": key,
                    "channel": channel,
                    "from_version": current,
                    "to_version": target,
                    "digest": manifest.checksum,
                    "actor": actor,
                    "note": note,
                    "at": _now(),
                }
            )
            self._save()
        return AssetRef(
            kind=kind,
            asset_id=asset_id,
            version=target,
            digest=manifest.checksum,
            channel=channel,
        )
