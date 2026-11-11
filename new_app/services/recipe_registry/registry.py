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


class RecipeRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT
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
