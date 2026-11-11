import json
from pathlib import Path

import yaml

CONTRACTS = Path(__file__).resolve().parents[1] / "packages" / "contracts"


def test_openapi_contracts_are_valid_yaml() -> None:
    for name in ("public.yaml", "internal.yaml"):
        data = yaml.safe_load((CONTRACTS / "openapi" / name).read_text(encoding="utf-8"))
        assert data["openapi"].startswith("3.")
        assert data["paths"]


def test_json_schemas_are_valid_json() -> None:
    for name in ("recipe-package-2.0.json", "run-manifest-1.0.json"):
        data = json.loads((CONTRACTS / "schemas" / name).read_text(encoding="utf-8"))
        assert data["$schema"]
        assert data["title"]
