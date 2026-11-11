"""Golden set evaluation utilities."""

from .metrics import (
    evaluate_document,
    evaluate_goldset,
    load_prediction,
    render_markdown,
    run_evaluation,
)
from .regression import (
    build_regression,
    compare_regression,
    load_regression,
    render_regression_markdown,
    write_regression,
)

__all__ = [
    "build_regression",
    "compare_regression",
    "evaluate_document",
    "evaluate_goldset",
    "load_prediction",
    "load_regression",
    "render_markdown",
    "render_regression_markdown",
    "run_evaluation",
    "write_regression",
]
