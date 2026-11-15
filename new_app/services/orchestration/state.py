from enum import StrEnum


class RunState(StrEnum):
    RECEIVED = "RECEIVED"
    OCR_RUNNING = "OCR_RUNNING"
    OCR_DONE = "OCR_DONE"
    ROUTING = "ROUTING"
    ROUTED = "ROUTED"
    UNROUTED = "UNROUTED"
    SANDBOX_RUNNING = "SANDBOX_RUNNING"
    PARSED = "PARSED"
    REVIEWING = "REVIEWING"
    REPAIRING = "REPAIRING"
    REPARSING = "REPARSING"
    REVIEW_PASSED = "REVIEW_PASSED"
    REVIEW_FAILED = "REVIEW_FAILED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    STRUCTURED_READY = "STRUCTURED_READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {
    RunState.STRUCTURED_READY,
    RunState.REVIEW_FAILED,
    RunState.HUMAN_REJECTED,
    RunState.UNROUTED,
    RunState.FAILED,
    RunState.CANCELLED,
}

ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.RECEIVED: {RunState.OCR_RUNNING, RunState.FAILED, RunState.CANCELLED},
    RunState.OCR_RUNNING: {RunState.OCR_DONE, RunState.FAILED, RunState.CANCELLED},
    RunState.OCR_DONE: {RunState.ROUTING, RunState.FAILED, RunState.CANCELLED},
    RunState.ROUTING: {
        RunState.ROUTED,
        RunState.UNROUTED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.ROUTED: {RunState.SANDBOX_RUNNING, RunState.FAILED, RunState.CANCELLED},
    RunState.SANDBOX_RUNNING: {RunState.PARSED, RunState.FAILED, RunState.CANCELLED},
    RunState.PARSED: {RunState.REVIEWING, RunState.FAILED, RunState.CANCELLED},
    RunState.REVIEWING: {
        RunState.REPAIRING,
        RunState.REVIEW_PASSED,
        RunState.REVIEW_FAILED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.REPAIRING: {
        RunState.REPARSING,
        RunState.REVIEWING,
        RunState.REVIEW_PASSED,
        RunState.REVIEW_FAILED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.REPARSING: {
        RunState.SANDBOX_RUNNING,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.REVIEW_PASSED: {
        RunState.REPAIRING,
        RunState.HUMAN_REVIEW,
        RunState.STRUCTURED_READY,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.HUMAN_REVIEW: {
        RunState.HUMAN_APPROVED,
        RunState.HUMAN_REJECTED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.HUMAN_APPROVED: {
        RunState.STRUCTURED_READY,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.STRUCTURED_READY: set(),
    RunState.REVIEW_FAILED: set(),
    RunState.HUMAN_REJECTED: set(),
    RunState.UNROUTED: set(),
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
