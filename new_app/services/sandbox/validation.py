"""Artifact validation: schema, digests and cross-file consistency."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

REQUIRED_FILES = (
    "result.json",
    "records.json",
    "evidence.jsonl",
    "diagnostics.json",
    "metrics.json",
    "manifest.json",
)
ROLE_CONTENT_TYPES = {
    "result": "application/json",
    "records": "application/json",
    "evidence": "application/x-ndjson",
    "diagnostics": "application/json",
    "metrics": "application/json",
    "manifest": "application/json",
}


class ValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ValidatedOutputs:
    files: dict[str, bytes]
    digests: dict[str, str]
    records: int
    diagnostics: list[dict[str, Any]]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(name: str, data: bytes) -> Any:
    try:
        return json.loads(data)
    except ValueError as exc:
        raise ValidationError("SANDBOX_OUTPUT_INVALID", f"{name} is not valid JSON: {exc}") from exc


def _require_object(name: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("SANDBOX_OUTPUT_INVALID", f"{name} must be a JSON object")
    return payload


def _require_list(name: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError("SANDBOX_OUTPUT_INVALID", f"{name} must be a JSON array")
    return value


def validate_outputs(
    files: dict[str, bytes],
    max_output_bytes: int,
    max_output_files: int,
) -> ValidatedOutputs:
    if len(files) > max_output_files:
        raise ValidationError(
            "SANDBOX_OUTPUT_LIMIT_EXCEEDED",
            f"too many output files: {len(files)} > {max_output_files}",
        )
    total = sum(len(data) for data in files.values())
    if total > max_output_bytes:
        raise ValidationError(
            "SANDBOX_OUTPUT_LIMIT_EXCEEDED",
            f"outputs exceed {max_output_bytes} bytes: {total}",
        )
    missing = sorted(set(REQUIRED_FILES) - set(files))
    extra = sorted(set(files) - set(REQUIRED_FILES))
    if missing or extra:
        raise ValidationError(
            "SANDBOX_OUTPUT_INVALID",
            f"output set mismatch: missing={missing} extra={extra}",
        )

    result = _require_object("result.json", _json("result.json", files["result.json"]))
    if result.get("schema_version") != "sandbox-result/1":
        raise ValidationError("SANDBOX_OUTPUT_INVALID", "result.json schema_version mismatch")
    if result.get("status") != "succeeded":
        raise ValidationError("SANDBOX_OUTPUT_INVALID", "result.json status is not succeeded")
    stats = _require_object("result.json stats", result.get("stats"))
    if not isinstance(stats.get("records"), int):
        raise ValidationError("SANDBOX_OUTPUT_INVALID", "result.json stats.records is missing")

    records_payload = _require_object(
        "records.json", _json("records.json", files["records.json"])
    )
    if records_payload.get("schema_version") != "sandbox-records/1":
        raise ValidationError("SANDBOX_OUTPUT_INVALID", "records.json schema_version mismatch")
    records = _require_list("records.json records", records_payload.get("records"))
    for item in records:
        record = _require_object("record", item)
        for field in ("record_id", "table_id", "grade"):
            if not isinstance(record.get(field), str):
                raise ValidationError(
                    "SANDBOX_OUTPUT_INVALID", f"record missing string field {field}"
                )
        if not isinstance(record.get("properties"), dict):
            raise ValidationError("SANDBOX_OUTPUT_INVALID", "record.properties must be an object")
    if stats["records"] != len(records):
        raise ValidationError(
            "SANDBOX_OUTPUT_INVALID",
            f"result stats.records={stats['records']} but records.json has {len(records)}",
        )

    evidence_lines = 0
    for line_no, line in enumerate(files["evidence.jsonl"].splitlines(), start=1):
        if not line.strip():
            continue
        try:
            evidence = json.loads(line)
        except ValueError as exc:
            raise ValidationError(
                "SANDBOX_OUTPUT_INVALID",
                f"evidence.jsonl line {line_no} is not JSON: {exc}",
            ) from exc
        if not isinstance(evidence, dict) or not isinstance(evidence.get("evidence_id"), str):
            raise ValidationError(
                "SANDBOX_OUTPUT_INVALID",
                f"evidence.jsonl line {line_no} lacks evidence_id",
            )
        evidence_lines += 1

    diagnostics_payload = _require_object(
        "diagnostics.json", _json("diagnostics.json", files["diagnostics.json"])
    )
    if diagnostics_payload.get("schema_version") != "sandbox-diagnostics/1":
        raise ValidationError(
            "SANDBOX_OUTPUT_INVALID", "diagnostics.json schema_version mismatch"
        )
    diagnostics = _require_list(
        "diagnostics.json diagnostics", diagnostics_payload.get("diagnostics")
    )
    for item in diagnostics:
        diagnostic = _require_object("diagnostic", item)
        if not isinstance(diagnostic.get("code"), str) or not isinstance(
            diagnostic.get("message"), str
        ):
            raise ValidationError(
                "SANDBOX_OUTPUT_INVALID", "diagnostic requires code and message"
            )

    metrics = _require_object("metrics.json", _json("metrics.json", files["metrics.json"]))
    if metrics.get("schema_version") != "sandbox-metrics/1":
        raise ValidationError("SANDBOX_OUTPUT_INVALID", "metrics.json schema_version mismatch")
    if not isinstance(metrics.get("duration_ms"), int):
        raise ValidationError("SANDBOX_OUTPUT_INVALID", "metrics.duration_ms is missing")

    manifest = _require_object("manifest.json", _json("manifest.json", files["manifest.json"]))
    if manifest.get("schema_version") != "sandbox-manifest/1":
        raise ValidationError("SANDBOX_OUTPUT_INVALID", "manifest.json schema_version mismatch")
    declared = _require_object("manifest outputs", manifest.get("outputs"))
    actual = {
        name: sha256(data) for name, data in files.items() if name != "manifest.json"
    }
    if declared != actual:
        raise ValidationError(
            "SANDBOX_OUTPUT_DIGEST_MISMATCH",
            "manifest.json outputs do not match the produced artifacts",
        )

    if evidence_lines == 0 and records:
        diagnostics = list(diagnostics) + [
            {
                "code": "EVIDENCE_EMPTY",
                "message": "records were produced without evidence lines",
                "severity": "warning",
                "detail": {"records": len(records)},
            }
        ]

    return ValidatedOutputs(
        files=dict(files),
        digests={name: sha256(data) for name, data in files.items()},
        records=len(records),
        diagnostics=diagnostics,
    )
