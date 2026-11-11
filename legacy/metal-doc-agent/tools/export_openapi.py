"""Export the live FastAPI OpenAPI contract to ``packages/contracts/openapi.json``.

The hand-written target draft lives in ``docs/openapi/standard-extraction.yaml``;
this export reflects what is actually implemented today.

Usage (from ``metal-doc-agent/``):
    python tools/export_openapi.py
    python tools/export_openapi.py --out ../packages/contracts/openapi.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT))

from metal_doc_agent.api import create_app  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(PROJECT / "packages" / "contracts" / "openapi.json"),
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    app = create_app(settings)
    spec = app.openapi()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"paths={len(spec.get('paths', {}))} out={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
