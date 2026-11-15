"""P2-01: stage progress mapping is monotonic and terminal values are stable."""

from services.orchestration.state import RunState
from services.orchestration.workflow import progress_for


def test_progress_is_monotonic_across_main_stages() -> None:
    ordered = [
        RunState.RECEIVED,
        RunState.OCR_RUNNING,
        RunState.OCR_DONE,
        RunState.ROUTING,
        RunState.ROUTED,
        RunState.SANDBOX_RUNNING,
        RunState.PARSED,
        RunState.REVIEWING,
        RunState.REVIEW_PASSED,
        RunState.HUMAN_REVIEW,
        RunState.STRUCTURED_READY,
    ]
    values = [progress_for(state) for state in ordered]
    assert values == sorted(values)
    assert values[0] == 0
    assert values[-1] == 100


def test_repair_and_reparse_do_not_claim_completion() -> None:
    assert progress_for(RunState.REPAIRING) <= progress_for(RunState.REVIEW_PASSED)
    assert progress_for(RunState.REPARSING) < progress_for(RunState.REVIEWING)
