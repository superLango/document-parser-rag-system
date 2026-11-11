from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

NEW_APP = Path(__file__).resolve().parents[3]
RUNTIME_DIR = NEW_APP / "services" / "sandbox" / "runtime"
RECIPE_ROOT = NEW_APP / "services" / "recipe_registry" / "data" / "recipes"
TEMPLATE_ROOT = NEW_APP / "services" / "recipe_registry" / "data" / "templates"

OCR = {
    "schema_version": "ocr/1",
    "tables": [
        {
            "table_id": "T1",
            "page_no": 1,
            "profile": "mechanical_properties",
            "n_cols": 3,
            "header_paths": [
                ["牌号"],
                ["抗拉强度 Rm/MPa"],
                ["断后伸长率 A/%"],
            ],
            "rows": [
                ["牌号", "抗拉强度 Rm/MPa", "断后伸长率 A/%"],
                ["Q355B", "470", "22"],
                ["Q235B", "400", "26"],
            ],
        }
    ],
}


def read_recipe(recipe_id: str, version: str = "1.0.0") -> dict:
    path = RECIPE_ROOT / recipe_id / version / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_request(
    recipe_id: str = "mechanical_properties_v1",
    version: str = "1.0.0",
    timeout_seconds: int = 10,
) -> dict:
    return {
        "schema_version": "1.0",
        "trace_id": "trace-1",
        "run_id": "run-1",
        "document": {
            "document_id": "doc-1",
            "filename": "mechanical-basic.md",
            "storage_key": "documents/doc-1.md",
            "sha256": "0" * 64,
        },
        "ocr": {"storage_key": "runs/run-1/ocr.json", "sha256": "0" * 64},
        "assignments": [
            {"table_id": "T1", "recipe_id": recipe_id, "version": version}
        ],
        "recipe": {"recipe_id": recipe_id, "version": version},
        "template": {"template_id": "product_full", "version": "1.0.0"},
        "engine": {"api": "sandbox-engine/1", "version": "sandbox-engine/1"},
        "limits": {
            "cpu": 0.5,
            "memory_mb": 128,
            "pids": 64,
            "timeout_seconds": timeout_seconds,
            "tmpfs_mb": 16,
        },
    }


def run_engine(
    root: Path,
    request: dict,
    recipes: dict[str, dict],
    extra_files: dict[str, dict[str, str]] | None = None,
    ocr: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    work = root / "work"
    for name in ("input", "output", "recipes", "templates"):
        (work / name).mkdir(parents=True, exist_ok=True)
    (work / "input" / "ocr.json").write_text(
        json.dumps(ocr or OCR, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    (work / "input" / "request.json").write_text(
        json.dumps(request, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    for recipe_id, manifest in recipes.items():
        recipe_dir = work / "recipes" / recipe_id
        recipe_dir.mkdir(parents=True, exist_ok=True)
        (recipe_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        for relative, content in (extra_files or {}).get(recipe_id, {}).items():
            target = recipe_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    template = json.loads(
        (TEMPLATE_ROOT / "product_full" / "1.0.0" / "template.json").read_text(
            encoding="utf-8"
        )
    )
    (work / "templates" / "product_full").mkdir(parents=True, exist_ok=True)
    (work / "templates" / "product_full" / "template.json").write_text(
        json.dumps(template, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    env = os.environ.copy()
    env.update(
        {
            "HANSON_INPUT_DIR": str(work / "input"),
            "HANSON_OUTPUT_DIR": str(work / "output"),
            "HANSON_RECIPE_DIR": str(work / "recipes"),
            "HANSON_TEMPLATE_DIR": str(work / "templates"),
            "HANSON_REQUEST": str(work / "input" / "request.json"),
            "HANSON_ENGINE_VERSION": "sandbox-engine/1",
            "HANSON_ENGINE_IMAGE": "hanson-sandbox-runtime:test",
            "HANSON_ENGINE_IMAGE_DIGEST": "sha256:test",
            "HANSON_RUNTIME": "runc",
            "HANSON_EMIT_ENVELOPE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return subprocess.run(
        [sys.executable, "-B", str(RUNTIME_DIR / "runner.py")],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def read_outputs(work: Path) -> dict[str, bytes]:
    return {
        name: (work / name).read_bytes()
        for name in (
            "result.json",
            "records.json",
            "evidence.jsonl",
            "diagnostics.json",
            "metrics.json",
            "manifest.json",
        )
        if (work / name).exists()
    }


def parse_envelope(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.startswith("HANSON_ENVELOPE ")]
    assert lines, f"no envelope in stdout: {stdout[:500]}"
    return json.loads(lines[-1][len("HANSON_ENVELOPE ") :])
