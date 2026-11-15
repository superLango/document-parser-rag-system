"""PASS_TO_PASS regression gate over the fixed sample set."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PLACEHOLDER_GRADES = {"", "~", "-", "--", "—", "–", "/"}
DUPLICATE_LIMIT = 3


def metrics_from_records(records: list[dict[str, Any]]) -> dict[str, int]:
    """Per-document metrics used by the regression snapshot."""
    fields = 0
    placeholders = 0
    counts: dict[tuple[str, str], int] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        grade = str(record.get("grade") or "").strip()
        if grade in PLACEHOLDER_GRADES:
            placeholders += 1
            grade = ""
        properties = record.get("properties") or {}
        if not isinstance(properties, dict):
            continue
        fields += len(properties)
        if not grade:
            continue
        for name in properties:
            counts[(grade, str(name))] = counts.get((grade, str(name)), 0) + 1
    duplicates = sum(
        count - DUPLICATE_LIMIT
        for count in counts.values()
        if count > DUPLICATE_LIMIT
    )
    return {
        "records": len(records),
        "fields": fields,
        "placeholders": placeholders,
        "duplicates": duplicates,
    }


def snapshot_from_documents(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for item in documents:
        name = str(item.get("name") or "")
        if not name:
            continue
        entry: dict[str, Any] = {
            "status": str(item.get("status") or ""),
            "records": int(item.get("records") or 0),
            "fields": int(item.get("fields") or 0),
        }
        for key in ("placeholders", "duplicates", "complete_rows", "required_present"):
            if key in item:
                entry[key] = int(item.get(key) or 0)
        snapshot[name] = entry
    return snapshot


def load_snapshot(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    documents = payload.get("documents") if isinstance(payload, dict) else payload
    return snapshot_from_documents(documents or [])


def gate(
    baseline_path: str | Path,
    current_path: str | Path,
    *,
    max_drop_ratio: float = 0.1,
) -> dict[str, Any]:
    """Compare two snapshot files; missing files mean the gate is not configured."""
    baseline_file = Path(baseline_path)
    current_file = Path(current_path)
    if not baseline_file.exists() or not current_file.exists():
        return {
            "passed": True,
            "skipped": True,
            "detail": "未配置回归基线，跳过",
            "regressions": [],
        }
    result = compare_snapshots(
        load_snapshot(baseline_file),
        load_snapshot(current_file),
        max_drop_ratio=max_drop_ratio,
    )
    result["skipped"] = False
    return result


def compare_snapshots(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    *,
    max_drop_ratio: float = 0.1,
) -> dict[str, Any]:
    """Fail when a document disappears, loses structured status, or drops records."""
    regressions: list[dict[str, Any]] = []
    for name, base in baseline.items():
        item = current.get(name)
        if item is None:
            regressions.append({"name": name, "reason": "missing"})
            continue
        if base.get("status") == "STRUCTURED_READY" and item.get("status") != "STRUCTURED_READY":
            regressions.append(
                {
                    "name": name,
                    "reason": "status_regressed",
                    "before": base.get("status"),
                    "after": item.get("status"),
                }
            )
            continue
        base_records = int(base.get("records") or 0)
        current_records = int(item.get("records") or 0)
        if base_records > 0 and current_records < base_records * (1 - max_drop_ratio):
            regressions.append(
                {
                    "name": name,
                    "reason": "records_dropped",
                    "before": base_records,
                    "after": current_records,
                }
            )
            continue
        for key, reason in (
            ("complete_rows", "complete_rows_dropped"),
            ("required_present", "required_present_dropped"),
        ):
            before = base.get(key)
            after = item.get(key)
            if before is None or after is None:
                continue
            if int(before) > 0 and int(after) < int(before) * (1 - max_drop_ratio):
                regressions.append(
                    {
                        "name": name,
                        "reason": reason,
                        "before": int(before),
                        "after": int(after),
                    }
                )
        for key, reason in (
            ("placeholders", "placeholders_increased"),
            ("duplicates", "duplicates_increased"),
        ):
            before = base.get(key)
            after = item.get(key)
            if before is None or after is None:
                continue
            if int(after) > int(before):
                regressions.append(
                    {
                        "name": name,
                        "reason": reason,
                        "before": int(before),
                        "after": int(after),
                    }
                )
    return {
        "passed": not regressions,
        "regressions": regressions,
        "detail": f"{len(regressions)} regression(s) / {len(baseline)} document(s)",
    }
