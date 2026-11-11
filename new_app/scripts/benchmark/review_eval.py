#!/usr/bin/env python3
"""Deterministic review recall/false-positive evaluation on injected errors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.review.rules import run_rules

RECORDS = [
    {
        "record_id": "CLEAN",
        "table_id": "T1",
        "grade": "Q355B",
        "properties": {"Rm": {"value": 470, "unit": "MPa"}},
        "evidence_refs": ["E1"],
    },
    {
        "record_id": "NO_GRADE",
        "table_id": "T1",
        "grade": "",
        "properties": {"Rm": {"value": 470, "unit": "MPa"}},
        "evidence_refs": ["E1"],
    },
    {
        "record_id": "NO_EVIDENCE",
        "table_id": "T1",
        "grade": "Q235B",
        "properties": {"Rm": {"value": 400, "unit": "MPa"}},
        "evidence_refs": [],
    },
    {
        "record_id": "UNKNOWN_EVIDENCE",
        "table_id": "T1",
        "grade": "Q235B",
        "properties": {"Rm": {"value": 400, "unit": "MPa"}},
        "evidence_refs": ["E404"],
    },
    {
        "record_id": "NEGATIVE",
        "table_id": "T1",
        "grade": "Q235B",
        "properties": {"Rm": {"value": -1, "unit": "MPa"}},
        "evidence_refs": ["E1"],
    },
    {
        "record_id": "NO_UNIT",
        "table_id": "T1",
        "grade": "Q235B",
        "properties": {"Rm": {"value": 400}},
        "evidence_refs": ["E1"],
    },
    {
        "record_id": "EMPTY_PROPS",
        "table_id": "T1",
        "grade": "Q235B",
        "properties": {},
        "evidence_refs": ["E1"],
    },
    {
        "record_id": "CLEAN_OK",
        "table_id": "T1",
        "grade": "Q345B",
        "properties": {"Rm": {"value": 490, "unit": "MPa"}},
        "evidence_refs": ["E1"],
    },
    {
        "record_id": "CLEAN",
        "table_id": "T1",
        "grade": "Q355B",
        "properties": {"Rm": {"value": 470, "unit": "MPa"}},
        "evidence_refs": ["E1"],
    },
]

EXPECTED = {
    "M5-GRADE-001",
    "M5-EVID-001",
    "M5-EVID-002",
    "M5-VALUE-001",
    "M5-UNIT-001",
    "M5-PROP-001",
    "M5-ID-002",
    "M5-TABLE-001",
}

EVIDENCE = [{"evidence_id": "E1", "table_id": "T1", "page_no": 1, "cells": {}}]


def main() -> int:
    parser = argparse.ArgumentParser(description="Review rule evaluation")
    parser.add_argument("--out", default="docs/reports/M5-review-eval.json")
    args = parser.parse_args()
    findings = run_rules(
        RECORDS,
        EVIDENCE,
        tables=[{"table_id": "T1", "records": 1}],
    )
    rule_ids = {item.rule_id for item in findings}
    detected = EXPECTED & rule_ids
    clean_findings = [
        item for item in findings if item.target.get("record_id") == "CLEAN_OK"
    ]
    summary = {
        "cases": len(RECORDS),
        "expected_rules": len(EXPECTED),
        "detected_rules": len(detected),
        "recall": round(len(detected) / len(EXPECTED), 4),
        "findings": len(findings),
        "clean_record_findings": len(clean_findings),
        "false_positive_rate": round(len(clean_findings) / 1, 4),
        "missing_rules": sorted(EXPECTED - rule_ids),
        "rule_ids": sorted(rule_ids),
        "details": [item.model_dump(mode="json") for item in findings],
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    printable = {key: summary[key] for key in summary if key != "details"}
    print(json.dumps(printable, ensure_ascii=False))
    return 0 if summary["recall"] >= 0.95 and summary["false_positive_rate"] <= 0.05 else 1


if __name__ == "__main__":
    raise SystemExit(main())
