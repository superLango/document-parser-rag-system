"""Recipe JSON Schema validation (M2.5.1-01).

Pydantic already validates ``Recipe`` at load time; the JSON Schema adds a
language-neutral contract for authoring tools, CI and reviewers.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "recipe.schema.json"
)
DEFAULT_RECIPE_DIR = Path(__file__).resolve().parents[2] / "configs" / "recipes"


def load_schema(path: str | Path | None = None) -> dict:
    target = Path(path) if path is not None else DEFAULT_SCHEMA_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def validate_recipe(path: str | Path, schema: dict | None = None) -> list[str]:
    """Return human-readable schema errors; empty list means valid."""
    target = Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema or load_schema())
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    return [
        f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    ]


def validate_recipe_dir(
    path: str | Path | None = None, schema: dict | None = None
) -> dict[str, list[str]]:
    target = Path(path) if path is not None else DEFAULT_RECIPE_DIR
    files = [
        file_path
        for file_path in sorted(target.glob("*.json"))
        if json.loads(file_path.read_text(encoding="utf-8")).get("recipe_id")
    ]
    return {file_path.name: validate_recipe(file_path, schema) for file_path in files}


def recipe_id_matches_stem(path: str | Path) -> bool:
    target = Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    return data.get("recipe_id") == target.stem
