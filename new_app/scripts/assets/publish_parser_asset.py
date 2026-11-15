"""Publish the sandbox runtime parser code through the registry API.

Usage (from new_app):
    python scripts/assets/publish_parser_asset.py --version 1.0.1 --channel stable
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
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
    "translate.py",
)


def _post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:18005")
    parser.add_argument("--asset-id", default="parser_core")
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", default="")
    parser.add_argument("--actor", default="release")
    parser.add_argument("--note", default="publish parser bundle")
    args = parser.parse_args()

    files = {
        name: (RUNTIME_DIR / name).read_text(encoding="utf-8")
        for name in PARSER_FILES
    }
    manifest = {
        "schema_version": "1.0",
        "kind": "parser",
        "asset_id": args.asset_id,
        "version": args.version,
        "runtime_api": "sandbox-engine/1",
        "python": "3.12",
        "stdlib_only": True,
        "entry_modules": [
            "builtin",
            "strategies",
            "clauses",
            "inventory",
            "references",
            "projection",
            "dictionary",
            "translate",
        ],
        "files": [],
        "tests": [],
    }
    ref = _post(
        f"{args.api.rstrip('/')}/internal/assets",
        {"manifest": manifest, "files": files},
    )
    print(f"published {ref['kind']}/{ref['asset_id']}@{ref['version']} digest={ref['digest']}")
    if args.channel:
        ref = _post(
            f"{args.api.rstrip('/')}/internal/assets/parser/{args.asset_id}"
            f"/versions/{args.version}/promote",
            {
                "channel": args.channel,
                "actor": args.actor,
                "note": args.note,
            },
        )
        print(f"promoted {ref['asset_id']}@{ref['version']} -> {ref['channel']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
