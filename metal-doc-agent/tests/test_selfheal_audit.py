"""Stage B tests: audit packets, deterministic rules, model finding validation."""

from __future__ import annotations

import json
from pathlib import Path

from metal_doc_agent.contracts import (
    DocumentMeta,
    DocumentResult,
    Evidence,
    ExtractedValue,
    Record,
    TableGrid,
)
from metal_doc_agent.selfheal.audit import (
    build_packet,
    deterministic_findings,
    model_findings,
    audit_job,
)
from metal_doc_agent.selfheal.config import SelfHealSettings
from metal_doc_agent.selfheal.contracts import FindingVerdict
from metal_doc_agent.selfheal.storage import SelfHealStore

ROWS = [
    ["牌号", "抗拉强度Rm/MPa", "断后伸长率A/%"],
    ["2A14", "430", "10"],
    ["2A14", "400", "8"],
]


def _value(raw: str, value: float, unit: str, row: int, col: int, evidence_id: str):
    return ExtractedValue(
        raw=raw, value=value, unit=unit, comparator="min", evidence_id=evidence_id
    )


def make_job(tmp_path: Path, mutate: dict | None = None) -> Path:
    job = tmp_path / "job-1"
    job.mkdir()
    document = DocumentMeta(
        doc_id="doc-1",
        source_path="doc.md",
        file_name="doc.md",
        standard_no="GB/T 0000-2026",
        title="测试标准",
        page_count=1,
    )
    table = TableGrid(
        table_id="T1",
        page_no=1,
        caption="表1 力学性能",
        profile="mechanical_properties",
        header_rows=1,
        n_rows=len(ROWS),
        n_cols=3,
        rows=ROWS,
        header_paths=[["牌号"], ["抗拉强度Rm/MPa"], ["断后伸长率A/%"]],
    )
    record = Record(
        record_id="rec-1",
        source_table_id="T1",
        grade="2A14",
        condition=None,
        properties={
            "Rm": _value("430", 430.0, "MPa", 1, 1, "ev:1"),
            "A": _value("10", 10.0, "%", 1, 2, "ev:2"),
        },
    )
    if mutate:
        for field_name, replacement in mutate.items():
            if field_name == "records":
                record = replacement
            elif field_name == "rows":
                table.rows = replacement
    result = DocumentResult(document=document, tables=[table], records=[record])
    (job / "result.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )
    evidence = [
        Evidence(
            evidence_id="ev:1",
            page_no=1,
            table_id="T1",
            row=1,
            col=1,
            quote="430",
        ),
        Evidence(
            evidence_id="ev:2",
            page_no=1,
            table_id="T1",
            row=1,
            col=2,
            quote="10",
        ),
    ]
    (job / "evidence.jsonl").write_text(
        "\n".join(item.model_dump_json() for item in evidence) + "\n",
        encoding="utf-8",
    )
    return job


class FakeReviewer:
    name = "fake"

    def __init__(self, findings):
        self.findings = findings

    def review(self, packet, doc):
        return self.findings


def test_build_packet_shapes(tmp_path):
    job = make_job(tmp_path)
    packet = build_packet(job)
    assert packet.doc_id == "doc-1"
    assert len(packet.tables) == 1
    table = packet.tables[0]
    assert table.table_id == "T1"
    assert table.records[0]["record_id"] == "rec-1"
    assert table.records[0]["properties"]["Rm"]["value"] == 430.0
    assert packet.record_count == 1


def test_deterministic_rules_clean(tmp_path):
    job = make_job(tmp_path)
    packet = build_packet(job)
    assert deterministic_findings(packet, job) == []


def test_deterministic_rules_detect_issues(tmp_path):
    job = make_job(
        tmp_path,
        mutate={
            "rows": [
                ["牌号", "抗拉强度Rm/MPa", "断后伸长率A/%"],
                ["2A14", "999", "10"],
                ["2A14", "400", "8"],
            ]
        },
    )
    packet = build_packet(job)
    findings = deterministic_findings(packet, job)
    codes = {item.rule_code for item in findings}
    assert "evidence_quote_mismatch" in codes
    assert all(item.source.value == "audit" for item in findings)
    assert findings[0].evidence[0].quote == "430"


def test_deterministic_missing_evidence_and_unit(tmp_path):
    job = make_job(tmp_path)
    result = DocumentResult.model_validate(
        json.loads((job / "result.json").read_text(encoding="utf-8"))
    )
    record = result.records[0]
    record.properties["Rm"] = ExtractedValue(
        raw="430", value=430.0, unit=None, comparator="min", evidence_id="ev:missing"
    )
    (job / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    packet = build_packet(job)
    codes = {item.rule_code for item in deterministic_findings(packet, job)}
    assert "evidence_missing" in codes
    assert "unit_missing" in codes


def test_model_findings_are_grounded(tmp_path):
    job = make_job(tmp_path)
    packet = build_packet(job)
    reviewer = FakeReviewer(
        [
            {"record_id": "rec-1", "field": "properties.Rm.unit", "type": "wrong_unit"},
            {"record_id": "nope", "field": "Rm", "type": "wrong_value"},
            {"record_id": "rec-1", "field": "unknown_prop", "type": "extra_value"},
        ]
    )
    findings = model_findings(packet, reviewer)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.target.property == "Rm"
    assert finding.verdict == FindingVerdict.wrong
    assert finding.evidence and finding.evidence[0].quote == "430"


def test_audit_job_writes_outputs_and_store(tmp_path):
    job = make_job(tmp_path)
    out = tmp_path / "out"
    store = SelfHealStore(tmp_path / "selfheal.db")
    settings = SelfHealSettings.from_env(project_root=tmp_path)
    findings = audit_job(
        job,
        out,
        settings=settings,
        store=store,
        reviewer=FakeReviewer(
            [{"record_id": "rec-1", "field": "Rm", "type": "wrong_value"}]
        ),
    )
    assert len(findings) == 1
    payload = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert payload[0]["rule_code"] == "model_wrong_value"
    assert (out / "audit_packet.json").exists()
    assert store.metrics()["findings"]["open"] == 1


def test_audit_job_deterministic_only(tmp_path):
    job = make_job(tmp_path)
    out = tmp_path / "out"
    settings = SelfHealSettings.from_env(project_root=tmp_path)
    findings = audit_job(job, out, settings=settings, use_model=False)
    assert findings == []
    assert json.loads((out / "findings.json").read_text(encoding="utf-8")) == []
