"""Stage G: end-to-end audit -> finding -> L2 shadow repair -> gate."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from metal_doc_agent.pipeline import run_pipeline
from metal_doc_agent.settings import Settings
from metal_doc_agent.selfheal.config import SelfHealSettings
from metal_doc_agent.selfheal.contracts import FindingStatus, ProposalStatus
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


def _settings(tmp_path: Path) -> SelfHealSettings:
    return dataclasses.replace(
        SelfHealSettings.from_env(project_root=AGENT_ROOT),
        enabled=True,
        root=tmp_path / "selfheal",
        db_path=tmp_path / "selfheal" / "selfheal.db",
        data_dir=tmp_path / "data",
    )


def _corrupt_evidence(job: Path) -> None:
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    record = result["records"][0]
    evidence_id = record["properties"]["Rm"]["evidence_id"]
    path = job / "evidence.jsonl"
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item["evidence_id"] == evidence_id:
            item["quote"] = "999"
        lines.append(json.dumps(item, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_audit_finding_repairs_through_l2(job, tmp_path):
    _corrupt_evidence(job)
    settings = _settings(tmp_path)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    pipeline = SelfHealPipeline(store, settings, planner=None)
    production = AGENT_ROOT / "configs" / "table_repairs.json"
    before = hashlib.sha256(production.read_bytes()).hexdigest()

    findings = pipeline.audit_job(job, tmp_path / "audit")
    mismatch = [item for item in findings if item.rule_code == "evidence_quote_mismatch"]
    assert mismatch, [item.rule_code for item in findings]
    finding = mismatch[0]
    assert store.get_finding(finding.finding_id) is not None

    outcome = pipeline.process_finding(finding.finding_id)
    assert outcome["repaired"] is True, outcome
    assert outcome["level"] == "L2"
    assert store.get_finding(finding.finding_id).status == FindingStatus.fixed
    proposals = [
        item
        for item in store.list_candidates()
        if item.signature == proposals_signature(store, finding.finding_id)
    ]
    assert proposals
    assert proposals[0].status.value == "shadow"
    assert hashlib.sha256(production.read_bytes()).hexdigest() == before


def proposals_signature(store: SelfHealStore, finding_id: str) -> str:
    for item in store.list_candidates():
        proposal = store.get_proposal(item.proposal_id)
        if proposal and finding_id in proposal.finding_ids:
            return item.signature
    return ""


def test_audit_writes_findings_and_isolated_outputs(job, tmp_path):
    _corrupt_evidence(job)
    settings = _settings(tmp_path)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    pipeline = SelfHealPipeline(store, settings)
    out = tmp_path / "audit_out"
    findings = pipeline.audit_job(job, out)
    payload = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert len(payload) == len(findings)
    assert all(item["source"] == "audit" for item in payload)
    assert (out / "audit_packet.json").exists()
    assert not (job / "findings.json").exists()
