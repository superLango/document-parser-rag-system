from __future__ import annotations

from pathlib import Path

from services.orchestration.feedback.memory import CaseStore, select_reusable_case
from services.orchestration.feedback.service import _proposal_from_case


def _case(**overrides) -> dict:
    base = {
        "fingerprint": "abc123",
        "rule_id": "DOC-NO-RECORDS",
        "level": "L1",
        "patch": {"table_repair": {"table_id": "T1", "spec": {"header_rows": 1}}},
        "feedback_id": "f1",
        "root_cause": "table_structure",
    }
    base.update(overrides)
    return base


def test_select_reusable_case_matches_rule_and_level() -> None:
    cases = [
        _case(level="L2", patch={"ops": [{"op": "add"}]}),
        _case(level="L1"),
    ]
    assert select_reusable_case(cases, rule_id="DOC-NO-RECORDS", level="L1") is cases[1]
    assert select_reusable_case(cases, rule_id="DOC-NO-RECORDS", level="L2") is cases[0]


def test_select_reusable_case_rejects_other_rule_or_empty_patch() -> None:
    cases = [_case(rule_id="DOC-DUP-KEYS"), _case(patch={})]
    assert select_reusable_case(cases, rule_id="DOC-NO-RECORDS") is None


def test_proposal_from_l1_case_keeps_table_repair() -> None:
    proposal = _proposal_from_case(_case())
    assert proposal.scope == "data"
    assert proposal.patch["table_repair"]["table_id"] == "T1"
    assert proposal.needs_human is False
    assert proposal.confidence == 0.9


def test_proposal_from_l2_case_keeps_recipe_ops() -> None:
    case = _case(
        level="L2",
        patch={"ops": [{"op": "add", "path": "/bindings/measures/C", "value": {}}]},
    )
    proposal = _proposal_from_case(case)
    assert proposal.scope == "recipe"
    assert proposal.patch["ops"][0]["path"] == "/bindings/measures/C"


def test_case_store_default_path_is_mounted() -> None:
    path = CaseStore().path.as_posix()
    assert path.endswith("services/orchestration/data/feedback/cases.json")
    assert Path(path).is_absolute() is False
