"""Decide the adaptation level for an edition drift report (P1-12).

L0 -> nothing, L1 -> patch the stored profile, L2 -> recipe candidate,
L3 -> code candidate.  L2/L3 are only planned here: they must go through the
sandbox and a human diff before promotion, and old editions keep their pins.
"""

from __future__ import annotations

from .drift import MEASURE_MISS_RATIO
from .models import (
    AdaptationLevel,
    AdaptationPlan,
    DriftKind,
    DriftReport,
    EditionProfile,
)
from .profile import EditionStore


class AdaptationController:
    def __init__(self, store: EditionStore | None = None) -> None:
        self.store = store or EditionStore()

    def plan(self, report: DriftReport) -> AdaptationPlan:
        errors = report.critical
        missing = [item for item in report.drifts if item.kind == DriftKind.MISSING_TABLE]
        profile_changed = [
            item for item in report.drifts if item.kind == DriftKind.PROFILE_CHANGED
        ]
        measure_lost = [
            item for item in report.drifts if item.kind == DriftKind.MEASURE_LOST
        ]
        header_changed = [
            item for item in report.drifts if item.kind == DriftKind.HEADER_CHANGED
        ]
        if not errors and not header_changed:
            return AdaptationPlan(
                level=AdaptationLevel.L0_NONE,
                reasons=["edition matches the stored profile"],
            )
        missing_ratio = len(missing) / max(1, report.expected_tables)
        if profile_changed or missing_ratio > MEASURE_MISS_RATIO:
            return AdaptationPlan(
                level=AdaptationLevel.L3_CODE_CANDIDATE,
                reasons=[
                    f"{len(missing)} missing table(s) ({missing_ratio:.0%}), "
                    f"{len(profile_changed)} profile change(s)"
                ],
                actions=[
                    "build a code candidate patch",
                    "verify the candidate in the sandbox",
                    "produce a record-level diff for human review",
                ],
                requires_sandbox=True,
                requires_human=True,
            )
        if measure_lost:
            return AdaptationPlan(
                level=AdaptationLevel.L2_RECIPE_CANDIDATE,
                reasons=[f"{len(measure_lost)} measure(s) lost in matched tables"],
                actions=[
                    "build a recipe candidate (bindings/aliases)",
                    "replay the edition in the sandbox",
                    "produce a record-level diff for human review",
                ],
                requires_sandbox=True,
                requires_human=True,
            )
        return AdaptationPlan(
            level=AdaptationLevel.L1_PROFILE_PATCH,
            reasons=[
                f"{len(header_changed)} header change(s) with all tables present",
            ],
            actions=["refresh the edition profile signatures"],
        )

    def apply_l1(
        self,
        profile: EditionProfile,
        report: DriftReport,
        ocr: dict,
    ) -> EditionProfile:
        """Refresh signatures after an L1 plan; recipe pins are preserved."""
        plan = self.plan(report)
        if plan.level != AdaptationLevel.L1_PROFILE_PATCH:
            raise ValueError("apply_l1 requires an L1 plan")
        refreshed = EditionStore.build(
            profile.standard_id,
            profile.edition,
            ocr,
            document_sha256=profile.document_sha256,
            page_count=profile.page_count or None,
            sample_doc_id=profile.sample_doc_id,
            recipe_pins=profile.recipe_pins,
        )
        refreshed.created_at = profile.created_at
        self.store.save(refreshed)
        return refreshed
