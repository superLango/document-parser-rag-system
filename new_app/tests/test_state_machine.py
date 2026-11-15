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
    ensure_transition(RunState.ROUTING, RunState.UNROUTED)
    ensure_transition(RunState.REVIEWING, RunState.REPAIRING)
    ensure_transition(RunState.REVIEW_PASSED, RunState.REPAIRING)
    ensure_transition(RunState.REPAIRING, RunState.REPARSING)
    ensure_transition(RunState.REPARSING, RunState.SANDBOX_RUNNING)
    ensure_transition(RunState.REVIEWING, RunState.REVIEW_FAILED)
    ensure_transition(RunState.REVIEW_PASSED, RunState.HUMAN_REVIEW)
    ensure_transition(RunState.HUMAN_REVIEW, RunState.HUMAN_APPROVED)
    ensure_transition(RunState.HUMAN_APPROVED, RunState.STRUCTURED_READY)
    ensure_transition(RunState.HUMAN_REVIEW, RunState.HUMAN_REJECTED)
    ensure_transition(RunState.REVIEW_PASSED, RunState.STRUCTURED_READY)


def test_invalid_transition() -> None:
    with pytest.raises(InvalidTransition):
        ensure_transition(RunState.RECEIVED, RunState.REVIEW_PASSED)
    with pytest.raises(InvalidTransition):
        ensure_transition(RunState.STRUCTURED_READY, RunState.OCR_RUNNING)


def test_failure_allowed_from_non_terminal() -> None:
    terminal = {
        RunState.STRUCTURED_READY,
        RunState.REVIEW_FAILED,
        RunState.HUMAN_REJECTED,
        RunState.UNROUTED,
        RunState.FAILED,
        RunState.CANCELLED,
    }
    for state in RunState:
        if state in terminal:
            continue
        ensure_transition(state, RunState.FAILED)


def test_terminal_states() -> None:
    assert is_terminal(RunState.STRUCTURED_READY)
    assert is_terminal(RunState.REVIEW_FAILED)
    assert is_terminal(RunState.HUMAN_REJECTED)
    assert is_terminal(RunState.UNROUTED)
    assert is_terminal(RunState.FAILED)
    assert not is_terminal(RunState.HUMAN_REVIEW)
    assert not is_terminal(RunState.OCR_RUNNING)
