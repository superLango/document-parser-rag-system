from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "benchmark"))

from teds import teds_score  # noqa: E402


def test_identical_grids_score_one() -> None:
    grid = [["牌号", "Rm"], ["Q355B", "470"]]
    assert teds_score(grid, [list(row) for row in grid]) == 1.0


def test_single_cell_difference_reduces_score() -> None:
    expected = [["牌号", "Rm"], ["Q355B", "470"]]
    actual = [["牌号", "Rm"], ["Q355B", "480"]]
    score = teds_score(expected, actual)
    assert 0.5 < score < 1.0


def test_missing_row_reduces_score_more() -> None:
    expected = [["牌号", "Rm"], ["Q355B", "470"], ["Q390B", "490"]]
    actual = [["牌号", "Rm"], ["Q355B", "470"]]
    assert teds_score(expected, actual) < teds_score(
        expected, [["牌号", "Rm"], ["Q355B", "470"], ["Q390B", "500"]]
    )


def test_empty_tables_score_one() -> None:
    assert teds_score([], []) == 1.0
