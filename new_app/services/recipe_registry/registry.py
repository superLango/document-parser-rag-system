"""File-backed recipe registry: immutable versions, channel pointers, history."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from .package import (
    RecipeManifest,
    RecipePackageError,
    RecipeRef,
    dump_manifest,
    load_package,
    missing_test_references,
    validate_manifest,
)

CHANNELS = ("stable", "candidate", "shadow", "deprecated")
DEFAULT_ROOT = Path(__file__).resolve().parent / "data" / "recipes"


class RegistryError(ValueError):
    """Registry-level failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _version_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


class RecipeRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT
        self.archive_root = self.root.parent / "recipes_archive"
        self.path = self.root / "registry.json"
        self._lock = threading.Lock()
        self.state = self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> dict:
        state: dict = {
            "schema_version": "2.0",
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

    # -- read -------------------------------------------------------------
    def channel_of(self, recipe_id: str, version: str) -> str | None:
        for channel in CHANNELS:
            if self.state["channels"][channel].get(recipe_id) == version:
                return channel
        return None

    def channels_for(self, recipe_id: str) -> dict[str, str]:
        return {
            channel: version
            for channel in CHANNELS
            if (version := self.state["channels"][channel].get(recipe_id))
        }

    def get(self, recipe_id: str, version: str) -> RecipeManifest:
        directory = self.root / recipe_id / version
        try:
            return load_package(directory)
        except RecipePackageError as exc:
            raise RegistryError("RECIPE_NOT_FOUND", str(exc)) from exc

    def channel_for(self, recipe_id: str, version: str) -> str | None:
        """返回该版本实际绑定的通道；未绑定任何通道时返回 None。"""
        for channel in CHANNELS:
            if self.state["channels"][channel].get(recipe_id) == version:
                return channel
        return None

    def resolve(self, recipe_id: str, channel: str = "stable") -> RecipeRef:
        if channel not in CHANNELS:
            raise RegistryError("RECIPE_CHANNEL_INVALID", f"unknown channel: {channel}")
        version = self.state["channels"][channel].get(recipe_id)
        if not version:
            raise RegistryError(
                "RECIPE_NOT_RESOLVED", f"{recipe_id} has no pointer in {channel}"
            )
        manifest = self.get(recipe_id, version)
        return RecipeRef(
            recipe_id=recipe_id,
            version=version,
            digest=manifest.checksum,
            channel=channel,
        )

    def list_versions(self, recipe_id: str) -> list[RecipeRef]:
        base = self.root / recipe_id
        if not base.is_dir():
            return []
        refs: list[RecipeRef] = []
        for child in sorted(base.iterdir()):
            if not (child / "manifest.json").exists():
                continue
            manifest = load_package(child)
            refs.append(
                RecipeRef(
                    recipe_id=recipe_id,
                    version=manifest.version,
                    digest=manifest.checksum,
                    channel=self.channel_of(recipe_id, manifest.version),
                )
            )
        return refs

    def list_recipes(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        recipes: list[dict] = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            versions = self.list_versions(child.name)
            if not versions:
                continue
            recipes.append(
                {
                    "recipe_id": child.name,
                    "channels": self.channels_for(child.name),
                    "versions": [ref.model_dump() for ref in versions],
                }
            )
        return recipes

    def active_manifests(self, channel: str = "stable") -> list[RecipeManifest]:
        if channel not in CHANNELS:
            raise RegistryError("RECIPE_CHANNEL_INVALID", f"unknown channel: {channel}")
        manifests: list[RecipeManifest] = []
        for recipe_id, version in self.state["channels"][channel].items():
            manifests.append(self.get(recipe_id, version))
        return manifests

    def stale_candidate_versions(self, recipe_id: str) -> list[str]:
        """比 stable 新、但未绑定 candidate/shadow/stable 的历史候选版本。"""
        stable = self.state["channels"]["stable"].get(recipe_id)
        if not stable:
            return []
        bound = {
            self.state["channels"][channel].get(recipe_id)
            for channel in ("stable", "candidate", "shadow")
        }
        stale: list[str] = []
        for ref in self.list_versions(recipe_id):
            if ref.version in bound:
                continue
            if _version_key(ref.version) > _version_key(stable):
                stale.append(ref.version)
        return sorted(stale, key=_version_key)

    def archive_stale_candidates(self, recipe_id: str, *, actor: str) -> list[str]:
        """把历史候选版本移出 registry（归档到 data/recipes_archive）。"""
        if not actor.strip():
            raise RegistryError("RECIPE_ACTOR_REQUIRED", "actor is required")
        versions = self.stale_candidate_versions(recipe_id)
        moved: list[str] = []
        for version in versions:
            source = self.root / recipe_id / version
            target = self.archive_root / recipe_id / version
            if not source.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise RegistryError(
                    "RECIPE_ARCHIVE_EXISTS", f"archive already exists: {target}"
                )
            source.rename(target)
            self.state["history"].append(
                {
                    "kind": "archive",
                    "recipe_id": recipe_id,
                    "channel": "candidate",
                    "from_version": version,
                    "to_version": "",
                    "digest": "",
                    "actor": actor,
                    "note": "superseded candidate archived",
                    "at": _now(),
                }
            )
            moved.append(version)
        if moved:
            with self._lock:
                self._save()
        return moved

    def governance(self) -> list[dict]:
        """Return version-governance violations without mutating the registry."""
        issues: list[dict] = []
        recipe_ids = {
            recipe_id
            for channel in CHANNELS
            for recipe_id in self.state["channels"][channel]
        }
        for recipe_id in sorted(recipe_ids):
            stable = self.state["channels"]["stable"].get(recipe_id)
            candidate = self.state["channels"]["candidate"].get(recipe_id)
            if (
                stable
                and candidate
                and _version_key(candidate) < _version_key(stable)
            ):
                issues.append(
                    {
                        "code": "CANDIDATE_BEHIND_STABLE",
                        "recipe_id": recipe_id,
                        "stable": stable,
                        "candidate": candidate,
                    }
                )
            for channel in ("candidate", "shadow", "stable"):
                version = self.state["channels"][channel].get(recipe_id)
                if not version:
                    continue
                try:
                    manifest = self.get(recipe_id, version)
                except RecipePackageError:
                    continue
                if not manifest.tests:
                    issues.append(
                        {
                            "code": "RECIPE_TESTS_MISSING",
                            "recipe_id": recipe_id,
                            "channel": channel,
                            "version": version,
                        }
                    )
                missing = missing_test_references(manifest)
                if missing:
                    issues.append(
                        {
                            "code": "RECIPE_TEST_FILE_MISSING",
                            "recipe_id": recipe_id,
                            "channel": channel,
                            "version": version,
                            "missing": missing,
                        }
                    )
            stale = self.stale_candidate_versions(recipe_id)
            if stale:
                issues.append(
                    {
                        "code": "RECIPE_CANDIDATE_STALE",
                        "recipe_id": recipe_id,
                        "count": len(stale),
                        "versions": stale[:20],
                    }
                )
        return issues

    # -- write ------------------------------------------------------------
    def publish(self, manifest: RecipeManifest) -> RecipeRef:
        manifest = validate_manifest(manifest)
        directory = self.root / manifest.recipe_id / manifest.version
        target = directory / "manifest.json"
        with self._lock:
            if target.exists():
                existing = load_package(directory)
                if existing.checksum != manifest.checksum:
                    raise RegistryError(
                        "RECIPE_VERSION_IMMUTABLE",
                        f"{manifest.recipe_id}@{manifest.version} exists with a different digest",
                    )
                return RecipeRef(
                    recipe_id=manifest.recipe_id,
                    version=manifest.version,
                    digest=manifest.checksum,
                    channel=self.channel_of(manifest.recipe_id, manifest.version),
                )
            directory.mkdir(parents=True, exist_ok=True)
            target.write_text(dump_manifest(manifest), encoding="utf-8")
        return RecipeRef(
            recipe_id=manifest.recipe_id,
            version=manifest.version,
            digest=manifest.checksum,
            channel=self.channel_of(manifest.recipe_id, manifest.version),
        )

    def promote(
        self,
        recipe_id: str,
        version: str,
        channel: str,
        *,
        actor: str,
        note: str = "",
    ) -> RecipeRef:
        if channel not in CHANNELS:
            raise RegistryError("RECIPE_CHANNEL_INVALID", f"unknown channel: {channel}")
        if not actor.strip():
            raise RegistryError("RECIPE_ACTOR_REQUIRED", "actor is required")
        if channel == "deprecated":
            raise RegistryError(
                "RECIPE_CHANNEL_INVALID", "use deprecate() for the deprecated channel"
            )
        manifest = self.get(recipe_id, version)
        if channel == "candidate":
            stable = self.state["channels"]["stable"].get(recipe_id)
            if stable and _version_key(version) < _version_key(stable):
                raise RegistryError(
                    "RECIPE_CANDIDATE_BEHIND_STABLE",
                    f"candidate {recipe_id}@{version} is behind stable {stable}",
                )
        with self._lock:
            previous = self.state["channels"][channel].get(recipe_id)
            if previous == version:
                raise RegistryError(
                    "RECIPE_ALREADY_PROMOTED", f"{recipe_id}@{version} is already {channel}"
                )
            self.state["channels"][channel][recipe_id] = version
            self.state["history"].append(
                {
                    "kind": "promote",
                    "recipe_id": recipe_id,
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
        return RecipeRef(
            recipe_id=recipe_id,
            version=version,
            digest=manifest.checksum,
            channel=channel,
        )

    def rollback(
        self,
        recipe_id: str,
        channel: str,
        *,
        actor: str,
        note: str = "",
    ) -> RecipeRef:
        if channel not in CHANNELS:
            raise RegistryError("RECIPE_CHANNEL_INVALID", f"unknown channel: {channel}")
        if not actor.strip():
            raise RegistryError("RECIPE_ACTOR_REQUIRED", "actor is required")
        with self._lock:
            current = self.state["channels"][channel].get(recipe_id)
            if not current:
                raise RegistryError(
                    "RECIPE_NOT_RESOLVED", f"{recipe_id} has no pointer in {channel}"
                )
            target: str | None = None
            for item in reversed(self.state["history"]):
                if (
                    item.get("kind") == "promote"
                    and item.get("recipe_id") == recipe_id
                    and item.get("channel") == channel
                    and item.get("to_version") == current
                ):
                    target = item.get("from_version")
                    break
            if not target:
                raise RegistryError(
                    "RECIPE_ROLLBACK_UNAVAILABLE",
                    f"no previous version for {recipe_id} in {channel}",
                )
            manifest = self.get(recipe_id, target)
            self.state["channels"][channel][recipe_id] = target
            self.state["history"].append(
                {
                    "kind": "rollback",
                    "recipe_id": recipe_id,
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
        return RecipeRef(
            recipe_id=recipe_id,
            version=target,
            digest=manifest.checksum,
            channel=channel,
        )

    def discard(
        self,
        recipe_id: str,
        version: str,
        *,
        actor: str,
        reason: str = "",
    ) -> RecipeRef:
        if not actor.strip():
            raise RegistryError("RECIPE_ACTOR_REQUIRED", "actor is required")
        manifest = self.get(recipe_id, version)
        with self._lock:
            current = self.state["channels"]["candidate"].get(recipe_id)
            if current != version:
                raise RegistryError(
                    "RECIPE_NOT_RESOLVED",
                    f"{recipe_id}@{version} is not the candidate",
                )
            del self.state["channels"]["candidate"][recipe_id]
            self.state["history"].append(
                {
                    "kind": "discard",
                    "recipe_id": recipe_id,
                    "channel": "candidate",
                    "from_version": version,
                    "to_version": "",
                    "digest": manifest.checksum,
                    "actor": actor,
                    "note": reason,
                    "at": _now(),
                }
            )
            self._save()
        return RecipeRef(
            recipe_id=recipe_id,
            version=version,
            digest=manifest.checksum,
            channel=None,
        )

    def deprecate(
        self,
        recipe_id: str,
        version: str,
        *,
        actor: str,
        reason: str = "",
    ) -> RecipeRef:
        if not actor.strip():
            raise RegistryError("RECIPE_ACTOR_REQUIRED", "actor is required")
        manifest = self.get(recipe_id, version)
        with self._lock:
            for channel in ("stable", "candidate", "shadow"):
                if self.state["channels"][channel].get(recipe_id) == version:
                    del self.state["channels"][channel][recipe_id]
            self.state["channels"]["deprecated"][recipe_id] = version
            self.state["history"].append(
                {
                    "kind": "deprecate",
                    "recipe_id": recipe_id,
                    "channel": "deprecated",
                    "from_version": version,
                    "to_version": version,
                    "digest": manifest.checksum,
                    "actor": actor,
                    "note": reason,
                    "at": _now(),
                }
            )
            self._save()
        return RecipeRef(
            recipe_id=recipe_id,
            version=version,
            digest=manifest.checksum,
            channel="deprecated",
        )
