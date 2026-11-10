"""Declarative recipe loading and routing (M1.6)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..contracts import Recipe, TableGrid
from .lifecycle import RecipeRegistry
from .signature import build_signature, signature_score

DEFAULT_RECIPE_DIR = Path(__file__).resolve().parents[2] / "configs" / "recipes"


@dataclass(frozen=True)
class RecipeMatch:
    recipe: Recipe | None
    status: str
    score: float = 0.0


def load_recipes(path: str | Path | None = None) -> list[Recipe]:
    target = Path(path) if path is not None else DEFAULT_RECIPE_DIR
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(target.glob("*.json"))
    else:
        return []
    recipes: list[Recipe] = []
    for file_path in files:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if "recipe_id" not in data:
            continue
        recipes.append(Recipe.model_validate(data))
    # M2.5.3: the lifecycle registry overrides authored status (promotion,
    # rollback, deprecation) without rewriting the recipe files.
    registry_path = target / "registry.json" if target.is_dir() else target.parent / "registry.json"
    if registry_path.exists():
        recipes = RecipeRegistry(registry_path).apply(recipes)
    return recipes


def match_recipe(table: TableGrid, recipes: list[Recipe]) -> RecipeMatch:
    if not recipes:
        return RecipeMatch(recipe=None, status="unknown", score=0.0)
    best: tuple[Recipe, float] | None = None
    for recipe in recipes:
        if recipe.status != "active":
            continue
        score = signature_score(table, recipe.signature)
        if best is None or score > best[1]:
            best = (recipe, score)
    if best is None:
        return RecipeMatch(recipe=None, status="unknown", score=0.0)
    recipe, score = best
    if score >= 0.9:
        return RecipeMatch(recipe=recipe, status="exact", score=score)
    if score >= 0.6:
        return RecipeMatch(recipe=recipe, status="candidate", score=score)
    return RecipeMatch(recipe=None, status="unknown", score=score)


def route_table(table: TableGrid, recipes: list[Recipe] | None = None) -> RecipeMatch:
    return match_recipe(table, recipes if recipes is not None else load_recipes())


def table_signature_dict(table: TableGrid) -> dict:
    return build_signature(table).model_dump(mode="json")
