"""Candidate recipe authoring (M1.6-09).

A candidate is proposed deterministically from an existing TableGrid and its
column bindings. It is *not* auto-activated: a human reviews it, runs the golden
sample, then promotes it to ``configs/recipes/``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..contracts import ColumnBindingResult, Recipe, TableGrid
from ..tablegrid.normalize import clean_text
from .signature import build_signature, token_overlap


def propose_recipe(
    table: TableGrid,
    bindings: ColumnBindingResult,
    *,
    recipe_id: str | None = None,
    coverage_template: str | None = None,
    business_dictionary: str | None = None,
) -> Recipe:
    measures: dict[str, dict] = {}
    for item in bindings.bindings:
        if item.role != "measure" or not item.property:
            continue
        measures.setdefault(
            item.property,
            {"unit": item.unit, "family": item.item_family},
        )
    if not measures:
        raise ValueError("cannot propose a recipe without any measure column")
    row_keys = _labels(bindings, "row_key")
    conditions = _labels(bindings, "condition")
    methods = _labels(bindings, "method")
    strong_measures = [name for name in measures if name not in {"A", "Z", "E"}]
    if not row_keys and not conditions and len(strong_measures) < 2:
        raise ValueError("candidate lacks identity/conditions and has no strong measure")
    if not strong_measures and len(measures) < 2:
        raise ValueError("candidate only has weak elongation/modulus properties")
    signature = build_signature(table)
    candidate_id = recipe_id or _candidate_id(signature, table)
    rules = {
        "candidate": True,
        "source_table_id": table.table_id,
        "source_page_no": table.page_no,
        "conflicts": len(bindings.conflicts),
        "ambiguous": len(bindings.ambiguous),
        "unmapped": len(bindings.unmapped_columns),
    }
    if methods:
        rules["methods"] = methods
    return Recipe(
        recipe_id=candidate_id,
        version=1,
        status="candidate",
        profile=table.profile,
        signature=signature,
        bindings={
            "row_key": row_keys,
            "conditions": conditions,
            "measures": measures,
        },
        rules=rules,
        coverage_template=coverage_template
        or ("product_full" if table.profile != "inspection" else "product_full"),
        business_dictionary=business_dictionary,
    )


def is_duplicate(candidate: Recipe, recipes: list[Recipe], threshold: float = 0.8) -> Recipe | None:
    for recipe in recipes:
        if recipe.profile != candidate.profile:
            continue
        if recipe.signature.orientation != candidate.signature.orientation:
            continue
        overlap = token_overlap(candidate.signature.tokens, recipe.signature.tokens)
        if overlap >= threshold:
            return recipe
    return None


def save_candidate(candidate: Recipe, out_dir: str | Path) -> Path:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{candidate.recipe_id}.json"
    path.write_text(
        json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def promote_candidate(
    candidate_path: str | Path,
    recipe_dir: str | Path,
    *,
    force: bool = False,
) -> Path:
    source = Path(candidate_path)
    candidate = Recipe.model_validate_json(source.read_text(encoding="utf-8"))
    if candidate.status != "candidate":
        raise ValueError("only candidate recipes can be promoted")
    if not candidate.bindings.get("measures"):
        raise ValueError("candidate has no measures")
    target = Path(recipe_dir) / f"{candidate.recipe_id}.json"
    if target.exists() and not force:
        raise FileExistsError(f"recipe already exists: {target}")
    candidate.status = "active"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def _labels(bindings: ColumnBindingResult, role: str) -> list[str]:
    labels: list[str] = []
    for item in bindings.bindings:
        if item.role != role:
            continue
        label = clean_text(item.header_path[-1]) if item.header_path else ""
        if label and label not in labels:
            labels.append(label)
    return labels


def _candidate_id(signature, table: TableGrid) -> str:
    payload = json.dumps(signature.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]
    profile = table.profile or "unknown"
    return f"candidate_{profile}_{digest}"
