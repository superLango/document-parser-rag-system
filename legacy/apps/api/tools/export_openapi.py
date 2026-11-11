"""Export the platform-plane OpenAPI contract.

Run from ``apps/api``:

    python tools/export_openapi.py

Writes ``packages/contracts/openapi.json``. Engine data routes are internal and
excluded by default; the engine API contract stays in ``metal-doc-agent``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
PROJECT = API_DIR.parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import main  # noqa: E402


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(PROJECT / "packages" / "contracts" / "openapi.json"),
    )
    args = parser.parse_args(argv)
    spec = main.app.openapi()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"paths={len(spec.get('paths', {}))} out={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
