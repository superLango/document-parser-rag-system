from services.orchestration.shadow_state import (
    EXPIRED,
    FAILED,
    PROMOTED,
    READY,
    WAITING,
    decide_batch_status,
)


def _decide(**overrides):
    values = {
        "completed": 0,
        "failed": 0,
        "required": 10,
        "auto_promote": False,
        "expired": False,
    }
    values.update(overrides)
    return decide_batch_status(**values)


def test_partial_progress_waits() -> None:
    assert _decide(completed=9) == WAITING


def test_full_progress_stops_at_ready_by_default() -> None:
    assert _decide(completed=10) == READY


def test_full_progress_auto_promotes_only_when_enabled() -> None:
    assert _decide(completed=10, auto_promote=True) == PROMOTED


def test_failures_win_over_completion() -> None:
    assert _decide(completed=10, failed=1) == FAILED
    assert _decide(completed=10, failed=1, expired=True) == FAILED


def test_timeout_expires_batch() -> None:
    assert _decide(completed=9, expired=True) == EXPIRED
    assert _decide(completed=10, expired=True) == EXPIRED
    assert _decide(completed=10, auto_promote=True, expired=True) == EXPIRED
