from __future__ import annotations

from services.orchestration.workflow import _canary_selected, _canary_should_pin


def test_canary_percent_boundaries() -> None:
    assert _canary_selected("run-1", 0) is False
    assert _canary_selected("run-1", 100) is True


def test_canary_selection_is_stable() -> None:
    assert _canary_selected("run-abc", 10) == _canary_selected("run-abc", 10)


def test_canary_selection_is_roughly_ten_percent() -> None:
    selected = sum(
        1 for index in range(2000) if _canary_selected(f"run-{index}", 10)
    )
    assert 120 <= selected <= 280


def test_canary_skips_when_candidate_matches_stable() -> None:
    assert (
        _canary_should_pin("run-1", 100, candidate="1.0.27", stable="1.0.27") is False
    )
    assert _canary_should_pin("run-1", 100, candidate=None, stable="1.0.27") is False
    assert (
        _canary_should_pin("run-1", 100, candidate="1.0.28", stable="1.0.27") is True
    )
