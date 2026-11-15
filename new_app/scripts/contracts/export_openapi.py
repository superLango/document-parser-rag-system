#!/usr/bin/env python3
"""Export FastAPI OpenAPI specs into packages/contracts/openapi.

Usage (from new_app):
    python scripts/contracts/export_openapi.py            # regenerate both
    python scripts/contracts/export_openapi.py --check    # CI: fail on drift
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import yaml

APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = APP_ROOT / "packages" / "contracts" / "openapi"
for path in (APP_ROOT, APP_ROOT / "packages" / "contracts" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
TARGETS = {
    "public": "services.api_gateway.main:app",
    "internal": "services.orchestration.main:app",
}


def load_app(reference: str):
    module_name, attribute = reference.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


def dump(spec: dict) -> str:
    return yaml.safe_dump(
        spec, allow_unicode=True, sort_keys=True, width=120, default_flow_style=False
    )


def canonical(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=sorted(TARGETS))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()

    drifted: list[str] = []
    for name, reference in TARGETS.items():
        if args.only and name != args.only:
            continue
        spec = load_app(reference).openapi()
        target = args.out_dir / f"{name}.yaml"
        if args.check:
            if canonical(target) != spec:
                drifted.append(name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dump(spec), encoding="utf-8")
        print(f"wrote {target} ({len(spec.get('paths') or {})} paths)")

    if args.check:
        for name in drifted:
            print(
                f"contract drift: {name}.yaml is stale; "
                "run scripts/contracts/export_openapi.py and commit the result"
            )
        return 1 if drifted else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
