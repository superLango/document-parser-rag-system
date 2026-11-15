from __future__ import annotations

from services.orchestration import cross_standard
from services.orchestration.models import StandardIndex


def _row(standard_no: str, edition: str, **kwargs) -> StandardIndex:
    return StandardIndex(
        id=f"{standard_no}-{edition}",
        document_id=kwargs.get("document_id", "doc-source"),
        standard_no=standard_no,
        edition=edition,
        title=kwargs.get("title", ""),
        source_kind="upload",
        status=kwargs.get("status", "parsed"),
        page_count=kwargs.get("page_count", 10),
        categories=kwargs.get("categories", ["化学成分"]),
        grades=kwargs.get("grades", ["TA1G", "TA8-1"]),
        latest_run_id=kwargs.get("latest_run_id", "run-source"),
    )


def _candidate(**overrides) -> dict:
    payload = {
        "task_id": "xstd-test",
        "feature": "化学成分",
        "scope": "category",
        "parameter": "",
        "standard_no": "GB/T 3620.2",
        "edition": "",
        "kind": "content",
        "clause_id": "5.1",
        "page_no": 6,
        "quote": "其化学成分允许偏差应符合GB/T 3620.2的规定。",
    }
    payload.update(overrides)
    return payload


def _chemical_record(grade: str, properties: dict) -> dict:
    return {
        "record_id": f"T-{grade}",
        "table_id": "T1",
        "page_no": 6,
        "profile": "chemical_composition",
        "grade": grade,
        "conditions": {},
        "properties": properties,
        "evidence_refs": ["ev-source"],
    }


def test_resolve_needs_source_and_latest_edition() -> None:
    tasks = cross_standard.resolve_tasks([_candidate()], [], [])
    assert tasks[0]["status"] == "needs_source"
    assert "未收录" in tasks[0]["gap"]

    rows = [
        _row("GB/T 3620.2", "2019"),
        _row("GB/T 3620.2", "2024"),
    ]
    tasks = cross_standard.resolve_tasks([_candidate()], rows, [])
    assert tasks[0]["status"] == "resolved"
    assert tasks[0]["resolution"]["edition"] == "2024"


def test_expand_fills_missing_measures_only() -> None:
    source = [
        _chemical_record(
            "TA1G",
            {
                "C": {"raw": "0.04", "value": 0.04, "unit": "%"},
                "Fe": {"raw": "0.10", "value": 0.10, "unit": "%"},
                "O": {"raw": "0.10", "value": 0.10, "unit": "%"},
            },
        ),
        _chemical_record(
            "SUS304",
            {
                "C": {"raw": "0.08", "value": 0.08, "unit": "%"},
            },
        ),
    ]
    current = [
        _chemical_record(
            "TA1G",
            {"C": {"raw": "0.05", "value": 0.05, "unit": "%"}},
        )
    ]
    task = cross_standard.resolve_tasks(
        [_candidate()],
        [_row("GB/T 3620.2", "2024")],
        current,
    )[0]
    outcome = cross_standard.expand_deterministic(
        task, current, [], source, {}, []
    )
    assert outcome["status"] == "expanded"
    measures = {
        item["measure"]
        for item in outcome["proposals"]
        if item["kind"] == "property"
    }
    assert measures == {"Fe", "O"}
    assert outcome["conflicts"][0]["measure"] == "C"
    records, evidence, _ = cross_standard.apply_proposals(
        current, [], task, outcome["proposals"]
    )
    assert records[0]["properties"]["C"]["raw"] == "0.05"
    assert records[0]["properties"]["Fe"]["meta"]["跨标准来源"].startswith(
        "GB/T 3620.2-2024"
    )
    assert evidence and evidence[0]["source"] == "cross_standard"


def test_expand_creates_grade_rows_when_category_missing() -> None:
    source = [
        _chemical_record(
            "TA8-1",
            {"C": {"raw": "0.05", "value": 0.05, "unit": "%"}},
        )
    ]
    current = [
        {
            "record_id": "M-1",
            "table_id": "T2",
            "profile": "mechanical_properties",
            "grade": "TA8-1",
            "conditions": {},
            "properties": {},
        }
    ]
    task = cross_standard.resolve_tasks(
        [_candidate()],
        [_row("GB/T 3620.2", "2024")],
        current,
    )[0]
    outcome = cross_standard.expand_deterministic(
        task, current, [], source, {}, []
    )
    assert outcome["status"] == "expanded"
    records, evidence, added = cross_standard.apply_proposals(
        current, [], task, outcome["proposals"]
    )
    assert len(records) == 2
    assert added[0].startswith("XS-")
    copied = records[-1]
    assert copied["grade"] == "TA8-1"
    assert copied["profile"] == "chemical_composition"
    assert copied["source"]["kind"] == "cross_standard"
    assert evidence


def test_agent_items_require_source_quote() -> None:
    task = cross_standard.resolve_tasks(
        [_candidate()],
        [_row("GB/T 3620.2", "2024")],
        [],
    )[0]
    source_text = "成品化学成分允许偏差应符合表2的规定，其他元素应符合本文件要求。"
    accepted, rejected = cross_standard.validate_agent_items(
        [
            {
                "task_id": task["task_id"],
                "feature": "化学成分",
                "measure": "其他元素",
                "requirement": "符合本文件要求",
                "quote": "其他元素应符合本文件要求",
                "standard_no": "GB/T 3620.2",
                "page_no": 5,
            },
            {
                "task_id": task["task_id"],
                "feature": "化学成分",
                "measure": "Fe",
                "requirement": "≤0.10",
                "quote": "这是一段来源正文中不存在的编造引用",
                "standard_no": "GB/T 3620.2",
            },
        ],
        [task],
        {"doc-source": source_text},
    )
    assert len(accepted) == 1
    assert accepted[0]["measure"] == "其他元素"
    assert rejected[0]["reason"] == "quote_not_found"
