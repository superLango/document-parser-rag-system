"""Error → repair action mapping under budget (M3.2-01/02).

The mapping is deliberately small: each error class has at most one automatic
action, and every action consumes a retry from the budget. When the budget is
exhausted the graph goes to the human queue instead of looping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .state import OrchestrationState

RepairAction = Literal["retry_ocr", "retry_extract", "human", "stop"]

OCR_QUALITY_FLOOR = 0.6

RETRYABLE_ERROR_CODES = {
    "EVIDENCE_NOT_FOUND",
    "MISSING_EVIDENCE_ID",
    "EMPTY_EVIDENCE_QUOTE",
    "EVIDENCE_TABLE_NOT_FOUND",
    "EVIDENCE_PAGE_MISMATCH",
    "EVIDENCE_LOCATOR_MISSING",
    "EVIDENCE_CELL_OUT_OF_RANGE",
    "EVIDENCE_QUOTE_MISMATCH",
    "EVIDENCE_ID_MISMATCH",
}
RETRYABLE_PREFIXES = ("VALUE_", "UNIT_", "COMPARATOR_", "RANGE_", "MISSING_RAW")


@dataclass(frozen=True)
class RepairDecision:
    action: RepairAction
    reason: str
    code: str

    def to_dict(self) -> dict:
        return {"action": self.action, "reason": self.reason, "code": self.code}


def decide_repair(
    state: OrchestrationState,
    *,
    ocr_quality: float,
    audit_status: str,
    issue_codes: list[str],
    coverage_missing: int,
) -> RepairDecision:
    if ocr_quality < OCR_QUALITY_FLOOR and state.retries.ocr < state.budget.max_ocr_retries:
        return RepairDecision("retry_ocr", f"ocr_quality={ocr_quality:.3f}", "ocr_low_quality")

    last_error = state.errors[-1] if state.errors else None
    if last_error is not None and last_error.retryable:
        if state.retries.extract < state.budget.max_extract_retries:
            return RepairDecision(
                "retry_extract", last_error.message or last_error.code, last_error.code
            )
        return RepairDecision(
            "human", f"retry budget exhausted: {last_error.code}", "retry_exhausted"
        )

    if audit_status == "fail":
        retryable = [
            code
            for code in issue_codes
            if code in RETRYABLE_ERROR_CODES or str(code).startswith(RETRYABLE_PREFIXES)
        ]
        if retryable and state.retries.extract < state.budget.max_extract_retries:
            return RepairDecision(
                "retry_extract",
                f"{len(retryable)} retryable issue(s): {retryable[0]}",
                retryable[0],
            )
        return RepairDecision("human", f"audit failed: {issue_codes[:3]}", "audit_failed")

    if coverage_missing > 0:
        # Targeted retrieval/re-OCR per missing field is not implemented yet;
        # re-running the whole extractor does not add coverage, so the item goes
        # to the human queue instead of burning the retry budget.
        return RepairDecision(
            "human", f"coverage missing without targeted retrieval: {coverage_missing}", "coverage_gap"
        )

    if audit_status == "review":
        return RepairDecision("human", "audit review required", "audit_review")

    return RepairDecision("stop", "no repair needed", "ok")
