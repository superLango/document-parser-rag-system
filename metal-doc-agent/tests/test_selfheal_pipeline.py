"""Stage C tests: feedback intake, L1 repair, gates and orchestration."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from metal_doc_agent.pipeline import run_pipeline
from metal_doc_agent.settings import Settings
from metal_doc_agent.selfheal.config import SelfHealSettings
from metal_doc_agent.selfheal.contracts import (
    FeedbackCategory,
    FeedbackCreate,
    FeedbackStatus,
    FeedbackTarget,
    Finding,
    FindingSource,
    FindingVerdict,
    GateDecision,
)
from metal_doc_agent.selfheal.feedback import FeedbackService
from metal_doc_agent.selfheal.gates import GateContext, evaluate
from metal_doc_agent.selfheal.l1 import L1Repairer, diff_results
from metal_doc_agent.selfheal.pipeline import SelfHealPipeline
from metal_doc_agent.selfheal.storage import SelfHealStore

AGENT_ROOT = Path(__file__).resolve().parents[1]

MD = """# Page 1

# 测试标准

## Table

<table border="1">
<tr><td rowspan="2">牌号</td><td colspan="2">力学性能(不小于)</td></tr>
<tr><td>抗拉强度Rm/MPa</td><td>断后伸长率A/%</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
<tr><td>2A15</td><td>400</td><td>8</td></tr>
</table>
"""


@pytest.fixture()
def job(tmp_path: Path) -> Path:
    md = tmp_path / "doc.md"
    md.write_text(MD, encoding="utf-8")
    out = tmp_path / "data" / "jobs" / "job-1"
    settings = dataclasses.replace(
        Settings.from_env(),
        project_root=AGENT_ROOT,
        data_dir=tmp_path / "data",
        ocr_backend="mock",
        extractor_backend="mock",
    )
    run_pipeline(md, out, settings=settings, coverage_template="product_full")
    return out


def _store(tmp_path: Path) -> SelfHealStore:
    return SelfHealStore(tmp_path / "selfheal.db")


def _settings(tmp_path: Path) -> SelfHealSettings:
    return dataclasses.replace(
        SelfHealSettings.from_env(project_root=AGENT_ROOT),
        root=tmp_path / "selfheal",
        db_path=tmp_path / "selfheal" / "selfheal.db",
        data_dir=tmp_path / "data",
    )


def _first_record(job: Path):
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    record = result["records"][0]
    return record["record_id"], record["properties"]["Rm"]["raw"]


def _payload(job: Path, **overrides) -> FeedbackCreate:
    record_id, raw = _first_record(job)
    data = {
        "doc_id": "doc",
        "job_id": "job-1",
        "category": FeedbackCategory.wrong_value,
        "target": FeedbackTarget(record_id=record_id, property="Rm", table_id="T1"),
        "description": "抗拉强度应为 440",
        "expected_value": "440",
    }
    data.update(overrides)
    return FeedbackCreate(**data)


def test_feedback_creates_finding_with_evidence(job, tmp_path):
    store = _store(tmp_path)
    service = FeedbackService(store, _settings(tmp_path))
    outcome = service.create(_payload(job))
    assert outcome["problems"] == []
    assert outcome["feedback"].status == FeedbackStatus.open
    assert outcome["finding"] is not None
    assert outcome["finding"].evidence
    assert store.list_findings_for_feedback(outcome["feedback"].feedback_id)


def test_feedback_missing_job_needs_more_info(tmp_path):
    store = _store(tmp_path)
    service = FeedbackService(store, _settings(tmp_path))
    payload = FeedbackCreate(
        doc_id="doc",
        job_id="no-such-job",
        category=FeedbackCategory.other,
        target=FeedbackTarget(table_id="T1"),
    )
    outcome = service.create(payload)
    assert outcome["problems"]
    assert outcome["feedback"].status == FeedbackStatus.needs_more_info
    assert outcome["finding"] is None


def test_feedback_bad_quote_is_a_hint_not_a_rejection(job, tmp_path):
    store = _store(tmp_path)
    service = FeedbackService(store, _settings(tmp_path))
    outcome = service.create(
        _payload(job, source_quote="原文中不存在的句子")
    )
    assert outcome["problems"] == []
    assert outcome["feedback"].status == FeedbackStatus.open
    assert outcome["finding"] is not None


def test_diff_results_detects_changes():
    from metal_doc_agent.contracts import DocumentMeta, DocumentResult, Record

    doc = DocumentMeta(doc_id="d", source_path="a", file_name="a")
    before = DocumentResult(
        document=doc,
        records=[Record(record_id="r1", source_table_id="T1", grade="A")],
    )
    after = DocumentResult(
        document=doc,
        records=[
            Record(record_id="r1", source_table_id="T1", grade="A"),
            Record(record_id="r2", source_table_id="T1", grade="B"),
        ],
    )
    diff = diff_results(before, after)
    assert diff["summary"]["added"] == 1
    assert diff["summary"]["records_after"] == 2


def test_l1_reparse_is_isolated(job, tmp_path):
    repairer = L1Repairer(_settings(tmp_path))
    finding = Finding(
        doc_id="doc",
        job_id="job-1",
        source=FindingSource.user,
        verdict=FindingVerdict.wrong,
        target=FeedbackTarget(record_id=_first_record(job)[0], property="Rm", table_id="T1"),
        expected=_first_record(job)[1],
    )
    production = AGENT_ROOT / "configs" / "table_repairs.json"
    before_hash = hashlib.sha256(production.read_bytes()).hexdigest()
    result = repairer.apply(finding, job, tmp_path / "sandbox", proposal_id="prp-l1")
    assert result.ok, result.error
    assert (tmp_path / "sandbox" / "result.json").exists()
    assert (tmp_path / "sandbox" / "repair_diff.json").exists()
    assert result.diff["target_resolved"] is True
    after_hash = hashlib.sha256(production.read_bytes()).hexdigest()
    assert before_hash == after_hash


def test_l1_table_repair_changes_value(job, tmp_path):
    repairer = L1Repairer(_settings(tmp_path))
    record_id, raw = _first_record(job)
    finding = Finding(
        doc_id="doc",
        job_id="job-1",
        source=FindingSource.user,
        verdict=FindingVerdict.wrong,
        target=FeedbackTarget(record_id=record_id, property="Rm", table_id="T1"),
        expected="440",
        observed=raw,
    )
    result = repairer.apply(
        finding,
        job,
        tmp_path / "sandbox2",
        proposal_id="prp-l1b",
        table_repair={"replace_rows": {"2": ["2A14", "440", "10"]}},
    )
    assert result.ok, result.error
    after = json.loads((tmp_path / "sandbox2" / "result.json").read_text(encoding="utf-8"))
    values = [r["properties"]["Rm"]["raw"] for r in after["records"] if "Rm" in r["properties"]]
    assert "440" in values


def _gate_proposal(level="L1"):
    from metal_doc_agent.selfheal.contracts import RepairLevel, RepairProposal

    return RepairProposal(
        proposal_id="prp-1",
        finding_ids=["fnd-1"],
        level=RepairLevel(level),
        operator="document.reparse",
        status="verified",
    )


def _gate_finding():
    from metal_doc_agent.selfheal.contracts import EvidenceRef

    return Finding(
        doc_id="doc",
        job_id="job-1",
        source=FindingSource.user,
        verdict=FindingVerdict.wrong,
        target=FeedbackTarget(record_id="r1", property="Rm"),
        evidence=[EvidenceRef(quote="430")],
    )


def test_gates_accept(tmp_path):
    gate = evaluate(
        GateContext(
            finding=_gate_finding(),
            proposal=_gate_proposal(),
            diff={"reproduced": True, "target_resolved": True, "new_errors": 0},
            iterations=1,
        ),
        _settings(tmp_path),
    )
    assert gate.decision == GateDecision.accept


def test_gates_rollback_without_evidence(tmp_path):
    finding = _gate_finding()
    finding.evidence = []
    gate = evaluate(
        GateContext(
            finding=finding,
            proposal=_gate_proposal(),
            diff={"target_resolved": True},
            iterations=1,
        ),
        _settings(tmp_path),
    )
    assert gate.decision == GateDecision.rollback


def test_pipeline_reports_evidence_when_gate_fails(job, tmp_path):
    store = _store(tmp_path)
    settings = _settings(tmp_path)
    service = FeedbackService(store, settings)
    created = service.create(_payload(job))
    pipeline = SelfHealPipeline(store, settings)
    outcome = pipeline.process_feedback(created["feedback"].feedback_id)
    assert outcome.status in {
        FeedbackStatus.unresolved,
        FeedbackStatus.fixed,
    }
    assert store.get_feedback(created["feedback"].feedback_id).status == outcome.status
    messages = store.list_messages(created["feedback"].feedback_id)
    assert any(
        "依据" in item.content or "已执行" in item.content for item in messages
    )


def test_iteration_limit_quarantines(job, tmp_path):
    store = _store(tmp_path)
    settings = dataclasses.replace(_settings(tmp_path), max_iterations=0)
    service = FeedbackService(store, settings)
    created = service.create(_payload(job))
    pipeline = SelfHealPipeline(store, settings)
    outcome = pipeline.process_feedback(created["feedback"].feedback_id)
    assert outcome.status == FeedbackStatus.needs_more_info
    findings = store.list_findings_for_feedback(created["feedback"].feedback_id)
    assert findings[0].status.value == "quarantined"
