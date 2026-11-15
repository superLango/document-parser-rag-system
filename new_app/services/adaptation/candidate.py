"""Build L2 recipe / L3 code candidate packages (Phase 2 skeleton).

Candidates are never promoted here: each package records the drift reasons, the
manifest diff and the verification steps, and must pass sandbox replay plus a
human diff (`requires_sandbox` / `requires_human` on the plan).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .models import AdaptationLevel, DriftKind, DriftReport, now_iso

DEFAULT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "recipe_registry"
    / "data"
    / "editions"
    / "candidates"
)
ALIAS_TARGETS = {
    "rm": "Rm",
    "rp0.2": "Rp0.2",
    "rp0,2": "Rp0.2",
    "reh": "ReH",
    "rel": "ReL",
    "a": "A",
    "z": "Z",
    "kv2": "KV2",
    "ku2": "KU2",
    "ku5": "KU5",
    "hb": "HB",
    "hbw": "HBW",
    "hrc": "HRC",
    "hrb": "HRB",
    "hv": "HV",
    "kic": "KIC",
    "抗拉强度": "Rm",
    "屈服强度": "Rp0.2",
    "断后伸长率": "A",
    "断面收缩率": "Z",
    "冲击吸收能量": "KV2",
    "布氏硬度": "HB",
    "洛氏硬度": "HRC",
    "维氏硬度": "HV",
    "断裂韧度": "KIC",
}


class CandidatePackage(BaseModel):
    candidate_id: str
    standard_id: str
    edition: str
    level: AdaptationLevel
    recipe_id: str = ""
    base_version: str = ""
    candidate_version: str = ""
    reasons: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    diff: dict[str, Any] = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    status: str = "pending_sandbox"
    created_at: str = ""
    requires_sandbox: bool = True
    requires_human: bool = True


def bump_patch(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version or "")
    if not match:
        return "0.0.1"
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def build_recipe_candidate(
    standard_id: str,
    edition: str,
    base_manifest: dict[str, Any],
    report: DriftReport,
) -> CandidatePackage:
    """L2: propose a recipe patch (measure aliases + condition tokens)."""
    manifest = copy.deepcopy(base_manifest)
    base_version = str(manifest.get("version") or "")
    manifest["version"] = bump_patch(base_version)
    manifest.pop("checksum", None)
    bindings = manifest.setdefault("bindings", {})
    measures = bindings.setdefault("measures", {})
    added: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for item in report.drifts:
        if item.kind != DriftKind.MEASURE_LOST:
            continue
        for token in _tokens(item.detail):
            target = ALIAS_TARGETS.get(token.lower())
            if not target or target not in measures:
                unresolved.append(token)
                continue
            config = measures.setdefault(target, {})
            aliases = config.setdefault("aliases", [])
            if token not in aliases:
                aliases.append(token)
                added.setdefault(target, []).append(token)
    conditions = bindings.setdefault("conditions", [])
    added_conditions = []
    for item in report.drifts:
        if item.kind != DriftKind.HEADER_CHANGED:
            continue
        for token in _tokens(item.detail):
            if token.isascii() or len(token) > 12:
                continue
            if token not in conditions:
                conditions.append(token)
                added_conditions.append(token)
    reasons = [
        f"{item.kind.value}: {item.table} {item.detail}".strip()
        for item in report.drifts
        if item.kind in {DriftKind.MEASURE_LOST, DriftKind.HEADER_CHANGED}
    ]
    candidate = CandidatePackage(
        candidate_id=f"{standard_id}-{edition}-{manifest.get('recipe_id')}-"
        f"{manifest['version']}",
        standard_id=standard_id,
        edition=edition,
        level=AdaptationLevel.L2_RECIPE_CANDIDATE,
        recipe_id=str(manifest.get("recipe_id") or ""),
        base_version=base_version,
        candidate_version=str(manifest["version"]),
        reasons=reasons,
        manifest=manifest,
        diff={
            "measure_aliases_added": added,
            "conditions_added": added_conditions,
        },
        unresolved=sorted(set(unresolved)),
        verification=[
            "sandbox replay with the candidate manifest",
            "record-level diff against the previous stable output",
            "human approval before promotion",
        ],
        created_at=now_iso(),
    )
    return candidate


def build_code_candidate(
    standard_id: str, edition: str, report: DriftReport
) -> CandidatePackage:
    """L3: package the structural drifts for a code-level patch and review."""
    reasons = [
        f"{item.kind.value}: {item.table} {item.detail}".strip()
        for item in report.drifts
        if item.severity == "error"
    ]
    return CandidatePackage(
        candidate_id=f"{standard_id}-{edition}-code-{now_iso()}",
        standard_id=standard_id,
        edition=edition,
        level=AdaptationLevel.L3_CODE_CANDIDATE,
        reasons=reasons,
        diff={
            "missing_tables": [
                item.table
                for item in report.drifts
                if item.kind == DriftKind.MISSING_TABLE
            ],
            "profile_changes": [
                f"{item.table}: {item.detail}"
                for item in report.drifts
                if item.kind == DriftKind.PROFILE_CHANGED
            ],
        },
        verification=[
            "write a code patch against parser/OCR",
            "sandbox replay on the new edition",
            "regression run on the previous edition",
            "human diff review before promotion",
        ],
        created_at=now_iso(),
    )


def save_candidate(candidate: CandidatePackage, root: str | Path | None = None) -> Path:
    base = Path(root) if root else DEFAULT_ROOT
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", candidate.standard_id)
    directory = base / safe / candidate.edition
    directory.mkdir(parents=True, exist_ok=True)
    filename = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", candidate.candidate_id)
    path = directory / f"{filename}.json"
    path.write_text(
        json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_candidate(path: str | Path) -> CandidatePackage:
    return CandidatePackage.model_validate_json(Path(path).read_text(encoding="utf-8"))


def list_candidates(root: str | Path | None = None) -> list[dict[str, str]]:
    base = Path(root) if root else DEFAULT_ROOT
    if not base.exists():
        return []
    found: list[dict[str, str]] = []
    for path in sorted(base.glob("*/*/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        found.append(
            {
                "path": str(path),
                "standard_id": str(payload.get("standard_id") or path.parents[1].name),
                "edition": str(payload.get("edition") or path.parent.name),
                "candidate_id": str(payload.get("candidate_id") or path.stem),
            }
        )
    return found


def _tokens(detail: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，;；\s]+", detail or "") if part.strip()]
