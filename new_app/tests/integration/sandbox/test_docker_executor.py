from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from hanson_contracts import ExecutionRequest

from services.sandbox.config import Settings
from services.sandbox.docker_executor import DockerExecutor
from services.sandbox.workspace import Workspace, canonical_bytes, sha256

SOCKET = Path("/var/run/docker.sock")
pytestmark = pytest.mark.skipif(
    not SOCKET.exists(), reason="docker socket is not available"
)

OCR = {"schema_version": "ocr/1", "tables": []}


def _request(timeout: int = 60, memory_mb: int = 128) -> ExecutionRequest:
    payload = {
        "schema_version": "1.0",
        "trace_id": "docker-test",
        "run_id": "docker-test",
        "document": {"document_id": "d", "filename": "f.md", "sha256": "0" * 64},
        "ocr": {"storage_key": "runs/docker-test/ocr.json", "sha256": "0" * 64},
        "assignments": [
            {
                "table_id": "T1",
                "recipe_id": "entrypoint_v1",
                "version": "1.0.0",
            }
        ],
        "recipe": {"recipe_id": "entrypoint_v1", "version": "1.0.0"},
        "template": {"template_id": "product_full", "version": "1.0.0"},
        "engine": {"api": "sandbox-engine/1", "version": "sandbox-engine/1"},
        "limits": {
            "cpu": 0.5,
            "memory_mb": memory_mb,
            "pids": 64,
            "timeout_seconds": timeout,
            "tmpfs_mb": 16,
        },
    }
    return ExecutionRequest.model_validate(payload)


def _workspace(root: Path, entry: str, timeout: int = 60, memory_mb: int = 128) -> Workspace:
    root.mkdir(parents=True, exist_ok=True)
    request = _request(timeout, memory_mb)
    files = {
        "input/request.json": canonical_bytes(request.model_dump(mode="json")),
        "input/ocr.json": canonical_bytes(OCR),
        "input/document.json": canonical_bytes({"document_id": "d"}),
        "recipes/entrypoint_v1/manifest.json": canonical_bytes(
            {
                "schema_version": "2.0",
                "recipe_id": "entrypoint_v1",
                "version": "1.0.0",
                "engine_api": "recipe-engine/1",
                "profile": "custom",
                "entrypoint": {"type": "python", "path": "entry.py"},
            }
        ),
        "recipes/entrypoint_v1/entry.py": entry.encode("utf-8"),
        "templates/product_full/template.json": canonical_bytes({"template_id": "product_full"}),
    }
    return Workspace(
        root=root,
        request=request,
        files=files,
        input_hashes={"request": sha256(files["input/request.json"])},
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        executor="docker",
        runtime="runc",
        engine_image="hanson-sandbox-runtime:local",
        workspace_root=tmp_path / "sandbox",
        object_storage_endpoint="memory://",
    )


ISOLATION_ENTRY = """\
import json
import os
import socket
from pathlib import Path

checks = {"uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid()}
try:
    connection = socket.create_connection(("1.1.1.1", 80), timeout=2)
    connection.close()
    checks["network"] = "reachable"
except OSError as exc:
    checks["network"] = "blocked:" + type(exc).__name__

for name, path in (
    ("engine_write", "/engine/evil"),
    ("input_write", "/input/evil"),
    ("recipes_write", "/recipes/evil"),
    ("root_write", "/evil"),
):
    try:
        Path(path).write_text("x")
        checks[name] = "allowed"
    except OSError as exc:
        checks[name] = "denied:" + type(exc).__name__

probe = Path("/output/probe.txt")
try:
    probe.write_text("x")
    checks["output_write"] = "allowed"
    probe.unlink()
except OSError as exc:
    checks["output_write"] = "denied:" + type(exc).__name__

out = Path("/output")
out.joinpath("result.json").write_text(json.dumps({
    "schema_version": "sandbox-result/1",
    "status": "succeeded",
    "stats": {"records": 0},
}, sort_keys=True) + "\\n")
out.joinpath("records.json").write_text(json.dumps({
    "schema_version": "sandbox-records/1",
    "records": [],
}, sort_keys=True) + "\\n")
out.joinpath("evidence.jsonl").write_text("")
out.joinpath("diagnostics.json").write_text(json.dumps({
    "schema_version": "sandbox-diagnostics/1",
    "diagnostics": [{
        "code": "ISOLATION",
        "message": "isolation probe",
        "severity": "info",
        "detail": checks,
    }],
}, sort_keys=True) + "\\n")
"""


def test_docker_isolation_probe(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, ISOLATION_ENTRY)
    executor = DockerExecutor(_settings(tmp_path))
    raw = asyncio.run(executor.execute(workspace))
    assert raw.exit_code == 0, raw.stderr
    diagnostics = json.loads(raw.files["diagnostics.json"])["diagnostics"]
    detail = next(item["detail"] for item in diagnostics if item["code"] == "ISOLATION")
    assert detail["uid"] == 65534
    assert detail["euid"] != 0
    assert detail["network"].startswith("blocked")
    assert detail["engine_write"].startswith("denied")
    assert detail["input_write"].startswith("denied")
    assert detail["recipes_write"].startswith("denied")
    assert detail["root_write"].startswith("denied")
    assert detail["output_write"] == "allowed"
    assert raw.isolation["network"] == "none"
    assert raw.isolation["read_only_rootfs"] is True
    assert raw.isolation["cap_drop"] == ["ALL"]


def test_docker_timeout_is_classified(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "import time\ntime.sleep(60)\n", timeout=2)
    executor = DockerExecutor(_settings(tmp_path))
    raw = asyncio.run(executor.execute(workspace))
    assert raw.timed_out is True
    assert raw.duration_ms < 20_000


def test_docker_oom_is_classified(tmp_path: Path) -> None:
    entry = """\
chunks = []
while True:
    chunks.append(bytearray(20 * 1024 * 1024))
"""
    workspace = _workspace(tmp_path, entry, timeout=60, memory_mb=64)
    executor = DockerExecutor(_settings(tmp_path))
    raw = asyncio.run(executor.execute(workspace))
    assert raw.oom is True


def test_docker_nonzero_exit(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "raise SystemExit(5)\n")
    executor = DockerExecutor(_settings(tmp_path))
    raw = asyncio.run(executor.execute(workspace))
    assert raw.exit_code == 5
