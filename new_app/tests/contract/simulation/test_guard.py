import pytest

from services.orchestration.simulation import (
    SIMULATED_RUN_NOT_ACCEPTABLE,
    is_simulated,
    reject_simulated,
)


def test_missing_marker_is_real() -> None:
    assert is_simulated({}) is False
    assert is_simulated({"records": []}) is False
    assert is_simulated(None) is False


def test_marker_detected() -> None:
    assert is_simulated({"simulated": True}) is True
    assert is_simulated({"simulated": False}) is False


def test_reject_simulated_raises_with_code() -> None:
    with pytest.raises(ValueError) as exc:
        reject_simulated({"simulated": True}, role="ocr")
    assert SIMULATED_RUN_NOT_ACCEPTABLE in str(exc.value)
    reject_simulated({"records": []}, role="records")
