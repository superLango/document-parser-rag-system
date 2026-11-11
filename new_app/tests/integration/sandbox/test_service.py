from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from hanson_contracts import ExecutionRequest, RuntimeInfo

from services.sandbox.config import Settings
from services.sandbox.executor import RawExecution
from services.sandbox.service import SandboxService

from .helpers import OCR, RUNTIME_DIR, make_request


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def ensure_ready(self) -> None:
        return None

    async def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        self.data[key] = data
        return key

    async def get_bytes(self, key: str) -> bytes:
        return self.data[key]

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class LocalRunnerExecutor:
    """Runs the real engine runtime as a local subprocess (no container)."""

    async def execute(self, workspace: Any) -> RawExecution:
        work = workspace.root
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
                "HANSON_EMIT_ENVELOPE": "0",
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        completed = subprocess.run(
            [sys.executable, "-B", str(RUNTIME_DIR / "runner.py")],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        files = {
            name: (work / "output" / name).read_bytes()
            for name in (
                "result.json",
                "records.json",
                "evidence.jsonl",
                "diagnostics.json",
                "metrics.json",
                "manifest.json",
            )
            if (work / "output" / name).exists()
        }
        return RawExecution(
            exit_code=completed.returncode,
            files=files,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=25,
            image_digest="sha256:test",
            runtime="runc",
            isolation={"network": "none", "user": "65534:65534"},
        )

    async def info(self) -> RuntimeInfo:
        return RuntimeInfo(executor="test", runtime="runc", available=True)

    async def close(self) -> None:
        return None


class StaticExecutor:
    def __init__(self, raw: RawExecution) -> None:
        self.raw = raw

    async def execute(self, workspace: Any) -> RawExecution:
        return self.raw

    async def info(self) -> RuntimeInfo:
        return RuntimeInfo(executor="test", runtime="runc", available=True)

    async def close(self) -> None:
        return None


class TamperedExecutor(LocalRunnerExecutor):
    async def execute(self, workspace: Any) -> RawExecution:
        raw = await super().execute(workspace)
        # Keep result.json schema-valid but change its digest.
        raw.files["result.json"] = raw.files["result.json"] + b" "
        return raw


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        executor="docker",
        workspace_root=tmp_path / "workspace",
        engine_image="hanson-sandbox-runtime:test",
        object_storage_endpoint="memory://",
    )


def _ocr_bytes() -> bytes:
    return json.dumps(OCR, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _request() -> ExecutionRequest:
    payload = make_request()
    payload["ocr"]["sha256"] = hashlib.sha256(_ocr_bytes()).hexdigest()
    return ExecutionRequest.model_validate(payload)


def _store() -> MemoryStore:
    store = MemoryStore()
    store.data["runs/run-1/ocr.json"] = _ocr_bytes()
    return store


def _execute(service: SandboxService, request: ExecutionRequest) -> Any:
    return asyncio.run(service.execute(request))


def test_service_success_writes_six_artifacts(tmp_path: Path) -> None:
    store = _store()
    service = SandboxService(_settings(tmp_path), store, LocalRunnerExecutor())
    result = _execute(service, _request())

    assert result.status == "succeeded"
    assert set(result.outputs) == {
        "result",
        "records",
        "evidence",
        "diagnostics",
        "metrics",
        "manifest",
    }
    assert result.manifest.engine_image_digest == "sha256:test"
    assert result.manifest.outputs["result.json"] == result.outputs["result"].sha256
    assert result.metrics.duration_ms == 25
    uploaded = [key for key in store.data if key.startswith("runs/run-1/sandbox/")]
    assert len(uploaded) == 6


def test_service_semantic_outputs_are_deterministic(tmp_path: Path) -> None:
    store = _store()
    service = SandboxService(_settings(tmp_path), store, LocalRunnerExecutor())
    first = _execute(service, _request())
    second = _execute(service, _request())

    first_prefix = first.outputs["result"].storage_key.rsplit("/", 1)[0]
    second_prefix = second.outputs["result"].storage_key.rsplit("/", 1)[0]
    for role in ("result", "records", "evidence", "diagnostics"):
        first_name = first.outputs[role].storage_key.rsplit("/", 1)[-1]
        second_name = second.outputs[role].storage_key.rsplit("/", 1)[-1]
        assert (
            store.data[f"{first_prefix}/{first_name}"]
            == store.data[f"{second_prefix}/{second_name}"]
        ), f"{role} is not deterministic"


def test_service_classifies_timeout(tmp_path: Path) -> None:
    raw = RawExecution(timed_out=True, exit_code=137, duration_ms=10)
    service = SandboxService(_settings(tmp_path), _store(), StaticExecutor(raw))
    result = _execute(service, _request())
    assert result.status == "timeout"
    assert result.error_code == "SANDBOX_TIMEOUT"
    assert "diagnostics" in result.outputs


def test_service_classifies_oom(tmp_path: Path) -> None:
    raw = RawExecution(oom=True, exit_code=137, duration_ms=10)
    service = SandboxService(_settings(tmp_path), _store(), StaticExecutor(raw))
    result = _execute(service, _request())
    assert result.status == "oom"
    assert result.error_code == "SANDBOX_OOM"


def test_service_classifies_nonzero_exit(tmp_path: Path) -> None:
    raw = RawExecution(exit_code=5, stderr="boom")
    service = SandboxService(_settings(tmp_path), _store(), StaticExecutor(raw))
    result = _execute(service, _request())
    assert result.status == "failed"
    assert result.error_code == "SANDBOX_EXIT_NONZERO"
    assert result.stderr == "boom"


def test_service_rejects_tampered_outputs(tmp_path: Path) -> None:
    service = SandboxService(_settings(tmp_path), _store(), TamperedExecutor())
    result = _execute(service, _request())
    assert result.status == "invalid_output"
    assert result.error_code == "SANDBOX_OUTPUT_DIGEST_MISMATCH"


def test_service_rejects_unknown_recipe(tmp_path: Path) -> None:
    store = _store()
    payload = make_request(recipe_id="missing_recipe")
    payload["ocr"]["sha256"] = hashlib.sha256(_ocr_bytes()).hexdigest()
    service = SandboxService(_settings(tmp_path), store, LocalRunnerExecutor())
    result = _execute(service, ExecutionRequest.model_validate(payload))
    assert result.status == "rejected"
    assert result.error_code == "SANDBOX_RECIPE_NOT_FOUND"
