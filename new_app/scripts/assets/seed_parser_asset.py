"""Publish the sandbox runtime parser code as a versioned parser asset.

Usage (from new_app):
    python scripts/assets/seed_parser_asset.py --version 1.0.0 --channel stable
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT))

from services.recipe_registry.assets import AssetManifest, AssetRegistry  # noqa: E402

RUNTIME_DIR = APP_ROOT / "services" / "sandbox" / "runtime"
PARSER_FILES = (
    "builtin.py",
    "strategies.py",
    "clauses.py",
    "inventory.py",
    "references.py",
    "projection.py",
    "dictionary.py",
    "dictionary_data.json",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-id", default="parser_core")
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", default="")
    parser.add_argument("--actor", default="release")
    parser.add_argument("--note", default="seed from sandbox runtime")
    args = parser.parse_args()

    files = {
        name: (RUNTIME_DIR / name).read_bytes()
        for name in PARSER_FILES
    }
    manifest = AssetManifest(
        kind="parser",
        asset_id=args.asset_id,
        version=args.version,
        entry_modules=[
            "builtin",
            "strategies",
            "clauses",
            "inventory",
            "references",
            "projection",
            "dictionary",
        ],
    )
    registry = AssetRegistry()
    ref = registry.publish(manifest, files)
    print(f"published {ref.kind}/{ref.asset_id}@{ref.version} digest={ref.digest}")
    if args.channel:
        ref = registry.promote(
            "parser",
            args.asset_id,
            args.version,
            args.channel,
            actor=args.actor,
            note=args.note,
        )
        print(f"promoted {ref.asset_id}@{ref.version} -> {ref.channel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
