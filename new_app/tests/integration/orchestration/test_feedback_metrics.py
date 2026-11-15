from __future__ import annotations

from services.orchestration.feedback.metrics import (
    render_markdown,
    summarize_feedbacks,
)


def _item(
    feedback_id: str,
    status: str = "verified",
    *,
    intent: dict | None = None,
    diagnosis: dict | None = None,
    proposal: dict | None = None,
    verification: dict | None = None,
    created: str = "2026-11-13T10:00:00+00:00",
    updated: str = "2026-11-13T10:00:20+00:00",
    messages: list | None = None,
) -> dict:
    return {
        "id": feedback_id,
        "status": status,
        "target": {"rule_id": "DOC-NO-RECORDS"},
        "root_cause": {
            "triage": {"root_cause": "table_structure"},
            "intent": intent or {},
            "diagnosis": diagnosis or {},
            "repairability": {"decision": "data"},
        },
        "proposal": proposal or {},
        "verification": verification or {},
        "messages": messages or [],
        "created_at": created,
        "updated_at": updated,
    }


def _intent(
    table_ids: list[str],
    *,
    concept_id: str = "tensile_room",
    rerank: bool = False,
    clarifying: str = "",
) -> dict:
    return {
        "concept_id": concept_id,
        "concept": "室温拉伸",
        "category": "unspecified",
        "scope": "table",
        "candidate_targets": [
            {"table_id": table_id, "page_no": index + 1, "confidence": 0.7}
            for index, table_id in enumerate(table_ids)
        ],
        "rerank": {"applied": rerank},
        "clarifying_question": clarifying,
        "assumption": "按表核对",
    }


def _diagnosis(**extra) -> dict:
    payload = {
        "root_cause": "table_structure",
        "action": "table_repair",
        "scope": "table",
        "expected": None,
        "needs_model": True,
        "model_attribution": {"applied": True},
        "rule_change": {"rule_id": "x", "before": "a", "after": "b"},
        "evidence_count": 1,
    }
    payload.update(extra)
    return payload


def test_summary_counts_status_and_l1() -> None:
    items = [
        _item(
            "f1",
            "verified",
            verification={"affected_targets": [{"level": "L1"}], "decision": "accept"},
        ),
        _item(
            "f2",
            "needs_more_info",
            verification={
                "affected_targets": [{"level": "L1"}],
                "decision": "rollback",
            },
        ),
        _item("f3", "needs_more_info"),
    ]
    summary = summarize_feedbacks(items)
    assert summary["total"] == 3
    assert summary["status_dist"] == {"verified": 1, "needs_more_info": 2}
    assert summary["verified_rate"] == 0.3333
    assert summary["human_takeover_rate"] == 0.6667
    assert summary["l1_attempts"] == 2
    assert summary["l1_rollbacks"] == 1
    assert summary["l1_success_rate"] == 0.5


def test_summary_intent_metrics_and_gold_accuracy() -> None:
    items = [
        _item("f1", "verified", intent=_intent(["T12", "T13"], rerank=True)),
        _item("f2", "needs_more_info", intent=_intent(["T18", "T12"], clarifying="哪张表？")),
        _item("f3", "verified", intent=_intent(["T20"], concept_id="impact")),
    ]
    gold = {"f1": {"table_id": "T12"}, "f2": {"table_id": "T12"}}
    summary = summarize_feedbacks(items, gold=gold)
    assert summary["intent"]["rerank_rate"] == 0.3333
    assert summary["intent"]["clarifying_rate"] == 0.3333
    assert summary["intent"]["labeled"] == 2
    assert summary["intent"]["top1_accuracy"] == 0.5
    assert summary["intent"]["top3_accuracy"] == 1.0
    assert summary["intent"]["concepts"]["tensile_room"]["total"] == 2
    assert summary["intent"]["concepts"]["tensile_room"]["top1_accuracy"] == 0.5
    assert summary["intent"]["concepts"]["impact"]["total"] == 1


def test_summary_diagnosis_completeness() -> None:
    items = [
        _item("f1", diagnosis=_diagnosis()),
        _item(
            "f2",
            diagnosis=_diagnosis(
                expected="≥470",
                model_attribution={"applied": False},
                evidence_count=0,
            ),
        ),
        _item("f3"),
    ]
    summary = summarize_feedbacks(items)
    diagnosis = summary["diagnosis"]
    assert diagnosis["total"] == 2
    assert diagnosis["needs_model_rate"] == 0.6667
    assert diagnosis["model_used_rate"] == 0.5
    assert diagnosis["expected_present_rate"] == 0.5
    assert diagnosis["rule_change_present_rate"] == 1.0
    assert diagnosis["evidence_present_rate"] == 0.5
    assert diagnosis["repairability"] == {"data": 2}


def test_summary_patch_metrics_and_latency() -> None:
    items = [
        _item(
            "f1",
            proposal={"scope": "recipe", "patch": {"ops": [{"op": "add"}, {"op": "add"}]}},
            verification={"action_tier": "review"},
            updated="2026-11-13T10:00:10+00:00",
        ),
        _item(
            "f2",
            "needs_more_info",
            proposal={"scope": "recipe", "patch": {"ops": []}},
            verification={"action_tier": "auto"},
            updated="2026-11-13T10:00:30+00:00",
        ),
    ]
    summary = summarize_feedbacks(items)
    assert summary["patch"]["avg_ops"] == 1.0
    assert summary["patch"]["empty_patch_rate"] == 0.5
    assert summary["action_tiers"] == {"review": 1, "auto": 1}
    assert summary["latency"]["samples"] == 2
    assert summary["latency"]["p50"] == 10.0
    assert summary["latency"]["p95"] == 30.0


def test_summary_collects_gate_failures() -> None:
    items = [
        _item(
            "f1",
            "needs_more_info",
            verification={
                "checks": [
                    {"name": "target_metric", "passed": False},
                    {"name": "required_no_loss", "passed": False},
                    {"name": "no_new_errors", "passed": True},
                ]
            },
        )
    ]
    summary = summarize_feedbacks(items)
    assert summary["check_failures"] == {"target_metric": 1, "required_no_loss": 1}


def test_latency_prefers_message_timestamps() -> None:
    item = _item(
        "f1",
        messages=[
            {"role": "user", "at": "2026-11-13T10:00:00+00:00"},
            {"role": "agent", "at": "2026-11-13T10:00:06+00:00"},
        ],
        updated="2026-11-13T11:00:00+00:00",
    )
    summary = summarize_feedbacks([item])
    assert summary["latency"]["samples"] == 1
    assert summary["latency"]["p50"] == 6.0


def test_render_markdown_contains_sections() -> None:
    summary = summarize_feedbacks(
        [_item("f1", "verified", intent=_intent(["T12"]))]
    )
    markdown = render_markdown(summary)
    assert "# Feedback 闭环度量" in markdown
    assert "## 意图" in markdown
    assert "## 诊断" in markdown
    assert "| 验证通过率 | 1 (100.0%) |" in markdown
