import pytest

from services.orchestration.state import (
    InvalidTransition,
    RunState,
    ensure_transition,
    is_terminal,
)


def test_valid_transitions() -> None:
    ensure_transition(RunState.RECEIVED, RunState.OCR_RUNNING)
    ensure_transition(RunState.OCR_RUNNING, RunState.OCR_DONE)
    ensure_transition(RunState.OCR_DONE, RunState.ROUTING)
    ensure_transition(RunState.REVIEW_PASSED, RunState.STRUCTURED_READY)


def test_invalid_transition() -> None:
    with pytest.raises(InvalidTransition):
        ensure_transition(RunState.RECEIVED, RunState.REVIEW_PASSED)
    with pytest.raises(InvalidTransition):
        ensure_transition(RunState.STRUCTURED_READY, RunState.OCR_RUNNING)


def test_failure_allowed_from_non_terminal() -> None:
    for state in RunState:
        if state in {RunState.STRUCTURED_READY, RunState.FAILED, RunState.CANCELLED}:
            continue
        ensure_transition(state, RunState.FAILED)


def test_terminal_states() -> None:
    assert is_terminal(RunState.STRUCTURED_READY)
    assert is_terminal(RunState.FAILED)
    assert not is_terminal(RunState.OCR_RUNNING)
