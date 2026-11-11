from enum import StrEnum


class RunState(StrEnum):
    RECEIVED = "RECEIVED"
    OCR_RUNNING = "OCR_RUNNING"
    OCR_DONE = "OCR_DONE"
    ROUTING = "ROUTING"
    ROUTED = "ROUTED"
    SANDBOX_RUNNING = "SANDBOX_RUNNING"
    PARSED = "PARSED"
    REVIEWING = "REVIEWING"
    REVIEW_PASSED = "REVIEW_PASSED"
    STRUCTURED_READY = "STRUCTURED_READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {RunState.STRUCTURED_READY, RunState.FAILED, RunState.CANCELLED}

ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.RECEIVED: {RunState.OCR_RUNNING, RunState.FAILED, RunState.CANCELLED},
    RunState.OCR_RUNNING: {RunState.OCR_DONE, RunState.FAILED, RunState.CANCELLED},
    RunState.OCR_DONE: {RunState.ROUTING, RunState.FAILED, RunState.CANCELLED},
    RunState.ROUTING: {RunState.ROUTED, RunState.FAILED, RunState.CANCELLED},
    RunState.ROUTED: {RunState.SANDBOX_RUNNING, RunState.FAILED, RunState.CANCELLED},
    RunState.SANDBOX_RUNNING: {RunState.PARSED, RunState.FAILED, RunState.CANCELLED},
    RunState.PARSED: {RunState.REVIEWING, RunState.FAILED, RunState.CANCELLED},
    RunState.REVIEWING: {RunState.REVIEW_PASSED, RunState.FAILED, RunState.CANCELLED},
    RunState.REVIEW_PASSED: {RunState.STRUCTURED_READY, RunState.FAILED, RunState.CANCELLED},
    RunState.STRUCTURED_READY: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}


class InvalidTransition(ValueError):
    pass


def ensure_transition(current: str, target: str) -> None:
    try:
        current_state = RunState(current)
        target_state = RunState(target)
    except ValueError as exc:
        raise InvalidTransition(f"unknown state transition: {current} -> {target}") from exc
    if target_state not in ALLOWED_TRANSITIONS[current_state]:
        raise InvalidTransition(f"invalid state transition: {current} -> {target}")


def is_terminal(state: str) -> bool:
    try:
        return RunState(state) in TERMINAL_STATES
    except ValueError:
        return False
