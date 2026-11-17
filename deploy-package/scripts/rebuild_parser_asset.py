#!/usr/bin/env python3
"""Rebuild one parser_core asset directory from the sandbox runtime.

Copies the 9 runtime files into
``services/recipe_registry/data/assets/parser/parser_core/<version>`` and
recomputes every file sha256 plus the manifest checksum with the registry's
own validation code (so the digest matches the server exactly).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

PARSER_FILES = (
    "builtin.py",
    "strategies.py",
    "clauses.py",
    "inventory.py",
    "references.py",
    "projection.py",
    "dictionary.py",
    "dictionary_data.json",
    "translate.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    app = root / "new_app"
    runtime = app / "services" / "sandbox" / "runtime"
    asset = (
        app
        / "services"
        / "recipe_registry"
        / "data"
        / "assets"
        / "parser"
        / "parser_core"
        / args.version
    )
    sys.path.insert(0, str(app))
    from services.recipe_registry.assets import AssetManifest, validate_manifest

    asset.mkdir(parents=True, exist_ok=True)
    for name in PARSER_FILES:
        shutil.copyfile(runtime / name, asset / name)

    manifest_path = asset / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = AssetManifest.model_validate(payload)
    manifest.files = []
    manifest.created_at = datetime.now(UTC).isoformat(timespec="seconds")
    manifest.checksum = ""
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    files = {
        name: (asset / name).read_bytes()
        for name in PARSER_FILES
    }
    manifest = validate_manifest(manifest, files)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(
        f"rebuilt parser_core@{args.version} files={len(files)} "
        f"checksum={manifest.checksum}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
