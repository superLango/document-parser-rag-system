"""L1 document-level repair: re-parse into an isolated sandbox and diff."""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts import DocumentResult, Record
from ..pipeline import run_pipeline
from ..sandbox_exec import run_pipeline_sandbox
from ..settings import Settings
from .config import SelfHealSettings, normalize_ocr_backend
from .contracts import Finding, FindingVerdict, RepairLevel, RepairProposal, ProposalStatus
from .locate import load_result, load_trace
from .sandbox import append_table_repair, create_overlay_project

MAX_DIFF_ITEMS = 200
UNIT_VALUES = {"MPa", "%", "J", "GPa", "HBW", "HRC", "HV", "mm"}
COMPARATOR_VALUES = {"min", "max", "eq", "range", "text", "na"}


@dataclass
class L1Result:
    ok: bool
    out_dir: Path
    diff: dict[str, Any]
    proposal: RepairProposal | None = None
    error: str | None = None


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _record_key(record: Record) -> tuple[str, str, str]:
    return (
        record.source_table_id or "",
        _norm(record.grade or record.grade_level),
        _norm(record.condition),
    )


def _value_payload(value) -> dict[str, Any]:
    return {
        "raw": value.raw,
        "value": value.value,
        "text": value.text,
        "unit": value.unit,
        "comparator": value.comparator,
    }


def diff_results(before: DocumentResult, after: DocumentResult) -> dict[str, Any]:
    before_map = {_record_key(record): record for record in before.records}
    after_map = {_record_key(record): record for record in after.records}
    added = []
    for key in after_map.keys() - before_map.keys():
        record = after_map[key]
        added.append(
            {
                "record_id": record.record_id,
                "table_id": record.source_table_id,
                "grade": record.grade or record.grade_level,
                "condition": record.condition,
                "properties": len(record.properties),
            }
        )
    removed = []
    for key in before_map.keys() - after_map.keys():
        record = before_map[key]
        removed.append(
            {
                "record_id": record.record_id,
                "table_id": record.source_table_id,
                "grade": record.grade or record.grade_level,
                "condition": record.condition,
            }
        )
    changed = []
    for key in before_map.keys() & after_map.keys():
        old = before_map[key]
        new = after_map[key]
        for name in sorted(set(old.properties) | set(new.properties)):
            old_value = old.properties.get(name)
            new_value = new.properties.get(name)
            if old_value is None and new_value is None:
                continue
            if old_value is None or new_value is None or _value_payload(
                old_value
            ) != _value_payload(new_value):
                changed.append(
                    {
                        "record_id": new.record_id,
                        "table_id": new.source_table_id,
                        "grade": new.grade or new.grade_level,
                        "condition": new.condition,
                        "property": name,
                        "before": _value_payload(old_value) if old_value else None,
                        "after": _value_payload(new_value) if new_value else None,
                    }
                )
    return {
        "added": added[:MAX_DIFF_ITEMS],
        "removed": removed[:MAX_DIFF_ITEMS],
        "changed": changed[:MAX_DIFF_ITEMS],
        "summary": {
            "records_before": len(before.records),
            "records_after": len(after.records),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }


def _as_float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def target_resolved(finding: Finding, after: DocumentResult) -> bool:
    record = None
    if finding.target.record_id:
        record = next(
            (item for item in after.records if item.record_id == finding.target.record_id),
            None,
        )
    if record is None and finding.target.grade:
        record = next(
            (
                item
                for item in after.records
                if _norm(item.grade or item.grade_level) == _norm(finding.target.grade)
                and (
                    not finding.target.condition
                    or _norm(item.condition) == _norm(finding.target.condition)
                )
            ),
            None,
        )
    if record is None:
        return False
    name = finding.target.property
    if not name:
        return False
    value = record.properties.get(name)
    if finding.verdict == FindingVerdict.missing:
        return value is not None
    if finding.verdict == FindingVerdict.extra:
        return value is None
    if value is None:
        return False
    expected = (finding.expected or "").strip()
    if expected in COMPARATOR_VALUES:
        return value.comparator == expected
    if expected in UNIT_VALUES:
        return _norm(value.unit) == expected
    if expected:
        number = _as_float(expected)
        if number is not None and value.value is not None:
            return abs(float(value.value) - number) < 1e-9
        return _norm(value.raw) == _norm(expected)
    return _norm(value.raw) != _norm(finding.observed)


class L1Repairer:
    def __init__(self, settings: SelfHealSettings) -> None:
        self.settings = settings

    def plan(self, finding: Finding, job_dir: str | Path) -> dict[str, Any]:
        trace = load_trace(job_dir)
        versions = trace.get("versions") or {}
        # The trace stores the adapter name ("glm-ocr"), while Settings expects
        # the backend key ("glm"). Re-parsing used to fail on the adapter name.
        return {
            "mode": "reparse",
            "ocr": normalize_ocr_backend(versions.get("ocr")),
            "extractor": versions.get("extractor") or "mock",
            "template": versions.get("coverage_template") or "product_full",
        }

    def apply(
        self,
        finding: Finding,
        job_dir: str | Path,
        out_dir: str | Path,
        *,
        proposal_id: str | None = None,
        table_repair: dict[str, Any] | None = None,
        target_ok: Any = None,
    ) -> L1Result:
        base = Path(job_dir)
        target = Path(out_dir)
        before = load_result(base)
        if before is None:
            return L1Result(False, target, {}, None, "任务产物不可读")
        trace = load_trace(base)
        plan = self.plan(finding, base)
        source = Path(before.document.source_path)
        if not source.is_absolute():
            source = (base / source).resolve()
        if not source.exists():
            return L1Result(False, target, {}, None, f"源文件不存在：{source}")

        settings = Settings.from_env()
        settings = dataclasses.replace(
            settings,
            ocr_backend=plan["ocr"],
            extractor_backend=plan["extractor"],
        )
        if table_repair:
            if before.document.standard_no:
                doc_key = "".join(
                    char
                    for char in before.document.standard_no.upper()
                    if char.isalnum()
                )
            else:
                doc_key = before.document.doc_id
            overlay = create_overlay_project(
                self.settings,
                self.settings.overlays_root / (proposal_id or "l1"),
                {
                    "table_repairs.json": append_table_repair(
                        doc_key, finding.target.table_id or "", table_repair
                    )
                },
            )
            settings = dataclasses.replace(settings, project_root=overlay.root)

        if settings.sandbox:
            # A fresh interpreter imports the current source tree, so the
            # sandbox re-parse also exercises rule patches applied to disk.
            ok, detail = run_pipeline_sandbox(
                settings, source, target, coverage_template=plan["template"]
            )
            if not ok:
                return L1Result(False, target, {}, None, f"重解析失败：{detail}")
        else:
            try:
                run_pipeline(
                    source,
                    target,
                    settings=settings,
                    coverage_template=plan["template"],
                )
            except Exception as exc:  # noqa: BLE001 - repair failure must be reported
                return L1Result(
                    False, target, {}, None, f"重解析失败：{str(exc)[:300]}"
                )
        after = load_result(target)
        if after is None:
            return L1Result(False, target, {}, None, "重解析未生成 result.json")

        diff = diff_results(before, after)
        diff["reproduced"] = True
        if target_ok is not None:
            # Diagnosis scopes (missing item/field, document metadata, whole
            # document) cannot be expressed as record+property in the legacy
            # resolver; the caller supplies the target assertion instead.
            diff["target_resolved"] = bool(target_ok(before, after))
        elif finding.target.table_id and not finding.target.record_id:
            # Table-level feedback has no single field to compare; require the
            # table to gain or change at least one record/property.
            diff["target_resolved"] = _table_changed(diff, finding.target.table_id)
        else:
            diff["target_resolved"] = target_resolved(finding, after)
        diff["new_errors"] = _new_errors(before, after)
        (target / "repair_diff.json").write_text(
            json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        proposal_kwargs: dict[str, Any] = {
            "finding_ids": [finding.finding_id],
            "level": RepairLevel.L1,
            "operator": "document.reparse",
            "params": {"plan": plan, "table_repair": table_repair or None},
            "target_signature": None,
            "status": ProposalStatus.verified
            if diff["target_resolved"] and not diff["new_errors"]
            else ProposalStatus.rejected,
            "artifact_dir": str(target),
        }
        if proposal_id:
            proposal_kwargs["proposal_id"] = proposal_id
        proposal = RepairProposal(**proposal_kwargs)
        return L1Result(True, target, diff, proposal, None)


def _table_changed(diff: dict[str, Any], table_id: str) -> bool:
    for key in ("added", "removed", "changed"):
        for item in diff.get(key) or []:
            if (item.get("table_id") or "") == table_id:
                return True
    return False


def _new_errors(before: DocumentResult, after: DocumentResult) -> int:
    before_errors = (
        sum(1 for issue in before.quality.issues if issue.severity == "error")
        if before.quality
        else 0
    )
    after_errors = (
        sum(1 for issue in after.quality.issues if issue.severity == "error")
        if after.quality
        else 0
    )
    return max(0, after_errors - before_errors)
