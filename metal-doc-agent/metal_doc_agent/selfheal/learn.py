"""Persist what an applied correction taught the system.

The dictionary stays read-only: aliases go to the learned overlay, other rule
changes are recorded as rule proposals and (optionally) code patches. Every
learn step verifies the protected dictionary files by hash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import SelfHealSettings
from .lexicon import (
    add_learned_alias,
    dictionary_hashes,
    dictionary_unchanged,
    record_learned_rule,
)


def load_diagnosis(settings: SelfHealSettings, feedback_id: str) -> dict[str, Any]:
    path = settings.jobs_root / feedback_id / "diagnosis.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def learn_from_applied(
    settings: SelfHealSettings, feedback_id: str
) -> dict[str, Any]:
    diagnosis = load_diagnosis(settings, feedback_id)
    if not diagnosis:
        return {
            "status": "skipped",
            "reason": "没有诊断记录，无法沉淀规则",
            "feedback_id": feedback_id,
        }
    before = dictionary_hashes(settings.project_root)
    report: dict[str, Any] = {
        "feedback_id": feedback_id,
        "level": "D",
        "alias": None,
        "rule": None,
        "dictionary": None,
    }

    correction = diagnosis.get("correction") or {}
    target = diagnosis.get("target") or {}
    scope = diagnosis.get("scope")
    feature = target.get("feature") or diagnosis.get("expected")
    canonical = feature or diagnosis.get("expected")

    if scope in {"missing_item", "missing_field"} and correction.get("found"):
        surface = target.get("feature") or correction.get("value")
        if surface and canonical and surface != canonical:
            entry, detail = add_learned_alias(
                settings.project_root,
                surface=str(surface),
                canonical=str(canonical),
                source_feedback=feedback_id,
            )
            report["alias"] = {"entry": entry, "detail": detail}
            if entry is not None:
                report["level"] = "A"

    rule_change = diagnosis.get("rule_change") or {}
    if rule_change:
        record = {
            "feedback_id": feedback_id,
            "root_cause": diagnosis.get("root_cause"),
            "scope": scope,
            "mechanism": diagnosis.get("mechanism"),
            "first_divergence": diagnosis.get("first_divergence"),
            "rule_change": rule_change,
            "evidence": diagnosis.get("evidence") or [],
            "checks": diagnosis.get("checks") or [],
        }
        record_learned_rule(settings.project_root, record)
        report["rule"] = record
        if report["level"] == "D":
            report["level"] = "B"

    ok, detail = dictionary_unchanged(before, settings.project_root)
    report["dictionary"] = {"unchanged": ok, "detail": detail}
    if not ok:
        report["status"] = "failed"
        report["reason"] = detail
        return report

    if report["level"] == "D":
        report["status"] = "manual_review"
        report["reason"] = (
            "只能作为当前文档的个案修正，未找到可泛化的规则原因；"
            "依据：" + "；".join(diagnosis.get("checks") or [])[:300]
        )
    else:
        report["status"] = "learned"
        report["reason"] = f"已沉淀为 {report['level']} 级规则"
    return report
