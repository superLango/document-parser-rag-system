"""L2 config/recipe repair: whitelisted operators on an isolated overlay."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from ..contracts import DocumentResult, TableGrid
from ..pipeline import run_pipeline
from ..settings import Settings
from .config import SelfHealSettings, normalize_ocr_backend
from .contracts import (
    CandidateRecipe,
    CandidateStatus,
    Finding,
    ProposalStatus,
    RepairLevel,
    RepairProposal,
    new_id,
)
from .l1 import diff_results, target_resolved, _new_errors
from .locate import load_result, load_trace
from .sandbox import (
    append_alias,
    append_table_repair,
    create_overlay_project,
    update_json,
)

OPERATORS: dict[str, tuple[str, ...]] = {
    "column_alias.add": ("alias", "property"),
    "table_repair.add": ("document_key", "table_id", "spec"),
    "recipe.binding_override": ("recipe_id", "bindings"),
    "unit_normalize.add": ("pattern", "unit"),
    "property_map.add": ("alias", "property"),
    "extractor.enable": ("extractor",),
    "coverage_template.hint": ("doc_type", "template"),
}
EFFECTIVE_OPERATORS = {
    "column_alias.add",
    "table_repair.add",
    "recipe.binding_override",
}
ADVISORY_OPERATORS = set(OPERATORS) - EFFECTIVE_OPERATORS


def table_signature(table: TableGrid) -> str:
    payload = {
        "profile": table.profile,
        "orientation": table.orientation,
        "n_cols": table.n_cols,
        "header": table.header_paths,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def signature_for_result(result: DocumentResult, table_id: str | None) -> str:
    if table_id:
        table = next((item for item in result.tables if item.table_id == table_id), None)
        if table is not None:
            return table_signature(table)
    payload = sorted(table_signature(table) for table in result.tables)
    return hashlib.sha1("|".join(payload).encode("utf-8")).hexdigest()[:12]


def validate_operator(operator: str, params: dict[str, Any]) -> list[str]:
    if operator not in OPERATORS:
        return [f"未注册的算子：{operator}"]
    return [
        f"缺少参数 {name}"
        for name in OPERATORS[operator]
        if params.get(name) in (None, "", {}, [])
    ]


def _recipe_mutator(recipe_id: str, bindings: dict[str, Any]):
    def mutate(path: Path) -> None:
        def updater(payload: dict) -> None:
            current = payload.setdefault("bindings", {})
            for key, value in bindings.items():
                current[key] = value

        update_json(path, updater)

    return mutate


class L2Repairer:
    def __init__(self, settings: SelfHealSettings) -> None:
        self.settings = settings

    def propose(
        self,
        finding: Finding,
        job_dir: str | Path,
        operator: str,
        params: dict[str, Any],
    ) -> tuple[RepairProposal, CandidateRecipe]:
        problems = validate_operator(operator, params)
        if problems:
            raise ValueError("；".join(problems))
        result = load_result(job_dir)
        if result is None:
            raise ValueError("任务产物不可读")
        signature = signature_for_result(result, finding.target.table_id)
        proposal_id = new_id("prp")
        overlay_dir = self.settings.overlays_root / proposal_id
        mutators: dict[str, Callable[[Path], None]] = {}
        if operator == "column_alias.add":
            mutators["column_aliases.json"] = append_alias(
                str(params["alias"]), str(params["property"])
            )
        elif operator == "table_repair.add":
            mutators["table_repairs.json"] = append_table_repair(
                str(params["document_key"]), str(params["table_id"]), params["spec"]
            )
        elif operator == "recipe.binding_override":
            recipe_path = f"recipes/{params['recipe_id']}.json"
            if not (self.settings.project_root / "configs" / recipe_path).exists():
                raise ValueError(f"配方不存在：{params['recipe_id']}")
            mutators[recipe_path] = _recipe_mutator(
                str(params["recipe_id"]), params["bindings"]
            )

        overlay = create_overlay_project(self.settings, overlay_dir, mutators)
        manifest = {
            "proposal_id": proposal_id,
            "operator": operator,
            "params": params,
            "effective": operator in EFFECTIVE_OPERATORS,
            "signature": signature,
            "source_project": str(self.settings.project_root),
            "overlay_project": str(overlay.root),
            "source_hashes": _source_hashes(self.settings, operator, params),
        }
        (overlay_dir / "overlay_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        proposal = RepairProposal(
            proposal_id=proposal_id,
            finding_ids=[finding.finding_id],
            level=RepairLevel.L2,
            operator=operator,
            params={**params, "effective": operator in EFFECTIVE_OPERATORS},
            target_signature=signature,
            status=ProposalStatus.sandbox,
            artifact_dir=str(overlay_dir),
        )
        candidate = CandidateRecipe(
            proposal_id=proposal_id,
            signature=signature,
            operator=operator,
            params=params,
            status=CandidateStatus.local,
            overlay_dir=str(overlay_dir),
        )
        return proposal, candidate

    def shadow(
        self,
        proposal: RepairProposal,
        finding: Finding,
        job_dir: str | Path,
        out_dir: str | Path,
    ) -> dict[str, Any]:
        base = Path(job_dir)
        before = load_result(base)
        if before is None:
            raise ValueError("任务产物不可读")
        overlay_dir = Path(proposal.artifact_dir or "")
        project_root = overlay_dir / "project"
        if not project_root.exists():
            raise ValueError("overlay 项目不存在")
        trace = load_trace(base)
        versions = trace.get("versions") or {}
        settings = dataclasses.replace(
            Settings.from_env(),
            ocr_backend=normalize_ocr_backend(versions.get("ocr")),
            extractor_backend=versions.get("extractor") or "mock",
            project_root=project_root,
        )
        source = Path(before.document.source_path)
        if not source.is_absolute():
            source = (base / source).resolve()
        if not source.exists():
            raise ValueError(f"源文件不存在：{source}")
        target = Path(out_dir)
        run_pipeline(
            source,
            target,
            settings=settings,
            coverage_template=versions.get("coverage_template") or "product_full",
        )
        after = load_result(target)
        if after is None:
            raise ValueError("shadow 运行未生成 result.json")
        diff = diff_results(before, after)
        diff["reproduced"] = True
        diff["target_resolved"] = target_resolved(finding, after)
        diff["new_errors"] = _new_errors(before, after)
        (target / "shadow_diff.json").write_text(
            json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return diff


def _source_hashes(
    settings: SelfHealSettings, operator: str, params: dict[str, Any]
) -> dict[str, str]:
    relative = {
        "column_alias.add": "column_aliases.json",
        "table_repair.add": "table_repairs.json",
        "recipe.binding_override": f"recipes/{params.get('recipe_id')}.json",
    }.get(operator)
    if not relative:
        return {}
    path = settings.project_root / "configs" / relative
    if not path.exists():
        return {}
    return {relative: hashlib.sha256(path.read_bytes()).hexdigest()}


def rollback_overlay(proposal: RepairProposal) -> None:
    """Production configs are never modified; rollback only archives overlay."""

    if proposal.artifact_dir:
        overlay = Path(proposal.artifact_dir)
        if overlay.exists():
            archived = overlay.with_name(overlay.name + ".rolled_back")
            if archived.exists():
                shutil.rmtree(archived, ignore_errors=True)
            shutil.move(str(overlay), str(archived))
