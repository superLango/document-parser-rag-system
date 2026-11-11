"""Artifact manifest: every run produces a verifiable audit package."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contracts import ArtifactEntry, ArtifactManifest
from .storage import ArtifactStore

MANIFEST_NAME = "artifacts.json"

ROLE_MAP: dict[str, tuple[str, str, bool]] = {
    "manifest.json": ("document_meta", "application/json", True),
    "result.json": ("result", "application/json", True),
    "schema_result.json": ("schema_result", "application/json", False),
    "evidence.jsonl": ("evidence", "application/x-ndjson", True),
    "audit.md": ("audit", "text/markdown", True),
    "trace.json": ("trace", "application/json", True),
    "pages.json": ("pages", "application/json", False),
    "outline.json": ("outline", "application/json", False),
    "coverage_plan.json": ("coverage", "application/json", False),
    "references.json": ("references", "application/json", False),
    "version_report.md": ("version_report", "text/markdown", False),
    "column_bindings.json": ("column_bindings", "application/json", False),
    "table_ir.json": ("table_ir", "application/json", False),
    "table_ir_diff.json": ("table_ir_diff", "application/json", False),
    "item_inventory.json": ("item_inventory", "application/json", False),
    "item_inventory_aligned.json": ("item_inventory_aligned", "application/json", False),
    "alignment.json": ("alignment", "application/json", False),
    "new_terms.json": ("new_terms", "application/json", False),
    "clauses.jsonl": ("clauses", "application/x-ndjson", False),
    "links.json": ("table_clause_links", "application/json", False),
    "coverage_audit.json": ("item_coverage_audit", "application/json", False),
    "routing.json": ("routing", "application/json", False),
}

EXCLUDED = {MANIFEST_NAME, "state.json"}


@dataclass(frozen=True)
class Verification:
    ok: bool
    issues: list[dict[str, str]]
    checked: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collect_entries(root: Path) -> list[ArtifactEntry]:
    root = Path(root).resolve()
    entries: list[ArtifactEntry] = []
    for relative, (role, content_type, required) in ROLE_MAP.items():
        path = root / relative
        if not path.exists():
            continue
        entries.append(
            ArtifactEntry(
                path=relative,
                role=role,
                content_type=content_type,
                size=path.stat().st_size,
                sha256=_sha256(path),
                required=required,
            )
        )
    for pattern, role in (
        ("tablegrid/*.json", "table"),
        ("pages/*.png", "page_image"),
        ("pages/layout-*.json", "page_layout"),
    ):
        for path in sorted(root.glob(pattern)):
            relative = path.relative_to(root).as_posix()
            if relative in EXCLUDED:
                continue
            entries.append(
                ArtifactEntry(
                    path=relative,
                    role=role,
                    content_type="image/png" if path.suffix == ".png" else "application/json",
                    size=path.stat().st_size,
                    sha256=_sha256(path),
                    required=False,
                )
            )
    return sorted(entries, key=lambda item: item.path)


def write_artifact_manifest(root: str | Path, *, job_id: str, doc_id: str) -> ArtifactManifest:
    root = Path(root)
    manifest = ArtifactManifest(
        job_id=job_id,
        doc_id=doc_id,
        created_at=_now(),
        artifacts=collect_entries(root),
    )
    ArtifactStore(root).write_json(MANIFEST_NAME, manifest)
    return manifest


def read_artifact_manifest(root: str | Path) -> ArtifactManifest:
    data = ArtifactStore(Path(root)).read_json(MANIFEST_NAME)
    return ArtifactManifest.model_validate(data)


def verify_artifacts(root: str | Path) -> Verification:
    root = Path(root)
    try:
        manifest = read_artifact_manifest(root)
    except (FileNotFoundError, ValueError) as exc:
        return Verification(
            ok=False,
            issues=[{"code": "MANIFEST_MISSING", "path": MANIFEST_NAME, "detail": str(exc)}],
            checked=0,
        )
    issues: list[dict[str, str]] = []
    listed = {entry.path for entry in manifest.artifacts}
    for relative, (role, _content_type, required) in ROLE_MAP.items():
        if required and relative not in listed:
            issues.append(
                {"code": "REQUIRED_ARTIFACT_MISSING", "path": relative, "detail": role}
            )
    for entry in manifest.artifacts:
        path = root / entry.path
        if not path.exists():
            issues.append(
                {"code": "ARTIFACT_MISSING", "path": entry.path, "detail": entry.role}
            )
            continue
        size = path.stat().st_size
        if size != entry.size:
            issues.append(
                {
                    "code": "SIZE_MISMATCH",
                    "path": entry.path,
                    "detail": f"{size} != {entry.size}",
                }
            )
            continue
        if _sha256(path) != entry.sha256:
            issues.append(
                {"code": "SHA256_MISMATCH", "path": entry.path, "detail": entry.role}
            )
    return Verification(ok=not issues, issues=issues, checked=len(manifest.artifacts))
