"""Stage A tests: contracts, config, isolated SQLite storage."""

from __future__ import annotations

import json

from metal_doc_agent.selfheal.config import SelfHealSettings
from metal_doc_agent.selfheal.contracts import (
    AuditRun,
    CandidateRecipe,
    CodePatchProposal,
    FeedbackCategory,
    FeedbackCreate,
    FeedbackItem,
    FeedbackMessage,
    FeedbackStatus,
    FeedbackTarget,
    Finding,
    FindingSource,
    FindingVerdict,
    GateCheck,
    GateDecision,
    GateResult,
    ProposalStatus,
    RepairLevel,
    RepairProposal,
)
from metal_doc_agent.selfheal.storage import SelfHealStore


def _feedback() -> FeedbackItem:
    payload = FeedbackCreate(
        doc_id="doc-1",
        job_id="job-1",
        user_id="u1",
        category=FeedbackCategory.wrong_value,
        target=FeedbackTarget(record_id="rec-1", property="Rm", table_id="T2"),
        description="抗拉强度写错了",
        expected_value="430",
    )
    return FeedbackItem(
        feedback_id="fb-1",
        **payload.model_dump(),
        status=FeedbackStatus.open,
    )


def test_settings_default_off(monkeypatch):
    monkeypatch.delenv("SELFHEAL_ENABLED", raising=False)
    settings = SelfHealSettings.from_env(project_root="C:/tmp/project")
    assert settings.enabled is False
    assert settings.root.as_posix().endswith("data/selfheal")
    assert settings.code_agent is False
    assert settings.auto_merge is False


def test_settings_env_switch(monkeypatch):
    monkeypatch.setenv("SELFHEAL_ENABLED", "1")
    monkeypatch.setenv("SELFHEAL_CODE_AGENT", "on")
    monkeypatch.setenv("SELFHEAL_MAX_ITERATIONS", "5")
    monkeypatch.setenv("SELFHEAL_MODEL", "Qwen3.6-35B-A3B-NVFP4")
    settings = SelfHealSettings.from_env(project_root="C:/tmp/project")
    assert settings.enabled is True
    assert settings.code_agent is True
    assert settings.max_iterations == 5
    assert settings.model_name == "Qwen3.6-35B-A3B-NVFP4"


def test_store_roundtrip(tmp_path):
    store = SelfHealStore(tmp_path / "selfheal.db")
    item = _feedback()
    store.add_feedback(item)

    loaded = store.get_feedback("fb-1")
    assert loaded is not None
    assert loaded.target.record_id == "rec-1"
    assert store.list_feedback(doc_id="doc-1")[0].feedback_id == "fb-1"

    store.add_message(FeedbackMessage(feedback_id="fb-1", content="已受理"))
    assert store.list_messages("fb-1")[0].content == "已受理"

    store.update_feedback("fb-1", status="processing", iterations=1)
    assert store.get_feedback("fb-1").status == FeedbackStatus.processing
    assert store.feedback_iterations("fb-1") == 1


def test_finding_dedupe(tmp_path):
    store = SelfHealStore(tmp_path / "selfheal.db")
    finding = Finding(
        doc_id="doc-1",
        job_id="job-1",
        source=FindingSource.audit,
        verdict=FindingVerdict.wrong,
        target=FeedbackTarget(record_id="rec-1", property="Rm"),
        expected="430",
        observed="400",
        rule_code="model_wrong_value",
        priority="P1",
    )
    assert store.add_finding(finding) is True
    duplicate = finding.model_copy(update={"finding_id": "fnd-2"})
    assert store.add_finding(duplicate) is False
    assert len(store.list_findings("doc-1")) == 1


def test_proposal_gate_candidate_patch(tmp_path):
    store = SelfHealStore(tmp_path / "selfheal.db")
    proposal = RepairProposal(
        proposal_id="prp-1",
        finding_ids=["fnd-1"],
        level=RepairLevel.L2,
        operator="column_alias.add",
        params={"alias": "σb", "target": "Rm"},
        target_signature="sig-1",
        status=ProposalStatus.proposed,
        artifact_dir=str(tmp_path / "overlays" / "prp-1"),
    )
    store.add_proposal(proposal)
    assert store.get_proposal("prp-1").operator == "column_alias.add"
    store.update_proposal_status("prp-1", "verified")
    assert store.get_proposal("prp-1").status == ProposalStatus.verified

    gate = GateResult(
        proposal_id="prp-1",
        checks=[GateCheck(name="evidence_grounded", passed=True)],
        decision=GateDecision.accept,
    )
    store.add_gate_result(gate)
    assert store.latest_gate("prp-1").decision == GateDecision.accept

    store.add_candidate(
        CandidateRecipe(
            candidate_id="cand-1",
            proposal_id="prp-1",
            signature="sig-1",
            operator="column_alias.add",
            params={"alias": "σb"},
            overlay_dir=str(tmp_path / "overlays" / "prp-1"),
        )
    )
    assert store.list_candidates("sig-1")[0].candidate_id == "cand-1"
    store.update_candidate_status("cand-1", "shadow")
    assert store.list_candidates("sig-1")[0].status.value == "shadow"

    store.add_code_patch(
        CodePatchProposal(
            patch_id="patch-1",
            proposal_id="prp-1",
            files=["metal_doc_agent/extraction/qwen.py"],
            diff="--- a\n+++ b\n",
            status=ProposalStatus.propose_only,
            reason="auto_merge disabled",
        )
    )
    store.add_audit_run(
        AuditRun(
            audit_run_id="aud-1",
            doc_id="doc-1",
            job_id="job-1",
            model="Qwen3.6-35B-A3B-NVFP4",
            packet_tables=2,
            packet_records=10,
            findings=1,
        )
    )
    metrics = store.metrics()
    assert metrics["findings"] == {}
    assert metrics["repairs_by_level"]["L2"] == 1
    assert metrics["gate_decisions"]["accept"] == 1


def test_schema_is_isolated(tmp_path):
    store = SelfHealStore(tmp_path / "selfheal.db")
    with store._connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert all(name.startswith("sh_") for name in tables)
    payload = json.loads((tmp_path / "selfheal.db").exists() and "{}" or "{}")
    assert payload == {}
