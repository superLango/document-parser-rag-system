"""Stage D tests: L2 overlay operators, shadow scoring, L3 patch policy."""

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
    ProposalStatus,
)
from metal_doc_agent.selfheal.feedback import FeedbackService
from metal_doc_agent.selfheal.storage import SelfHealStore
from metal_doc_agent.selfheal.l2 import (
    L2Repairer,
    rollback_overlay,
    signature_for_result,
    validate_operator,
)
from metal_doc_agent.selfheal.l1 import L1Repairer
from metal_doc_agent.selfheal.l3 import CodePatchService, check_policy, diff_line_count
from metal_doc_agent.selfheal.locate import load_result
from metal_doc_agent.selfheal.locator import locate_target
from metal_doc_agent.selfheal.pipeline import SelfHealPipeline
from metal_doc_agent.selfheal.planner import _render_prompt
from metal_doc_agent.selfheal.table_fix import _validated_spec, plan_table_fix
from metal_doc_agent.selfheal.triage import analyze_feedback

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


def _settings(tmp_path: Path, **overrides) -> SelfHealSettings:
    base = dataclasses.replace(
        SelfHealSettings.from_env(project_root=AGENT_ROOT),
        root=tmp_path / "selfheal",
        db_path=tmp_path / "selfheal" / "selfheal.db",
        data_dir=tmp_path / "data",
    )
    return dataclasses.replace(base, **overrides) if overrides else base


def _finding(job: Path) -> Finding:
    result = load_result(job)
    record = result.records[0]
    record_id = record.record_id
    return Finding(
        doc_id=result.document.doc_id,
        job_id="job-1",
        source=FindingSource.user,
        verdict=FindingVerdict.wrong,
        target=FeedbackTarget(record_id=record_id, property="Rm", table_id="T1"),
        expected="440",
        observed=record.properties["Rm"].raw,
    )


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_operator_validation():
    assert validate_operator("unknown.op", {}) == ["未注册的算子：unknown.op"]
    assert validate_operator("column_alias.add", {"alias": "σb"})
    assert validate_operator(
        "column_alias.add", {"alias": "σb", "property": "Rm"}
    ) == []


def test_l1_plan_maps_trace_adapter_name(job, tmp_path):
    trace_path = job / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace.setdefault("versions", {})["ocr"] = "glm-ocr"
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")

    plan = L1Repairer(_settings(tmp_path)).plan(_finding(job), job)
    assert plan["ocr"] == "glm"


def test_locator_finds_record_from_description(job):
    result = load_result(job)
    located = locate_target(result, "2A14 的 Rm 不对，应为 440")
    assert located is not None
    assert located.target.property == "Rm"
    assert located.target.grade == "2A14"
    assert located.target.record_id
    assert located.expected == "440"


def test_feedback_without_record_uses_locator(job, tmp_path):
    settings = _settings(tmp_path, model_base_url=None)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    service = FeedbackService(store, settings)
    result = load_result(job)

    outcome = service.create(
        FeedbackCreate(
            doc_id=result.document.doc_id,
            job_id="job-1",
            category=FeedbackCategory.wrong_value,
            description="2A14 的 Rm 不对，应为 440",
        )
    )
    assert outcome["problems"] == []
    assert outcome["feedback"].target.property == "Rm"
    assert outcome["feedback"].expected_value == "440"
    assert outcome["finding"] is not None
    assert outcome["finding"].target.property == "Rm"
    assert outcome["finding"].expected == "440"


def test_table_fix_plan_rejects_fabricated_values():
    from metal_doc_agent.contracts import TableGrid

    table = TableGrid(
        table_id="T1",
        page_no=1,
        n_rows=3,
        n_cols=2,
        header_rows=1,
        rows=[
            ["牌号", "RmMPa，≥"],
            ["MA1fr 32", "590"],
            ["", ""],
        ],
        header_paths=[["牌号"], ["室温"]],
        profile="mechanical_properties",
    )
    accepted = _validated_spec(
        {"header_rows": 2, "patch_cells": {"1": {"1": "≥590"}}}, table
    )
    assert accepted is not None
    assert accepted["header_rows"] == 2
    assert accepted["patch_cells"]["1"]["1"] == "≥590"

    rejected = _validated_spec({"patch_cells": {"1": {"1": "≥999"}}}, table)
    assert rejected is None
    assert plan_table_fix(
        table, [], "室温拉伸有问题", model_url=None, model_name=""
    ) is None


def test_table_level_feedback_is_located_for_audit(job):
    result = load_result(job)
    analysis = analyze_feedback(
        result,
        "室温拉伸大部分内容都有问题",
        category="wrong_value",
    )
    assert analysis.scope == "table"
    assert analysis.target.table_id == "T1"
    assert analysis.action == "audit"
    assert analysis.rule_code == "user_feedback_table"


def test_table_level_feedback_creates_audit_finding(job, tmp_path):
    settings = _settings(tmp_path, model_base_url=None)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    service = FeedbackService(store, settings)
    result = load_result(job)

    outcome = service.create(
        FeedbackCreate(
            doc_id=result.document.doc_id,
            job_id="job-1",
            category=FeedbackCategory.wrong_table,
            description="室温拉伸大部分内容都有问题",
        )
    )
    assert outcome["problems"] == []
    assert outcome["finding"] is not None
    assert outcome["finding"].target.table_id == "T1"
    assert outcome["finding"].rule_code == "user_feedback_table"


def test_table_feedback_returns_evidence(job, tmp_path):
    settings = _settings(tmp_path, model_base_url=None)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    pipeline = SelfHealPipeline(store, settings)
    service = FeedbackService(store, settings)
    result = load_result(job)
    outcome = service.create(
        FeedbackCreate(
            doc_id=result.document.doc_id,
            job_id="job-1",
            category=FeedbackCategory.wrong_table,
            description="室温拉伸大部分内容都有问题",
        )
    )
    repaired = pipeline.process_feedback(outcome["feedback"].feedback_id)
    assert "判定：" in repaired.reply
    assert "依据" in repaired.reply


def test_vague_feedback_is_accepted_and_diagnosed(job, tmp_path):
    settings = _settings(tmp_path, model_base_url=None)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    service = FeedbackService(store, settings)
    result = load_result(job)

    outcome = service.create(
        FeedbackCreate(
            doc_id=result.document.doc_id,
            job_id="job-1",
            category=FeedbackCategory.wrong_value,
            description="这个结果有点问题",
        )
    )
    assert outcome["problems"] == []
    assert outcome["feedback"].status == FeedbackStatus.open


def test_repeated_feedback_gets_distinct_findings(job, tmp_path):
    settings = _settings(tmp_path)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    service = FeedbackService(store, settings)
    result = load_result(job)
    record = result.records[0]
    payload = FeedbackCreate(
        doc_id=result.document.doc_id,
        job_id="job-1",
        category=FeedbackCategory.wrong_value,
        target=FeedbackTarget(
            record_id=record.record_id, property="Rm", table_id="T1"
        ),
        expected_value="430",
    )

    first = service.create(payload)
    second = service.create(payload)
    assert first["finding"] is not None
    assert second["finding"] is not None
    assert first["finding"].finding_id != second["finding"].finding_id
    assert store.list_findings_for_feedback(second["feedback"].feedback_id)


def test_planner_prompt_keeps_json_example(job):
    finding = _finding(job)
    prompt = _render_prompt(
        finding, {"header": [["牌号"]], "record": {"record_id": "r1"}}
    )
    assert '{"operator":' in prompt
    assert finding.finding_id in prompt


def test_signature_is_stable(job):
    result = load_result(job)
    first = signature_for_result(result, "T1")
    second = signature_for_result(result, "T1")
    assert first == second
    assert signature_for_result(result, None) != ""


def test_column_alias_overlay_isolated(job, tmp_path):
    settings = _settings(tmp_path)
    production = AGENT_ROOT / "configs" / "column_aliases.json"
    before = _hash(production)
    repairer = L2Repairer(settings)
    proposal, candidate = repairer.propose(
        _finding(job),
        job,
        "column_alias.add",
        {"alias": "σ_b测试别名", "property": "Rm"},
    )
    assert _hash(production) == before
    overlay = Path(proposal.artifact_dir)
    payload = json.loads((overlay / "project" / "configs" / "column_aliases.json").read_text(encoding="utf-8"))
    assert "σ_b测试别名" in payload["property_aliases"]["Rm"]
    assert candidate.signature == proposal.target_signature
    assert proposal.status == ProposalStatus.sandbox
    manifest = json.loads((overlay / "overlay_manifest.json").read_text(encoding="utf-8"))
    assert manifest["effective"] is True


def test_table_repair_shadow_resolves(job, tmp_path):
    settings = _settings(tmp_path)
    result = load_result(job)
    doc_key = result.document.doc_id
    finding = _finding(job)
    repairer = L2Repairer(settings)
    proposal, _ = repairer.propose(
        finding,
        job,
        "table_repair.add",
        {
            "document_key": doc_key,
            "table_id": "T1",
            "spec": {"patch_cells": {"2": {"1": "440"}}},
        },
    )
    diff = repairer.shadow(proposal, finding, job, job / "shadow")
    assert diff["target_resolved"] is True
    assert diff["new_errors"] == 0
    assert (job / "shadow" / "result.json").exists()


def test_recipe_override_requires_existing_recipe(job, tmp_path):
    repairer = L2Repairer(_settings(tmp_path))
    with pytest.raises(ValueError):
        repairer.propose(
            _finding(job),
            job,
            "recipe.binding_override",
            {"recipe_id": "no_such_recipe", "bindings": {"row_key": ["牌号"]}},
        )


def test_rollback_archives_overlay(job, tmp_path):
    repairer = L2Repairer(_settings(tmp_path))
    proposal, _ = repairer.propose(
        _finding(job),
        job,
        "column_alias.add",
        {"alias": "临时别名", "property": "Rm"},
    )
    overlay = Path(proposal.artifact_dir)
    assert overlay.exists()
    rollback_overlay(proposal)
    assert not overlay.exists()
    assert overlay.with_name(overlay.name + ".rolled_back").exists()


VALID_DIFF = """--- a/metal_doc_agent/extraction/qwen.py
+++ b/metal_doc_agent/extraction/qwen.py
@@ -1,2 +1,3 @@
 import json
+import re
--- a/tests/selfheal/test_new_rule.py
+++ b/tests/selfheal/test_new_rule.py
@@ -0,0 +1,2 @@
+def test_new_rule():
+    assert True
"""


def test_diff_line_count():
    assert diff_line_count(VALID_DIFF) == 3


def test_l3_policy_accepts_whitelisted_diff():
    policy = check_policy(VALID_DIFF)
    assert policy.passed, policy.detail
    assert policy.files == [
        "metal_doc_agent/extraction/qwen.py",
        "tests/selfheal/test_new_rule.py",
    ]


def test_l3_policy_rejects_forbidden_and_large():
    forbidden = VALID_DIFF.replace("metal_doc_agent/extraction/qwen.py", "apps/api/main.py")
    assert not check_policy(forbidden).passed
    missing_test = """--- a/metal_doc_agent/extraction/qwen.py
+++ b/metal_doc_agent/extraction/qwen.py
@@ -1 +1 @@
-a
+b
"""
    assert not check_policy(missing_test).passed
    big = "--- a/metal_doc_agent/extraction/qwen.py\n+++ b/metal_doc_agent/extraction/qwen.py\n"
    big += "".join(f"+line {index}\n" for index in range(250))
    assert not check_policy(big).passed


def test_l3_disabled_returns_none(job, tmp_path):
    service = CodePatchService(_settings(tmp_path, code_agent=False))
    assert service.propose(_finding(job), "prp-1", VALID_DIFF) is None


def test_l3_proposal_only_without_git(job, tmp_path):
    settings = _settings(tmp_path, code_agent=True, auto_merge=True)
    service = CodePatchService(settings)
    patch = service.propose(_finding(job), "prp-l3", VALID_DIFF)
    assert patch is not None
    assert patch.status == ProposalStatus.propose_only
    assert "无 .git" in patch.reason
    assert (settings.patches_root / "prp-l3" / "patch.diff").exists()
