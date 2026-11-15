from __future__ import annotations

from services.agent.agents.analysis import parse_diagnosis, parse_intent_rerank
from services.orchestration.feedback.diagnosis import (
    merge_model_diagnosis,
    needs_model_attribution,
)
from services.orchestration.feedback.intent import (
    _build_clarification,
    apply_rerank,
    needs_clarification,
    needs_rerank,
)


def _intent(*candidates: dict) -> dict:
    return {
        "scope": "table",
        "candidate_targets": list(candidates),
        "confidence": 0.6,
        "evidence": [],
    }


def _candidate(table_id: str, page_no: int, records: int, confidence: float) -> dict:
    return {
        "table_id": table_id,
        "page_no": page_no,
        "reason": "表题命中室温拉伸",
        "records": records,
        "confidence": confidence,
    }


def test_needs_rerank_on_tied_confidence() -> None:
    intent = _intent(
        _candidate("T12", 9, 18, 0.75),
        _candidate("T13", 10, 18, 0.75),
    )
    assert needs_rerank(intent) is True


def test_needs_rerank_false_when_clear_winner() -> None:
    intent = _intent(
        _candidate("T12", 9, 18, 0.9),
        _candidate("T13", 10, 3, 0.5),
    )
    assert needs_rerank(intent) is False


def test_needs_rerank_false_for_non_table_scope() -> None:
    intent = _intent(_candidate("T12", 9, 18, 0.75), _candidate("T13", 10, 18, 0.75))
    intent["scope"] = "document"
    assert needs_rerank(intent) is False


def test_apply_rerank_moves_chosen_candidate_first() -> None:
    intent = _intent(
        _candidate("T12", 9, 18, 0.75),
        _candidate("T13", 10, 18, 0.75),
    )
    result = apply_rerank(
        intent,
        {"model_used": True, "table_id": "T13", "reason": "cap", "confidence": 0.85},
    )
    assert result["candidate_targets"][0]["table_id"] == "T13"
    assert result["rerank"]["applied"] is True
    assert result["assumption"].endswith("（模型重排）")
    assert result["clarifying_question"] is None


def test_apply_rerank_keeps_rule_order_on_unknown_table() -> None:
    intent = _intent(
        _candidate("T12", 9, 18, 0.75),
        _candidate("T13", 10, 18, 0.75),
    )
    result = apply_rerank(
        intent,
        {"model_used": True, "table_id": "T99", "reason": "", "confidence": 0.9},
    )
    assert result["candidate_targets"][0]["table_id"] == "T12"
    assert result["rerank"]["applied"] is False


def test_parse_intent_rerank_rejects_id_outside_candidates() -> None:
    output = parse_intent_rerank(
        {"table_id": "T99", "reason": "x", "confidence": 0.9},
        {"candidates": [{"table_id": "T12"}]},
    )
    assert output["model_used"] is False


def test_parse_intent_rerank_accepts_known_id() -> None:
    output = parse_intent_rerank(
        {"table_id": "T12", "reason": "cap", "confidence": 1.5},
        {"candidates": [{"table_id": "T12"}]},
    )
    assert output["model_used"] is True
    assert output["confidence"] == 1.0


def test_clarification_for_tied_candidates() -> None:
    candidates = [
        _candidate("T12", 9, 18, 0.75),
        _candidate("T13", 10, 18, 0.75),
    ]
    clarification = _build_clarification("table", candidates, 0.75)
    assert clarification is not None
    assert clarification["reason"] == "tie"
    assert len(clarification["options"]) == 3
    assert "A." in clarification["question"]
    assert "都不是" in clarification["question"]


def test_clarification_for_low_confidence_single_candidate() -> None:
    clarification = _build_clarification(
        "table", [_candidate("T12", 9, 3, 0.42)], 0.42
    )
    assert clarification is not None
    assert clarification["reason"] == "low_confidence"
    assert clarification["options"][0]["table_id"] == "T12"


def test_no_clarification_for_confident_single_candidate() -> None:
    assert _build_clarification("table", [_candidate("T12", 9, 18, 0.9)], 0.9) is None


def test_no_clarification_outside_table_scope() -> None:
    assert (
        _build_clarification("document", [_candidate("T12", 9, 18, 0.4)], 0.4)
        is None
    )


def test_needs_clarification_respects_applied_rerank() -> None:
    intent = {"clarification": {"question": "哪张表？"}, "rerank": {"applied": True}}
    assert needs_clarification(intent) is False
    intent["rerank"] = {"applied": False}
    assert needs_clarification(intent) is True


def test_apply_rerank_clears_clarification() -> None:
    intent = _intent(
        _candidate("T12", 9, 18, 0.75),
        _candidate("T13", 10, 18, 0.75),
    )
    intent["clarification"] = {"question": "哪张表？"}
    result = apply_rerank(
        intent,
        {"model_used": True, "table_id": "T13", "reason": "cap", "confidence": 0.9},
    )
    assert result["clarification"] is None
    assert result["clarifying_question"] is None


def test_parse_diagnosis_normalizes_aliases_and_action() -> None:
    output = parse_diagnosis(
        {
            "root_cause": "layout",
            "action": "not-an-action",
            "scope": "table",
            "mechanism": "m",
            "confidence": 0.7,
        },
        {"rule_diagnosis": {"scope": "table"}},
    )
    assert output["root_cause"] == "ocr_error"
    assert output["action"] == "reparse"
    assert output["model_used"] is True


def test_parse_diagnosis_rejects_unknown_root_cause() -> None:
    output = parse_diagnosis(
        {"root_cause": "made_up", "action": "rule_fix", "scope": "table"},
        {"rule_diagnosis": {}},
    )
    assert output["model_used"] is False


def test_needs_model_attribution_only_for_rule_flagged() -> None:
    assert needs_model_attribution({"needs_model": True, "source": "rule"}) is True
    assert needs_model_attribution({"needs_model": False, "source": "rule"}) is False
    assert needs_model_attribution({"needs_model": True, "source": "model"}) is False


def test_merge_model_diagnosis_overrides_and_filters_evidence() -> None:
    rule = {
        "root_cause": "unknown",
        "action": "report_only",
        "scope": "document",
        "mechanism": "rule",
        "needs_model": True,
        "source": "rule",
        "evidence": [],
    }
    model = {
        "model_used": True,
        "root_cause": "table_structure",
        "action": "table_repair",
        "scope": "table",
        "mechanism": "merged header",
        "confidence": 0.82,
        "evidence": [
            {"table_id": "T5", "quote": "化学成分"},
            {"table_id": "T9", "quote": "other table"},
        ],
    }
    merged = merge_model_diagnosis(rule, model, table_id="T5")
    assert merged["root_cause"] == "table_structure"
    assert merged["action"] == "table_repair"
    assert merged["source"] == "model"
    assert merged["evidence"] == [{"table_id": "T5", "quote": "化学成分"}]
    assert merged["model_attribution"]["applied"] is True


def test_merge_model_diagnosis_keeps_rule_when_model_unused() -> None:
    rule = {
        "root_cause": "unknown",
        "action": "report_only",
        "scope": "document",
        "needs_model": True,
        "source": "rule",
    }
    merged = merge_model_diagnosis(rule, {"model_used": False}, table_id="T5")
    assert merged["root_cause"] == "unknown"
    assert merged["source"] == "rule"
    assert merged["model_attribution"]["applied"] is False
