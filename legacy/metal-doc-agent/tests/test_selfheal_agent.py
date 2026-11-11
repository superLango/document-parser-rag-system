"""Agent diagnosis, source-grounded correction and patch guards."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from metal_doc_agent.pipeline import run_pipeline
from metal_doc_agent.settings import Settings
from metal_doc_agent.selfheal.compat import check_compat
from metal_doc_agent.selfheal.config import SelfHealSettings
from metal_doc_agent.selfheal.contracts import (
    FeedbackCategory,
    FeedbackCreate,
    FeedbackStatus,
    FeedbackTarget,
)
from metal_doc_agent.selfheal.diagnose import diagnose
from metal_doc_agent.selfheal.feedback import FeedbackService
from metal_doc_agent.selfheal.locate import load_result
from metal_doc_agent.selfheal.patch_guard import check_patch
from metal_doc_agent.selfheal.pipeline import SelfHealPipeline
from metal_doc_agent.selfheal.resolve import resolve_correction
from metal_doc_agent.selfheal.storage import SelfHealStore

AGENT_ROOT = Path(__file__).resolve().parents[1]
MD = """# Page 1

# 铝合金室温拉伸试验方法

GB/T 14992-2018

## Table

<table border="1">
<tr><td rowspan="2">牌号</td><td colspan="2">力学性能(不小于)</td></tr>
<tr><td>抗拉强度Rm/MPa</td><td>断后伸长率A/%</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
<tr><td>2A15</td><td>400</td><td>8</td></tr>
</table>
"""


def _job(tmp_path: Path) -> tuple[Path, SelfHealSettings]:
    md = tmp_path / "GB-T 14992-2024.md"
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
    heal = dataclasses.replace(
        SelfHealSettings.from_env(project_root=AGENT_ROOT),
        root=tmp_path / "selfheal",
        db_path=tmp_path / "selfheal" / "selfheal.db",
        data_dir=tmp_path / "data",
        model_base_url=None,
    )
    return out, heal


def test_standard_no_is_resolved_from_cover(tmp_path):
    job, settings = _job(tmp_path)
    result = load_result(job)
    diagnosis = diagnose(
        settings,
        result,
        job,
        description="标准编号没有正确解析",
        category="other",
    )
    assert diagnosis.action == "document_meta"
    assert diagnosis.correction is not None
    assert diagnosis.correction.found
    assert "14992-2018" in (diagnosis.correction.value or "")
    assert diagnosis.evidence


def test_missing_item_searches_document_not_dictionary_only(tmp_path):
    job, settings = _job(tmp_path)
    result = load_result(job)
    diagnosis = diagnose(
        settings,
        result,
        job,
        description="持久项目没有正确解析出来",
        category="missing_value",
    )
    assert diagnosis.scope == "missing_item"
    assert diagnosis.action == "reparse"
    assert diagnosis.checks
    assert diagnosis.rule_change is not None


def test_requirement_error_is_not_treated_as_missing(tmp_path):
    job, settings = _job(tmp_path)
    result = load_result(job)
    diagnosis = diagnose(
        settings,
        result,
        job,
        description="室温拉伸标准要求没有解析正确",
        category="wrong_requirement",
    )
    assert diagnosis.scope != "missing_item"
    assert diagnosis.action in {"table_repair", "reparse", "rule_fix"}


def test_field_cell_is_the_resolved_value(tmp_path):
    job, _ = _job(tmp_path)
    result = load_result(job)
    record = result.records[0]
    correction = resolve_correction(
        result,
        job,
        description="抗拉强度不对",
        target=FeedbackTarget(
            record_id=record.record_id,
            property="Rm",
            table_id=record.source_table_id,
        ),
        expected=None,
    )
    assert correction.checked
    assert correction.found or correction.value is None


def test_patch_guard_rejects_case_literals_and_dictionary():
    diff = (
        "--- a/metal_doc_agent/extraction/qwen.py\n"
        "+++ b/metal_doc_agent/extraction/qwen.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        '+if grade == "2A14":\n'
    )
    ok, detail = check_patch(
        diff, ["metal_doc_agent/extraction/qwen.py"], ["2A14"]
    )
    assert not ok
    assert "硬编码" in detail

    dictionary = (
        "--- a/configs/dictionaries/items.json\n"
        "+++ b/configs/dictionaries/items.json\n"
        "@@ -1 +1 @@\n"
        "-a\n+b\n"
    )
    ok, detail = check_patch(
        dictionary, ["configs/dictionaries/items.json"], []
    )
    assert not ok
    assert "词典" in detail


def test_compat_rejects_removed_definition():
    diff = (
        "--- a/metal_doc_agent/extraction/qwen.py\n"
        "+++ b/metal_doc_agent/extraction/qwen.py\n"
        "@@ -10 +10 @@\n"
        "-def parse_numeric(text):\n"
        "+def parse_numeric_v2(text):\n"
    )
    ok, detail = check_compat(
        diff, ["metal_doc_agent/extraction/qwen.py"]
    )
    assert not ok
    assert "删除" in detail


def test_feedback_standard_no_is_fixed_and_waiting_for_confirm(tmp_path):
    job, settings = _job(tmp_path)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    service = FeedbackService(store, settings)
    pipeline = SelfHealPipeline(store, settings)
    result = load_result(job)

    created = service.create(
        FeedbackCreate(
            doc_id=result.document.doc_id,
            job_id="job-1",
            category=FeedbackCategory.other,
            description="标准编号没有正确解析",
        )
    )
    assert created["problems"] == []
    outcome = pipeline.process_feedback(created["feedback"].feedback_id)
    assert outcome.status == FeedbackStatus.fixed
    assert "GB/T 14992-2018" in outcome.reply
    assert "依据" in outcome.reply
    patched = (
        settings.jobs_root
        / created["feedback"].feedback_id
        / "document_meta"
        / "result.json"
    )
    assert patched.exists()
