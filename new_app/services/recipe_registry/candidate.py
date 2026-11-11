"""Candidate recipe construction from a validated JSON Patch."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .package import (
    RecipeManifest,
    RecipePackageError,
    RecipeRef,
    build_package,
)
from .registry import RecipeRegistry, RegistryError

ALLOWED_PATCH_ROOTS = (
    "/bindings",
    "/signature",
    "/rules",
    "/templates",
    "/compatibility",
)


class CandidateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise CandidateError("RECIPE_VERSION_INVALID", f"invalid version: {value}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _path_parts(path: str) -> list[str]:
    if not path.startswith("/") or path == "/":
        raise CandidateError("CANDIDATE_PATCH_INVALID", f"invalid path: {path}")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _check_root(parts: list[str]) -> None:
    root = "/" + parts[0]
    if root not in ALLOWED_PATCH_ROOTS:
        raise CandidateError(
            "CANDIDATE_PATCH_FORBIDDEN",
            f"patch root {root} is not allowed",
        )


def _parent(data: Any, parts: list[str]) -> tuple[Any, str]:
    node = data
    for part in parts[:-1]:
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError) as exc:
                raise CandidateError(
                    "CANDIDATE_PATCH_INVALID", f"bad list path: {part}"
                ) from exc
        elif isinstance(node, dict):
            if part not in node:
                raise CandidateError(
                    "CANDIDATE_PATCH_INVALID", f"missing path segment: {part}"
                )
            node = node[part]
        else:
            raise CandidateError(
                "CANDIDATE_PATCH_INVALID", f"cannot traverse {part}"
            )
    return node, parts[-1]


def apply_patch(
    manifest: RecipeManifest,
    ops: list[dict[str, Any]],
    candidate_version: str,
) -> RecipeManifest:
    if not ops:
        raise CandidateError("CANDIDATE_PATCH_EMPTY", "patch has no ops")
    base_version = _version_tuple(manifest.version)
    if _version_tuple(candidate_version) <= base_version:
        raise CandidateError(
            "CANDIDATE_VERSION_INVALID",
            f"candidate {candidate_version} must be greater than {manifest.version}",
        )
    data = manifest.model_dump(mode="json")
    for op in ops:
        action = str(op.get("op") or "")
        parts = _path_parts(str(op.get("path") or ""))
        _check_root(parts)
        parent, key = _parent(data, parts)
        if action == "add":
            if isinstance(parent, list):
                if key == "-":
                    parent.append(op.get("value"))
                else:
                    parent.insert(int(key), op.get("value"))
            elif isinstance(parent, dict):
                parent[key] = op.get("value")
            else:
                raise CandidateError("CANDIDATE_PATCH_INVALID", "add target is not a container")
        elif action == "replace":
            if isinstance(parent, list):
                try:
                    parent[int(key)] = op.get("value")
                except (ValueError, IndexError) as exc:
                    raise CandidateError(
                        "CANDIDATE_PATCH_INVALID", f"replace index {key} is invalid"
                    ) from exc
            elif isinstance(parent, dict) and key in parent:
                parent[key] = op.get("value")
            else:
                raise CandidateError(
                    "CANDIDATE_PATCH_INVALID", f"replace target missing: {key}"
                )
        elif action == "remove":
            if isinstance(parent, list):
                try:
                    parent.pop(int(key))
                except (ValueError, IndexError) as exc:
                    raise CandidateError(
                        "CANDIDATE_PATCH_INVALID", f"remove index {key} is invalid"
                    ) from exc
            elif isinstance(parent, dict) and key in parent:
                del parent[key]
            else:
                raise CandidateError(
                    "CANDIDATE_PATCH_INVALID", f"remove target missing: {key}"
                )
        elif action == "test":
            current = parent.get(key) if isinstance(parent, dict) else None
            if current != op.get("value"):
                raise CandidateError(
                    "CANDIDATE_PATCH_TEST_FAILED", f"test failed at {op.get('path')}"
                )
        else:
            raise CandidateError(
                "CANDIDATE_PATCH_INVALID", f"unsupported op: {action}"
            )
    data["version"] = candidate_version
    data["checksum"] = ""
    data["created_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        return build_package(data)
    except RecipePackageError as exc:
        raise CandidateError(exc.code, str(exc)) from exc


def build_candidate(
    registry: RecipeRegistry,
    recipe_id: str,
    base_version: str,
    candidate_version: str,
    ops: list[dict[str, Any]],
    *,
    actor: str,
    note: str = "",
) -> RecipeRef:
    if not actor.strip():
        raise CandidateError("RECIPE_ACTOR_REQUIRED", "actor is required")
    base = registry.get(recipe_id, base_version)
    candidate = apply_patch(base, ops, candidate_version)
    try:
        registry.publish(candidate)
        return registry.promote(
            recipe_id,
            candidate_version,
            "candidate",
            actor=actor,
            note=note or f"candidate from {base_version}",
        )
    except RegistryError as exc:
        if exc.code == "RECIPE_ALREADY_PROMOTED":
            return RecipeRef(
                recipe_id=recipe_id,
                version=candidate_version,
                digest=candidate.checksum,
                channel="candidate",
            )
        raise
