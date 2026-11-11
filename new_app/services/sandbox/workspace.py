"""Prepare a deterministic, read-only workspace for an execution."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hanson_contracts import ExecutionRequest, RecipeRef, TableAssignment, TemplateRef

from services.recipe_registry.package import (
    RecipeManifest,
    RecipePackageError,
    build_package,
    load_package,
)
from services.shared.storage import ObjectStore

from .config import Settings


class WorkspaceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class RecipeBundle:
    manifest: dict[str, Any]
    files: dict[str, bytes]
    digest: str


@dataclass
class Workspace:
    root: Path
    request: ExecutionRequest
    files: dict[str, bytes]
    input_hashes: dict[str, str]

    def cleanup(self) -> None:
        for path in [self.root, *self.root.rglob("*")]:
            try:
                path.chmod(0o755 if path.is_dir() else 0o644)
            except OSError:
                pass
        shutil.rmtree(self.root, ignore_errors=True)


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_join(base: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or "\\" in relative:
        raise WorkspaceError("SANDBOX_RECIPE_FILE_INVALID", f"invalid path: {relative}")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise WorkspaceError("SANDBOX_RECIPE_FILE_INVALID", f"invalid path: {relative}")
    target = (base / relative).resolve()
    if not target.is_relative_to(base.resolve()):
        raise WorkspaceError("SANDBOX_RECIPE_FILE_INVALID", f"path escapes root: {relative}")
    return target


def _recipe_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if not root.exists():
        return files
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise WorkspaceError(
                "SANDBOX_RECIPE_FILE_INVALID", f"symlink not allowed: {path.name}"
            )
        if not path.is_file() or path.name == "manifest.json":
            continue
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _fetch_remote_recipe(
    ref: RecipeRef, settings: Settings
) -> RecipeManifest | None:
    """Candidate recipes live in the registry container; fetch by version."""
    if not settings.recipe_registry_url:
        return None
    url = (
        f"{settings.recipe_registry_url.rstrip('/')}/internal/recipes/"
        f"{ref.recipe_id}/versions/{ref.version}"
    )
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    try:
        manifest = build_package(payload)
    except RecipePackageError:
        return None
    if manifest.entrypoint:
        # The registry API returns the manifest only; entrypoint files still
        # come from the local image.
        return None
    return manifest


def _resolve_recipe(ref: RecipeRef, settings: Settings) -> RecipeBundle:
    try:
        if ref.manifest is not None:
            manifest: RecipeManifest = build_package(dict(ref.manifest))
            files = {
                path: content.encode("utf-8") for path, content in ref.files.items()
            }
            for path in files:
                safe_join(Path("/"), path)
        else:
            remote = _fetch_remote_recipe(ref, settings)
            if remote is not None:
                manifest = remote
                files = {}
            else:
                root = settings.recipe_data_dir / ref.recipe_id / ref.version
                if not (root / "manifest.json").exists():
                    raise WorkspaceError(
                        "SANDBOX_RECIPE_NOT_FOUND",
                        f"recipe package not found: {ref.recipe_id}@{ref.version}",
                    )
                manifest = load_package(root)
                files = _recipe_files(root)
    except RecipePackageError as exc:
        raise WorkspaceError(exc.code, str(exc)) from exc

    if manifest.recipe_id != ref.recipe_id or manifest.version != ref.version:
        raise WorkspaceError(
            "SANDBOX_RECIPE_REF_MISMATCH",
            f"package is {manifest.recipe_id}@{manifest.version}, "
            f"request is {ref.recipe_id}@{ref.version}",
        )
    if ref.digest and ref.digest != manifest.checksum:
        raise WorkspaceError(
            "SANDBOX_RECIPE_DIGEST_MISMATCH",
            f"recipe digest mismatch: declared={ref.digest} actual={manifest.checksum}",
        )
    return RecipeBundle(
        manifest=manifest.model_dump(mode="json"),
        files=files,
        digest=manifest.checksum,
    )


def _resolve_template(ref: TemplateRef, settings: Settings) -> tuple[dict[str, Any], str]:
    if ref.definition is not None:
        payload = {
            "schema_version": "2.0",
            "template_id": ref.template_id,
            "version": ref.version,
            "definition": ref.definition,
        }
    else:
        path = settings.template_data_dir / ref.template_id / ref.version / "template.json"
        if not path.exists():
            raise WorkspaceError(
                "SANDBOX_TEMPLATE_NOT_FOUND",
                f"template not found: {ref.template_id}@{ref.version}",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise WorkspaceError("SANDBOX_TEMPLATE_INVALID", str(exc)) from exc
    if payload.get("template_id") != ref.template_id or payload.get("version") != ref.version:
        raise WorkspaceError(
            "SANDBOX_TEMPLATE_REF_MISMATCH",
            f"template is {payload.get('template_id')}@{payload.get('version')}",
        )
    digest = sha256(canonical_bytes(payload))
    if ref.digest and ref.digest != digest:
        raise WorkspaceError(
            "SANDBOX_TEMPLATE_DIGEST_MISMATCH",
            f"template digest mismatch: declared={ref.digest} actual={digest}",
        )
    return payload, digest


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relative, data in sorted(files.items()):
        target = safe_join(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o444)


def _chmod_dirs(root: Path, relative_dirs: list[str]) -> None:
    for relative in relative_dirs:
        target = safe_join(root, relative)
        target.chmod(0o555)


async def prepare_workspace(
    request: ExecutionRequest,
    store: ObjectStore,
    settings: Settings,
) -> Workspace:
    request = request.model_copy(deep=True)
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="exec-", dir=settings.workspace_root))
    files: dict[str, bytes] = {}
    try:
        ocr_bytes = await store.get_bytes(request.ocr.storage_key)
        if len(ocr_bytes) > settings.max_input_bytes:
            raise WorkspaceError(
                "SANDBOX_INPUT_TOO_LARGE",
                f"ocr input exceeds {settings.max_input_bytes} bytes",
            )
        actual = sha256(ocr_bytes)
        if request.ocr.sha256 and request.ocr.sha256 != actual:
            raise WorkspaceError(
                "SANDBOX_INPUT_DIGEST_MISMATCH",
                f"ocr digest mismatch: declared={request.ocr.sha256} actual={actual}",
            )
        request.ocr.sha256 = actual
        try:
            ocr_payload = json.loads(ocr_bytes)
        except ValueError as exc:
            raise WorkspaceError("SANDBOX_INPUT_INVALID", f"ocr is not JSON: {exc}") from exc
        if not isinstance(ocr_payload, dict):
            raise WorkspaceError("SANDBOX_INPUT_INVALID", "ocr payload must be an object")

        recipes: dict[str, RecipeBundle] = {}
        primary = _resolve_recipe(request.recipe, settings)
        recipes[request.recipe.recipe_id] = primary

        assignments: list[TableAssignment] = []
        for item in request.assignments:
            if item.recipe_id == request.recipe.recipe_id:
                if item.version != request.recipe.version:
                    raise WorkspaceError(
                        "SANDBOX_RECIPE_CONFLICT",
                        f"conflicting versions for {item.recipe_id}",
                    )
                item = item.model_copy(update={"digest": primary.digest})
                assignments.append(item)
                continue
            if item.recipe_id in recipes:
                bundle = recipes[item.recipe_id]
                if bundle.manifest.get("version") != item.version:
                    raise WorkspaceError(
                        "SANDBOX_RECIPE_CONFLICT",
                        f"conflicting versions for {item.recipe_id}",
                    )
                item = item.model_copy(update={"digest": bundle.digest})
                assignments.append(item)
                continue
            ref = RecipeRef(
                recipe_id=item.recipe_id,
                version=item.version,
                digest=item.digest,
            )
            bundle = _resolve_recipe(ref, settings)
            recipes[item.recipe_id] = bundle
            item = item.model_copy(update={"digest": bundle.digest})
            assignments.append(item)

        template_payload, template_digest = _resolve_template(request.template, settings)

        request.recipe.digest = primary.digest
        request.recipe.manifest = None
        request.recipe.files = {}
        request.template.digest = template_digest
        request.template.definition = None
        request.assignments = assignments
        request_payload = request.model_dump(mode="json")
        request_bytes = canonical_bytes(request_payload)
        document_bytes = canonical_bytes(request.document.model_dump(mode="json"))

        files["input/request.json"] = request_bytes
        files["input/ocr.json"] = ocr_bytes
        files["input/document.json"] = document_bytes
        for recipe_id, bundle in sorted(recipes.items()):
            files[f"recipes/{recipe_id}/manifest.json"] = canonical_bytes(bundle.manifest)
            for relative, content in sorted(bundle.files.items()):
                files[f"recipes/{recipe_id}/{relative}"] = content
        files[f"templates/{request.template.template_id}/template.json"] = canonical_bytes(
            template_payload
        )

        _write_tree(root, files)
        (root / "output").mkdir(parents=True, exist_ok=True)
        (root / "output").chmod(0o777)
        _chmod_dirs(
            root,
            ["input"]
            + [f"recipes/{recipe_id}" for recipe_id in sorted(recipes)]
            + [f"templates/{request.template.template_id}"],
        )
        (root / "input").chmod(0o555)
        for recipe_id in recipes:
            (root / "recipes" / recipe_id).chmod(0o555)
            for path in sorted((root / "recipes" / recipe_id).rglob("*")):
                if path.is_dir():
                    path.chmod(0o555)
        template_dir = root / "templates" / request.template.template_id
        for path in sorted(template_dir.rglob("*")):
            if path.is_dir():
                path.chmod(0o555)

        return Workspace(
            root=root,
            request=request,
            files=files,
            input_hashes={
                "request": sha256(request_bytes),
                "ocr": sha256(ocr_bytes),
                "document": sha256(document_bytes),
            },
        )
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
