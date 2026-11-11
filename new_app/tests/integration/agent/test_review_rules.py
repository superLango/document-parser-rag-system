from __future__ import annotations

import asyncio

from hanson_contracts import ReviewRequest

from services.review.config import Settings
from services.review.rules import run_rules
from services.review.service import ReviewService


def _records() -> list[dict]:
    return [
        {
            "record_id": "R1",
            "table_id": "T1",
            "grade": "Q355B",
            "properties": {"Rm": {"value": 470, "unit": "MPa"}},
            "evidence_refs": ["E1"],
        },
        {
            "record_id": "R2",
            "table_id": "T1",
            "grade": "",
            "properties": {"Rm": {"value": 470, "unit": "MPa"}},
            "evidence_refs": ["E1"],
        },
        {
            "record_id": "R3",
            "table_id": "T1",
            "grade": "Q235B",
            "properties": {"Rm": {"value": -1, "unit": "MPa"}, "A": {"value": 22}},
            "evidence_refs": ["unknown"],
        },
        {
            "record_id": "R4",
            "table_id": "T1",
            "grade": "Q235B",
            "properties": {},
            "evidence_refs": [],
        },
        {
            "record_id": "R1",
            "table_id": "T1",
            "grade": "Q355B",
            "properties": {},
            "evidence_refs": ["E1"],
        },
    ]


def _evidence() -> list[dict]:
    return [{"evidence_id": "E1", "table_id": "T1", "page_no": 1, "cells": {}}]


def test_rules_cover_injected_errors() -> None:
    findings = run_rules(
        _records(),
        _evidence(),
        tables=[{"table_id": "T1", "records": 2}],
    )
    rule_ids = {item.rule_id for item in findings}
    for expected in {
        "M5-GRADE-001",
        "M5-EVID-001",
        "M5-EVID-002",
        "M5-VALUE-001",
        "M5-UNIT-001",
        "M5-PROP-001",
        "M5-ID-002",
        "M5-TABLE-001",
    }:
        assert expected in rule_ids, expected
    valid = [item for item in findings if item.target.get("record_id") == "R1"]
    assert all(item.rule_id != "M5-GRADE-001" for item in valid)


def test_review_service_rule_only_mode() -> None:
    async def scenario() -> None:
        service = ReviewService(Settings(use_agent=False, ruleset_version="m5"))
        report = await service.review(
            ReviewRequest(
                run_id="run-1",
                records=_records(),
                evidence=_evidence(),
                tables=[{"table_id": "T1", "records": 2}],
            )
        )
        assert report.status == "fail"
        assert report.stats["errors"] >= 2
        assert report.stats["deterministic"] == len(report.findings)
        assert report.degraded is False
        assert report.ruleset_version == "m5"

    asyncio.run(scenario())
