"""Sandbox engine runtime.

Runs inside the isolated engine container. Reads a prepared workspace, executes
either the built-in deterministic parser or a recipe entrypoint, and writes the
six contract artifacts to /work/output.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:  # resource is Unix-only; imported so the runtime can be smoke-tested on Windows.
    import resource
except ImportError:  # pragma: no cover - runtime image is Linux
    resource = None  # type: ignore[assignment]

from builtin import parse_table

INPUT_DIR = Path(os.environ.get("HANSON_INPUT_DIR", "/work/input"))
OUTPUT_DIR = Path(os.environ.get("HANSON_OUTPUT_DIR", "/work/output"))
RECIPE_DIR = Path(os.environ.get("HANSON_RECIPE_DIR", "/work/recipes"))
TEMPLATE_DIR = Path(os.environ.get("HANSON_TEMPLATE_DIR", "/work/templates"))
REQUEST_PATH = Path(os.environ.get("HANSON_REQUEST", str(INPUT_DIR / "request.json")))

OUTPUT_NAMES = (
    "result.json",
    "records.json",
    "evidence.jsonl",
    "diagnostics.json",
    "metrics.json",
    "manifest.json",
)
REQUIRED_FOR_ENTRYPOINT = ("result.json", "records.json", "evidence.jsonl", "diagnostics.json")
EXIT_INVALID_REQUEST = 2
EXIT_INVALID_OUTPUT = 3
EXIT_TIMEOUT = 124


def canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_payload(name: str, payload: Any) -> None:
    (OUTPUT_DIR / name).write_bytes((canonical(payload) + "\n").encode("utf-8"))


def write_jsonl(name: str, items: list[dict[str, Any]]) -> None:
    lines = "".join(canonical(item) + "\n" for item in items)
    (OUTPUT_DIR / name).write_bytes(lines.encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(recipe_id: str) -> dict[str, Any] | None:
    path = RECIPE_DIR / recipe_id / "manifest.json"
    if not path.exists():
        return None
    return read_json(path)


def find_entrypoint(
    primary: dict[str, Any] | None,
    assigned: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    ordered = ([primary] if primary else []) + assigned
    for manifest in ordered:
        if not manifest:
            continue
        entrypoint = manifest.get("entrypoint")
        if isinstance(entrypoint, str):
            entrypoint = {"type": "python", "path": entrypoint}
        if isinstance(entrypoint, dict) and entrypoint.get("path"):
            return manifest, entrypoint
    return None


def run_entrypoint(
    manifest: dict[str, Any],
    entrypoint: dict[str, Any],
    request: dict[str, Any],
) -> int:
    recipe_id = str(manifest.get("recipe_id") or "")
    recipe_path = RECIPE_DIR / recipe_id
    entry_rel = str(entrypoint.get("path") or "")
    entry_path = (recipe_path / entry_rel).resolve()
    if not entry_path.is_relative_to(recipe_path.resolve()):
        print(f"HANSON_INVALID_OUTPUT: entrypoint escapes recipe dir: {entry_rel}", file=sys.stderr)
        return EXIT_INVALID_OUTPUT
    if not entry_path.exists():
        print(f"HANSON_INVALID_OUTPUT: entrypoint missing: {entry_rel}", file=sys.stderr)
        return EXIT_INVALID_OUTPUT

    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "TZ": "UTC",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(recipe_path),
        "HANSON_REQUEST": str(REQUEST_PATH),
        "HANSON_INPUT_DIR": str(INPUT_DIR),
        "HANSON_OUTPUT_DIR": str(OUTPUT_DIR),
        "HANSON_RECIPE_DIR": str(RECIPE_DIR),
        "HANSON_RECIPE_ID": recipe_id,
        "HANSON_RECIPE_VERSION": str(manifest.get("version") or ""),
        "HANSON_TEMPLATE_DIR": str(TEMPLATE_DIR),
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-B", str(entry_path)],
            cwd=str(OUTPUT_DIR.parent),
            env=env,
            check=False,
        )
    except OSError as exc:
        print(f"HANSON_ENTRYPOINT_ERROR: {exc}", file=sys.stderr)
        return 1
    return completed.returncode


def run_builtin(request: dict[str, Any], diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    ocr_path = INPUT_DIR / "ocr.json"
    ocr = read_json(ocr_path)
    tables = ocr.get("tables") or []
    assignments = {item.get("table_id"): item for item in request.get("assignments") or []}
    primary = load_manifest(str((request.get("recipe") or {}).get("recipe_id") or ""))

    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    table_summaries: list[dict[str, Any]] = []
    used_recipes: dict[tuple[str, str], dict[str, Any]] = {}

    for table in tables:
        table_id = str(table.get("table_id") or "")
        assignment = assignments.get(table_id)
        recipe_id = str(
            (assignment or {}).get("recipe_id")
            or (request.get("recipe") or {}).get("recipe_id")
            or ""
        )
        manifest = load_manifest(recipe_id) if recipe_id else primary
        if assignment is None and recipe_id:
            diagnostics.append(
                {
                    "code": "RECIPE_FALLBACK",
                    "message": f"table {table_id} uses fallback recipe {recipe_id}",
                    "severity": "info",
                    "detail": {"table_id": table_id, "recipe_id": recipe_id},
                }
            )
        table_records, table_evidence, summary = parse_table(
            table, manifest, assignment, diagnostics
        )
        records.extend(table_records)
        evidence.extend(table_evidence)
        table_summaries.append(summary)
        if manifest:
            key = (str(manifest.get("recipe_id") or ""), str(manifest.get("version") or ""))
            used_recipes[key] = {
                "recipe_id": key[0],
                "version": key[1],
                "profile": manifest.get("profile"),
            }

    records.sort(key=lambda item: (item["page_no"], item["table_id"], item["row_index"]))
    evidence.sort(key=lambda item: (item["page_no"], item["table_id"], item["row_index"]))
    table_summaries.sort(key=lambda item: (item["page_no"], item["table_id"]))

    template = {
        "template_id": (request.get("template") or {}).get("template_id"),
        "version": (request.get("template") or {}).get("version"),
    }
    result = {
        "schema_version": "sandbox-result/1",
        "status": "succeeded",
        "document": request.get("document") or {},
        "template": template,
        "recipes": [used_recipes[key] for key in sorted(used_recipes)],
        "tables": table_summaries,
        "stats": {
            "tables": len(table_summaries),
            "records": len(records),
            "diagnostics": len(diagnostics),
        },
        "outputs": list(OUTPUT_NAMES),
    }
    write_payload("result.json", result)
    write_payload(
        "records.json",
        {"schema_version": "sandbox-records/1", "records": records},
    )
    write_jsonl("evidence.jsonl", evidence)
    write_payload(
        "diagnostics.json",
        {"schema_version": "sandbox-diagnostics/1", "diagnostics": diagnostics},
    )
    return {"tables": len(table_summaries), "records": len(records)}


def finalize_entrypoint(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    for name in REQUIRED_FOR_ENTRYPOINT:
        if not (OUTPUT_DIR / name).exists():
            diagnostics.append(
                {
                    "code": "ENTRYPOINT_OUTPUT_MISSING",
                    "message": f"entrypoint did not write {name}",
                    "severity": "error",
                    "detail": {"file": name},
                }
            )
    diagnostics_path = OUTPUT_DIR / "diagnostics.json"
    if diagnostics_path.exists():
        try:
            existing = read_json(diagnostics_path).get("diagnostics") or []
        except (ValueError, AttributeError):
            existing = []
        diagnostics = list(existing) + diagnostics
    write_payload(
        "diagnostics.json",
        {"schema_version": "sandbox-diagnostics/1", "diagnostics": diagnostics},
    )
    if any(item["severity"] == "error" for item in diagnostics):
        return {"tables": 0, "records": 0}
    records_payload = read_json(OUTPUT_DIR / "records.json")
    if isinstance(records_payload, list):
        records = records_payload
    elif isinstance(records_payload, dict):
        records = records_payload.get("records") or []
    else:
        records = []
    return {"tables": 0, "records": len(records)}


def append_timings(
    started: float,
    stats: dict[str, Any],
    request: dict[str, Any],
    input_hashes: dict[str, str],
) -> None:
    duration_ms = int((time.monotonic() - started) * 1000)
    peak_mb = 0
    if resource is not None:
        usage_self = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        usage_child = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        peak_mb = int(max(usage_self, usage_child) / 1024)
    limits = request.get("limits") or {}
    write_payload(
        "metrics.json",
        {
            "schema_version": "sandbox-metrics/1",
            "duration_ms": duration_ms,
            "peak_memory_mb": peak_mb,
            "tables": int(stats.get("tables") or 0),
            "records": int(stats.get("records") or 0),
            "memory_limit_mb": int(limits.get("memory_mb") or 0),
            "cpu_limit": float(limits.get("cpu") or 0.0),
            "timeout_seconds": int(limits.get("timeout_seconds") or 0),
        },
    )
    input_hashes = dict(input_hashes)
    inputs = {"request": input_hashes.get("request", "")}
    if (INPUT_DIR / "ocr.json").exists():
        inputs["ocr"] = sha256_bytes((INPUT_DIR / "ocr.json").read_bytes())
    if (INPUT_DIR / "document.json").exists():
        inputs["document"] = sha256_bytes((INPUT_DIR / "document.json").read_bytes())

    outputs = {
        name: sha256_bytes((OUTPUT_DIR / name).read_bytes())
        for name in OUTPUT_NAMES
        if name != "manifest.json" and (OUTPUT_DIR / name).exists()
    }
    isolation: dict[str, Any] = {}
    try:
        isolation = json.loads(os.environ.get("HANSON_ISOLATION") or "{}")
    except ValueError:
        isolation = {}
    write_payload(
        "manifest.json",
        {
            "schema_version": "sandbox-manifest/1",
            "engine": {
                "api": (request.get("engine") or {}).get("api"),
                "version": os.environ.get("HANSON_ENGINE_VERSION", ""),
                "image": os.environ.get("HANSON_ENGINE_IMAGE", ""),
                "digest": os.environ.get("HANSON_ENGINE_IMAGE_DIGEST", ""),
                "runtime": os.environ.get("HANSON_RUNTIME", ""),
            },
            "recipe": request.get("recipe") or {},
            "recipes": request.get("assignments") or [],
            "template": request.get("template") or {},
            "inputs": inputs,
            "outputs": outputs,
            "isolation": isolation,
        },
    )


def emit_envelope(status: str, error_code: str, message: str) -> None:
    if os.environ.get("HANSON_EMIT_ENVELOPE") != "1":
        return
    limit = int(os.environ.get("HANSON_MAX_ENVELOPE_BYTES", "8388608"))
    files: dict[str, str] = {}
    total = 0
    for name in OUTPUT_NAMES:
        path = OUTPUT_DIR / name
        if not path.exists():
            continue
        data = path.read_bytes()
        total += len(data)
        if total > limit:
            status = "invalid_output"
            error_code = "SANDBOX_OUTPUT_TOO_LARGE"
            message = f"outputs exceed envelope limit {limit} bytes"
            files = {}
            break
        files[name] = base64.b64encode(data).decode("ascii")
    payload = {
        "schema_version": "sandbox-envelope/1",
        "status": status,
        "error_code": error_code or None,
        "message": message,
        "files": files,
    }
    print("HANSON_ENVELOPE " + canonical(payload), flush=True)


def main() -> int:
    started = time.monotonic()
    diagnostics: list[dict[str, Any]] = []
    if not REQUEST_PATH.exists():
        print(f"HANSON_INVALID_REQUEST: missing {REQUEST_PATH}", file=sys.stderr)
        emit_envelope("rejected", "SANDBOX_REQUEST_INVALID", "missing request")
        return EXIT_INVALID_REQUEST
    request_bytes = REQUEST_PATH.read_bytes()
    try:
        request = json.loads(request_bytes)
    except ValueError as exc:
        print(f"HANSON_INVALID_REQUEST: {exc}", file=sys.stderr)
        emit_envelope("rejected", "SANDBOX_REQUEST_INVALID", str(exc))
        return EXIT_INVALID_REQUEST

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_hashes = {"request": sha256_bytes(request_bytes)}

    primary = load_manifest(str((request.get("recipe") or {}).get("recipe_id") or ""))
    assigned = []
    seen: set[str] = set()
    for item in request.get("assignments") or []:
        recipe_id = str(item.get("recipe_id") or "")
        if recipe_id and recipe_id not in seen:
            seen.add(recipe_id)
            manifest = load_manifest(recipe_id)
            if manifest:
                assigned.append(manifest)

    entry = find_entrypoint(primary, assigned)
    if entry is not None:
        manifest, entrypoint = entry
        diagnostics.append(
            {
                "code": "ENTRYPOINT_USED",
                "message": f"executed entrypoint for {manifest.get('recipe_id')}",
                "severity": "info",
                "detail": {"entrypoint": entrypoint.get("path")},
            }
        )
        exit_code = run_entrypoint(manifest, entrypoint, request)
        if exit_code != 0:
            write_payload(
                "diagnostics.json",
                {"schema_version": "sandbox-diagnostics/1", "diagnostics": diagnostics},
            )
            emit_envelope(
                "timeout" if exit_code == EXIT_TIMEOUT else "failed",
                "SANDBOX_TIMEOUT" if exit_code == EXIT_TIMEOUT else "SANDBOX_ENTRYPOINT_FAILED",
                f"entrypoint exited with code {exit_code}",
            )
            return exit_code
        stats = finalize_entrypoint(diagnostics)
        if any(item["severity"] == "error" for item in diagnostics):
            append_timings(started, stats, request, input_hashes)
            emit_envelope(
                "invalid_output", "SANDBOX_INVALID_OUTPUT", "entrypoint outputs are incomplete"
            )
            return EXIT_INVALID_OUTPUT
    else:
        try:
            stats = run_builtin(request, diagnostics)
        except Exception as exc:  # noqa: BLE001 - surface any engine failure to the host
            print(f"HANSON_ENGINE_ERROR: {exc}", file=sys.stderr)
            write_payload(
                "diagnostics.json",
                {
                    "schema_version": "sandbox-diagnostics/1",
                    "diagnostics": diagnostics
                    + [
                        {
                            "code": "ENGINE_ERROR",
                            "message": str(exc),
                            "severity": "error",
                            "detail": {},
                        }
                    ],
                },
            )
            emit_envelope("failed", "SANDBOX_ENGINE_ERROR", str(exc))
            return 1

    append_timings(started, stats, request, input_hashes)
    emit_envelope("succeeded", "", "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
