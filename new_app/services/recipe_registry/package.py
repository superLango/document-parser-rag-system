"""Immutable recipe package loading, validation and digest computation."""

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
RECIPE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
SUPPORTED_ENGINE_API = "recipe-engine/1"
SCHEMA_VERSION = "2.0"


class RecipeSignature(BaseModel):
    profile: str = "unknown"
    orientation: str = "grade_rows"
    n_cols: int = 0
    blocks: int = 0
    tokens: list[str] = Field(default_factory=list)
    multi_header: bool = False
    unit_set: list[str] = Field(default_factory=list)


class RecipeManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    recipe_id: str
    version: str
    engine_api: str = SUPPORTED_ENGINE_API
    profile: str
    signature: RecipeSignature = Field(default_factory=RecipeSignature)
    bindings: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)
    entrypoint: dict | None = None
    templates: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    compatibility: dict = Field(default_factory=dict)
    checksum: str = ""
    created_at: str = ""


class RecipeRef(BaseModel):
    recipe_id: str
    version: str
    digest: str
    channel: str | None = None


class RecipePackageError(ValueError):
    """A package violates the manifest contract or its digest."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_payload(manifest: RecipeManifest) -> bytes:
    """Digest input: manifest without the mutable checksum/created_at fields."""
    data = manifest.model_dump(mode="json")
    data.pop("checksum", None)
    data.pop("created_at", None)
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def compute_digest(manifest: RecipeManifest) -> str:
    return hashlib.sha256(canonical_payload(manifest)).hexdigest()


def validate_manifest(manifest: RecipeManifest) -> RecipeManifest:
    if not RECIPE_ID_RE.match(manifest.recipe_id):
        raise RecipePackageError(
            "RECIPE_ID_INVALID", f"invalid recipe_id: {manifest.recipe_id}"
        )
    if not SEMVER_RE.match(manifest.version):
        raise RecipePackageError(
            "RECIPE_VERSION_INVALID", f"invalid version: {manifest.version}"
        )
    if manifest.schema_version != SCHEMA_VERSION:
        raise RecipePackageError(
            "RECIPE_SCHEMA_UNSUPPORTED",
            f"unsupported schema_version: {manifest.schema_version}",
        )
    if manifest.engine_api != SUPPORTED_ENGINE_API:
        raise RecipePackageError(
            "RECIPE_ENGINE_INCOMPATIBLE",
            f"unsupported engine_api: {manifest.engine_api}",
        )
    if not manifest.profile:
        raise RecipePackageError("RECIPE_PROFILE_MISSING", "profile is required")

    expected = compute_digest(manifest)
    if manifest.checksum and manifest.checksum != expected:
        raise RecipePackageError(
            "RECIPE_CHECKSUM_MISMATCH",
            f"checksum mismatch: declared={manifest.checksum} computed={expected}",
        )
    manifest.checksum = expected
    return manifest


def build_package(payload: dict) -> RecipeManifest:
    try:
        manifest = RecipeManifest.model_validate(payload)
    except ValidationError as exc:
        raise RecipePackageError("RECIPE_MANIFEST_INVALID", str(exc)) from exc
    return validate_manifest(manifest)


def load_package(package_dir: str | Path) -> RecipeManifest:
    path = Path(package_dir) / "manifest.json"
    if not path.exists():
        raise RecipePackageError("RECIPE_MANIFEST_MISSING", f"missing {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RecipePackageError("RECIPE_MANIFEST_INVALID", str(exc)) from exc
    return build_package(payload)


def dump_manifest(manifest: RecipeManifest) -> str:
    return json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
