from __future__ import annotations

from types import SimpleNamespace

from services.orchestration.feedback.suggestions import build_suggestions


def _context(
    *,
    table_id: str = "T5",
    page_no: int = 8,
    unbound: list[str] | None = None,
    admissible: list[str] | None = None,
) -> dict:
    return {
        "problem": {"target": {"table_id": table_id, "page_no": page_no}},
        "recipe": {"unbound_columns": unbound or []},
        "constraints": {
            "admissible": {
                "columns": admissible or [],
                "measures": admissible or [],
            }
        },
    }


def test_engine_suggestion_requests_ocr_fix() -> None:
    suggestions = build_suggestions(
        repairability={"decision": "engine", "reason": "OCR/版面问题"},
        repair_context=_context(table_id="", page_no=0),
    )
    assert suggestions[0]["action"] == "reparse_or_fix_ocr"
    assert suggestions[0]["reason"] == "OCR/版面问题"


def test_data_suggestion_lists_columns() -> None:
    suggestions = build_suggestions(
        diagnosis={"mechanism": "表头合并"},
        repairability={"decision": "data"},
        repair_context=_context(unbound=["Ag", "As", "Bi"]),
    )
    assert suggestions[0]["action"] == "repair_table_structure"
    assert suggestions[0]["table_id"] == "T5"
    assert suggestions[0]["columns"] == ["Ag", "As", "Bi"]


def test_recipe_suggestion_uses_admissible_columns() -> None:
    suggestions = build_suggestions(
        repairability={"decision": "recipe_binding"},
        repair_context=_context(admissible=["C", "Si"]),
    )
    assert suggestions[0]["action"] == "bind_measures"
    assert suggestions[0]["columns"] == ["C", "Si"]


def test_needs_more_info_suggestion_requests_review() -> None:
    suggestions = build_suggestions(
        repairability={"decision": "needs_more_info", "reason": "无可用列"},
    )
    assert suggestions[0]["action"] == "manual_review"
    assert suggestions[0]["reason"] == "无可用列"


def test_no_decision_falls_back_to_manual_triage() -> None:
    suggestions = build_suggestions()
    assert suggestions == [
        {
            "action": "manual_triage",
            "table_id": "",
            "page_no": 0,
            "columns": [],
            "reason": "未定位到可自动修复的表或字段",
            "confidence": 0.0,
            "source": "rule",
        }
    ]


def test_clarification_adds_confirm_table_with_options() -> None:
    intent = {
        "clarification": {
            "question": "你指的是哪张表？",
            "options": [
                {"table_id": "T12", "page_no": 9, "label": "T12"},
                {"table_id": "T13", "page_no": 10, "label": "T13"},
            ],
        }
    }
    suggestions = build_suggestions(intent=intent)
    assert suggestions[0]["action"] == "confirm_table"
    assert len(suggestions[0]["options"]) == 2


def test_needs_human_proposal_adds_review_and_dedupes() -> None:
    proposal = SimpleNamespace(
        needs_human=True,
        summary="spec 越界，无法自动修复",
        confidence=0.3,
    )
    suggestions = build_suggestions(
        repairability={"decision": "needs_more_info", "reason": "规则无法归因"},
        repair_context=_context(),
        proposal=proposal,
    )
    actions = [item["action"] for item in suggestions]
    assert actions == ["manual_review"]
    assert "spec 越界" in suggestions[0]["reason"]


def test_suggestions_cap_columns() -> None:
    columns = [f"M{index}" for index in range(12)]
    suggestions = build_suggestions(
        repairability={"decision": "data"},
        repair_context=_context(unbound=columns),
    )
    assert len(suggestions[0]["columns"]) == 8
