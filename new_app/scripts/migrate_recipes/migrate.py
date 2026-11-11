"""Migrate legacy recipe/template JSON to recipe-package 2.0.

Run from ``new_app``:

    python scripts/migrate_recipes/migrate.py
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

NEW_APP_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = NEW_APP_DIR.parent
sys.path.insert(0, str(NEW_APP_DIR))

from services.recipe_registry.package import (  # noqa: E402
    RecipeManifest,
    RecipeSignature,
    build_package,
)
from services.recipe_registry.registry import (  # noqa: E402
    DEFAULT_ROOT,
    RecipeRegistry,
    RegistryError,
)

LEGACY_RECIPES = REPO_ROOT / "legacy" / "metal-doc-agent" / "configs" / "recipes"
LEGACY_TEMPLATES = REPO_ROOT / "legacy" / "metal-doc-agent" / "configs" / "schema_templates"
TEMPLATE_ROOT = NEW_APP_DIR / "services" / "recipe_registry" / "data" / "templates"

STATUS_CHANNEL = {
    "active": "stable",
    "candidate": "candidate",
    "retired": "deprecated",
}


def to_manifest(payload: dict) -> RecipeManifest:
    legacy_version = payload.get("version") or 1
    manifest = RecipeManifest(
        recipe_id=str(payload["recipe_id"]),
        version=f"{int(legacy_version)}.0.0",
        engine_api="recipe-engine/1",
        profile=str(payload.get("profile") or "unknown"),
        signature=RecipeSignature.model_validate(payload.get("signature") or {}),
        bindings=payload.get("bindings") or {},
        rules=payload.get("rules") or {},
        entrypoint=None,
        templates=[],
        tests=[],
        compatibility={
            "legacy_status": payload.get("status"),
            "legacy_version": legacy_version,
            "coverage_template": payload.get("coverage_template"),
            "business_dictionary": payload.get("business_dictionary"),
        },
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    return build_package(manifest.model_dump(mode="json"))


def migrate_recipes(registry: RecipeRegistry) -> tuple[int, int]:
    migrated = 0
    promoted = 0
    for path in sorted(LEGACY_RECIPES.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "recipe_id" not in payload:
            continue
        manifest = to_manifest(payload)
        registry.publish(manifest)
        migrated += 1
        channel = STATUS_CHANNEL.get(str(payload.get("status")), "candidate")
        if channel == "deprecated":
            registry.deprecate(
                manifest.recipe_id,
                manifest.version,
                actor="migration",
                reason="legacy status retired",
            )
        else:
            try:
                registry.promote(
                    manifest.recipe_id,
                    manifest.version,
                    channel,
                    actor="migration",
                    note=f"imported from {path.name}",
                )
                promoted += 1
            except RegistryError as exc:
                if exc.code != "RECIPE_ALREADY_PROMOTED":
                    raise
    return migrated, promoted


def migrate_templates() -> int:
    migrated = 0
    for path in sorted(LEGACY_TEMPLATES.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        template_id = "product_full" if "product" in path.stem else path.stem
        target_dir = TEMPLATE_ROOT / template_id / "1.0.0"
        target_dir.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": "2.0",
            "template_id": template_id,
            "name": payload.get("name") or template_id,
            "version": "1.0.0",
            "source": f"legacy/configs/schema_templates/{path.name}",
            "definition": payload,
        }
        (target_dir / "template.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        migrated += 1
    return migrated


def main() -> None:
    registry = RecipeRegistry(DEFAULT_ROOT)
    recipes, promoted = migrate_recipes(registry)
    templates = migrate_templates()
    print(f"recipes migrated={recipes} promoted={promoted} root={DEFAULT_ROOT}")
    print(f"templates migrated={templates} root={TEMPLATE_ROOT}")


if __name__ == "__main__":
    main()
