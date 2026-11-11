from __future__ import annotations

import hashlib
import json

import pytest

from services.sandbox.validation import ValidationError, validate_outputs


def _canonical(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _valid_files() -> dict[str, bytes]:
    result = _canonical(
        {
            "schema_version": "sandbox-result/1",
            "status": "succeeded",
            "stats": {"records": 1},
        }
    )
    records = _canonical(
        {
            "schema_version": "sandbox-records/1",
            "records": [
                {
                    "record_id": "T1-R1",
                    "table_id": "T1",
                    "grade": "Q355B",
                    "properties": {"Rm": {"value": 470.0, "unit": "MPa"}},
                }
            ],
        }
    )
    evidence = b'{"evidence_id":"T1-R1","table_id":"T1"}\n'
    diagnostics = _canonical(
        {"schema_version": "sandbox-diagnostics/1", "diagnostics": []}
    )
    metrics = _canonical(
        {"schema_version": "sandbox-metrics/1", "duration_ms": 12, "records": 1}
    )
    files = {
        "result.json": result,
        "records.json": records,
        "evidence.jsonl": evidence,
        "diagnostics.json": diagnostics,
        "metrics.json": metrics,
    }
    manifest = _canonical(
        {
            "schema_version": "sandbox-manifest/1",
            "outputs": {
                name: hashlib.sha256(data).hexdigest() for name, data in files.items()
            },
        }
    )
    files["manifest.json"] = manifest
    return files


def test_valid_outputs_pass() -> None:
    validated = validate_outputs(_valid_files(), 1024 * 1024, 16)
    assert validated.records == 1
    assert set(validated.digests) == set(_valid_files())


def test_digest_mismatch_is_rejected() -> None:
    files = _valid_files()
    # A trailing space keeps metrics.json valid JSON but changes its digest.
    files["metrics.json"] = files["metrics.json"] + b" "
    with pytest.raises(ValidationError) as exc:
        validate_outputs(files, 1024 * 1024, 16)
    assert exc.value.code == "SANDBOX_OUTPUT_DIGEST_MISMATCH"


def test_missing_artifact_is_rejected() -> None:
    files = _valid_files()
    files.pop("evidence.jsonl")
    with pytest.raises(ValidationError) as exc:
        validate_outputs(files, 1024 * 1024, 16)
    assert exc.value.code == "SANDBOX_OUTPUT_INVALID"


def test_record_count_mismatch_is_rejected() -> None:
    files = _valid_files()
    manifest = json.loads(files["manifest.json"])
    records = json.loads(files["records.json"])
    records["records"] = []
    files["records.json"] = _canonical(records)
    manifest["outputs"]["records.json"] = hashlib.sha256(files["records.json"]).hexdigest()
    files["manifest.json"] = _canonical(manifest)
    with pytest.raises(ValidationError) as exc:
        validate_outputs(files, 1024 * 1024, 16)
    assert exc.value.code == "SANDBOX_OUTPUT_INVALID"


def test_size_limit_is_enforced() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_outputs(_valid_files(), 32, 16)
    assert exc.value.code == "SANDBOX_OUTPUT_LIMIT_EXCEEDED"
