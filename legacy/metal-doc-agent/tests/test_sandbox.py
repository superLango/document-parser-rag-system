"""Sandbox execution: every job imports the current on-disk rule code."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from metal_doc_agent.jobs import JobStore
from metal_doc_agent.sandbox_exec import (
    child_env,
    run_job_sandbox,
    run_pipeline_sandbox,
    sandbox_enabled,
)
from metal_doc_agent.settings import Settings
from metal_doc_agent.worker import _mark_failed

AGENT_ROOT = Path(__file__).resolve().parents[1]

MD = """# Page 1

# 测试标准

## Table

<table border="1">
<tr><td rowspan="2">牌号</td><td colspan="2">力学性能(不小于)</td></tr>
<tr><td>抗拉强度Rm/MPa</td><td>断后伸长率A/%</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
</table>
"""


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = dataclasses.replace(
        Settings.from_env(),
        project_root=AGENT_ROOT,
        data_dir=tmp_path / "data",
        ocr_backend="mock",
        extractor_backend="mock",
    )
    return dataclasses.replace(base, **overrides) if overrides else base


def test_pipeline_runs_in_a_child_process(tmp_path):
    source = tmp_path / "doc.md"
    source.write_text(MD, encoding="utf-8")
    out = tmp_path / "out"
    settings = _settings(tmp_path)

    ok, detail = run_pipeline_sandbox(
        settings, source, out, coverage_template="product_full"
    )
    assert ok, detail
    assert (out / "result.json").exists()
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["records"]


def test_sandbox_reports_pipeline_failure(tmp_path):
    settings = _settings(tmp_path)
    ok, detail = run_pipeline_sandbox(
        settings, tmp_path / "missing.md", tmp_path / "out"
    )
    assert not ok
    assert detail


def test_child_env_drops_selfheal_secrets(monkeypatch):
    monkeypatch.setenv("SELFHEAL_MODEL_URL", "http://example.invalid")
    monkeypatch.setenv("HANSON_SECRET_KEY", "secret")
    monkeypatch.setenv("QWEN_BASE_URL", "http://model.example/v1")
    env = child_env()
    assert "SELFHEAL_MODEL_URL" not in env
    assert "HANSON_SECRET_KEY" not in env
    assert env["QWEN_BASE_URL"] == "http://model.example/v1"
    assert env["METAL_DOC_SANDBOX_CHILD"] == "1"


def test_sandbox_flag_can_be_disabled(tmp_path):
    assert sandbox_enabled(_settings(tmp_path)) is True
    assert sandbox_enabled(_settings(tmp_path, sandbox=False)) is False


def _enqueue(store: JobStore, source: Path):
    return store.reserve(
        idempotency_key=source.name,
        source_name=source.name,
        source_sha256="0" * 64,
        doc_path=str(source),
        options={"template": "product_full", "ocr": "mock", "extractor": "mock"},
    )[0]


def test_job_sandbox_runs_and_updates_state(tmp_path):
    source = tmp_path / "doc.md"
    source.write_text(MD, encoding="utf-8")
    settings = _settings(tmp_path)
    store = JobStore(tmp_path / "data" / "jobs")
    state = _enqueue(store, source)

    ok, detail = run_job_sandbox(settings, store.root, state.job_id)
    assert ok, detail
    finished = store.get(state.job_id)
    assert finished is not None
    assert finished.status in {"succeeded", "review", "failed"}
    assert Path(finished.out_dir, "result.json").exists()


def test_failed_child_marks_job_failed(tmp_path):
    settings = _settings(tmp_path)
    store = JobStore(tmp_path / "data" / "jobs")
    source = tmp_path / "doc.md"
    source.write_text(MD, encoding="utf-8")
    state = _enqueue(store, source)

    _mark_failed(store, state.job_id, "sandbox exploded")
    failed = store.get(state.job_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.failure_code == "engine_failed"
    assert "sandbox exploded" in (failed.error or "")


def test_settings_default_sandbox_enabled(monkeypatch):
    monkeypatch.delenv("METAL_DOC_SANDBOX", raising=False)
    assert Settings.from_env().sandbox is True
