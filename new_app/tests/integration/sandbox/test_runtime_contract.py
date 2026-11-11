from __future__ import annotations

import json
from pathlib import Path

from .helpers import (
    make_request,
    parse_envelope,
    read_outputs,
    read_recipe,
    run_engine,
)


def test_builtin_engine_produces_contract_artifacts(tmp_path: Path) -> None:
    request = make_request()
    completed = run_engine(tmp_path, request, {"mechanical_properties_v1": read_recipe(
        "mechanical_properties_v1"
    )})
    assert completed.returncode == 0, completed.stderr
    outputs = read_outputs(tmp_path / "work" / "output")
    assert set(outputs) == {
        "result.json",
        "records.json",
        "evidence.jsonl",
        "diagnostics.json",
        "metrics.json",
        "manifest.json",
    }

    result = json.loads(outputs["result.json"])
    records = json.loads(outputs["records.json"])["records"]
    evidence = [json.loads(line) for line in outputs["evidence.jsonl"].splitlines()]
    manifest = json.loads(outputs["manifest.json"])

    assert result["status"] == "succeeded"
    assert result["stats"]["records"] == 2
    assert [item["grade"] for item in records] == ["Q355B", "Q235B"]
    assert records[0]["properties"]["Rm"]["value"] == 470.0
    assert records[0]["properties"]["Rm"]["unit"] == "MPa"
    assert len(evidence) == 2
    assert manifest["engine"]["runtime"] == "runc"
    assert manifest["recipe"]["recipe_id"] == "mechanical_properties_v1"
    assert set(manifest["outputs"]) == {
        "result.json",
        "records.json",
        "evidence.jsonl",
        "diagnostics.json",
        "metrics.json",
    }

    envelope = parse_envelope(completed.stdout)
    assert envelope["status"] == "succeeded"
    assert "result.json" in envelope["files"]


def test_builtin_engine_is_deterministic(tmp_path: Path) -> None:
    recipe = read_recipe("mechanical_properties_v1")
    first = run_engine(tmp_path / "first", make_request(), {"mechanical_properties_v1": recipe})
    second = run_engine(tmp_path / "second", make_request(), {"mechanical_properties_v1": recipe})
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    left = read_outputs(tmp_path / "first" / "work" / "output")
    right = read_outputs(tmp_path / "second" / "work" / "output")
    # metrics.json measures wall-clock time, and manifest.json hashes metrics.json;
    # both are excluded. All semantic artifacts must be byte-identical.
    for name in ("result.json", "records.json", "evidence.jsonl", "diagnostics.json"):
        assert left[name] == right[name], f"{name} is not deterministic"


def test_entrypoint_recipe_is_supported(tmp_path: Path) -> None:
    manifest = {
        "schema_version": "2.0",
        "recipe_id": "entrypoint_v1",
        "version": "1.0.0",
        "engine_api": "recipe-engine/1",
        "profile": "custom",
        "entrypoint": {"type": "python", "path": "entry.py"},
    }
    entry = """\
import json
import os
from pathlib import Path

out = Path(os.environ["HANSON_OUTPUT_DIR"])
out.joinpath("result.json").write_text(json.dumps({
    "schema_version": "sandbox-result/1",
    "status": "succeeded",
    "stats": {"records": 1},
}, sort_keys=True) + "\\n")
out.joinpath("records.json").write_text(json.dumps({
    "schema_version": "sandbox-records/1",
    "records": [{"record_id": "E1", "table_id": "T1", "grade": "GH4169", "properties": {}}],
}, sort_keys=True) + "\\n")
out.joinpath("evidence.jsonl").write_text(
    json.dumps({"evidence_id": "E1"}, sort_keys=True) + "\\n"
)
out.joinpath("diagnostics.json").write_text(json.dumps({
    "schema_version": "sandbox-diagnostics/1",
    "diagnostics": [],
}, sort_keys=True) + "\\n")
"""
    request = make_request(recipe_id="entrypoint_v1")
    completed = run_engine(
        tmp_path,
        request,
        {"entrypoint_v1": manifest},
        extra_files={"entrypoint_v1": {"entry.py": entry}},
    )
    assert completed.returncode == 0, completed.stderr
    outputs = read_outputs(tmp_path / "work" / "output")
    diagnostics = json.loads(outputs["diagnostics.json"])["diagnostics"]
    assert any(item["code"] == "ENTRYPOINT_USED" for item in diagnostics)
    metrics = json.loads(outputs["metrics.json"])
    assert metrics["records"] == 1


def test_entrypoint_missing_outputs_is_invalid(tmp_path: Path) -> None:
    manifest = {
        "schema_version": "2.0",
        "recipe_id": "entrypoint_v1",
        "version": "1.0.0",
        "engine_api": "recipe-engine/1",
        "profile": "custom",
        "entrypoint": {"type": "python", "path": "entry.py"},
    }
    completed = run_engine(
        tmp_path,
        make_request(recipe_id="entrypoint_v1"),
        {"entrypoint_v1": manifest},
        extra_files={"entrypoint_v1": {"entry.py": "print('no outputs')\n"}},
    )
    assert completed.returncode == 3
    envelope = parse_envelope(completed.stdout)
    assert envelope["status"] == "invalid_output"
    assert envelope["error_code"] == "SANDBOX_INVALID_OUTPUT"
