"""Deterministic matcher scoring and migrated-recipe integration."""

from services.ocr.contracts import TableGrid
from services.recipe_registry.matcher import (
    EXACT_THRESHOLD,
    match_table,
    signature_score,
    signature_tokens,
)
from services.recipe_registry.package import RecipeManifest, RecipeSignature
from services.recipe_registry.registry import RecipeRegistry


def _table(**overrides) -> TableGrid:
    payload = {
        "table_id": "T1",
        "page_no": 1,
        "profile": "mechanical_properties",
        "orientation": "grade_rows",
        "n_cols": 3,
        "header_rows": 1,
        "header_paths": [["牌号"], ["抗拉强度 Rm/MPa"], ["断后伸长率 A/%"]],
        "rows": [
            ["牌号", "抗拉强度 Rm/MPa", "断后伸长率 A/%"],
            ["Q355B", "470", "22"],
        ],
        "blocks": [],
    }
    payload.update(overrides)
    return TableGrid.model_validate(payload)


def test_profile_mismatch_scores_zero() -> None:
    signature = RecipeSignature(profile="chemical_composition", n_cols=3)
    assert signature_score(_table(), signature) == 0.0


def test_full_match_reaches_exact_threshold() -> None:
    table = _table()
    tokens = signature_tokens(table)
    signature = RecipeSignature(
        profile=table.profile,
        orientation=table.orientation,
        n_cols=table.n_cols,
        blocks=len(table.blocks),
        tokens=tokens,
    )
    assert signature_score(table, signature) >= EXACT_THRESHOLD


def test_match_table_returns_candidate_for_partial_signature() -> None:
    table = _table()
    manifest = RecipeManifest(
        recipe_id="mechanical_properties_v1",
        version="1.0.0",
        profile="mechanical_properties",
        signature=RecipeSignature(
            profile="mechanical_properties",
            orientation="grade_rows",
            n_cols=9,
            blocks=0,
            tokens=["牌号", "力学性能", "rm"],
        ),
    )
    result = match_table(table, [manifest])
    assert result.status in {"candidate", "exact"}
    assert result.recipe_id == "mechanical_properties_v1"
    assert 0.0 < result.score <= 1.0


def test_migrated_registry_matches_golden_table() -> None:
    registry = RecipeRegistry()
    manifests = registry.active_manifests("stable")
    assert len(manifests) >= 7
    result = match_table(_table(), manifests)
    assert result.status != "unknown"
    assert result.recipe_id
    assert result.version == "1.0.0"
    assert result.digest


def test_mechanical_table_beats_hardness_recipe() -> None:
    registry = RecipeRegistry()
    manifests = registry.active_manifests("stable")
    result = match_table(_table(), manifests)
    assert result.recipe_id == "mechanical_properties_v1"


def test_hardness_table_still_routes_to_hardness() -> None:
    registry = RecipeRegistry()
    manifests = registry.active_manifests("stable")
    table = _table(
        n_cols=2,
        header_paths=[["牌号"], ["硬度 HBW"]],
        rows=[["牌号", "硬度 HBW"], ["Q355B", "220"]],
    )
    result = match_table(table, manifests)
    assert result.recipe_id == "hardness_v1"
