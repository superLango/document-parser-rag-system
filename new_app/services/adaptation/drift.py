"""Compare a fresh OCR result against a stored edition profile."""

from __future__ import annotations

from typing import Any

from .models import DriftItem, DriftKind, DriftReport, EditionProfile, TableSignature
from .profile import caption_key, signature_of

HEADER_MATCH_THRESHOLD = 0.6
MEASURE_MISS_RATIO = 0.2


class DriftAnalyzer:
    """Detect missing/changed tables between an edition profile and OCR output."""

    def compare(self, profile: EditionProfile, ocr: dict[str, Any]) -> DriftReport:
        current = [signature_of(table) for table in (ocr.get("tables") or [])]
        report = DriftReport(
            standard_id=profile.standard_id,
            edition=profile.edition,
            expected_tables=len(profile.tables),
        )
        unmatched = list(range(len(current)))
        matched = 0
        for expected in profile.tables:
            index = self._match(expected, current, unmatched)
            if index is None:
                report.drifts.append(
                    DriftItem(
                        kind=DriftKind.MISSING_TABLE,
                        table=self._label(expected),
                        detail="table expected by the edition profile was not found",
                        severity="error",
                    )
                )
                continue
            unmatched.remove(index)
            matched += 1
            report.drifts.extend(self._compare_table(expected, current[index]))
        for index in unmatched:
            table = current[index]
            if table.caption:
                report.drifts.append(
                    DriftItem(
                        kind=DriftKind.NEW_TABLE,
                        table=self._label(table),
                        detail="table not present in the edition profile",
                        severity="info",
                    )
                )
        report.matched_tables = matched
        report.score = round(matched / max(1, len(profile.tables)), 4)
        return report

    def _compare_table(
        self, expected: TableSignature, actual: TableSignature
    ) -> list[DriftItem]:
        drifts: list[DriftItem] = []
        label = self._label(expected)
        if expected.profile != actual.profile and expected.profile != "unknown":
            drifts.append(
                DriftItem(
                    kind=DriftKind.PROFILE_CHANGED,
                    table=label,
                    detail=f"profile {expected.profile} -> {actual.profile}",
                    severity="error",
                )
            )
        overlap = self._header_overlap(expected, actual)
        if overlap < HEADER_MATCH_THRESHOLD:
            drifts.append(
                DriftItem(
                    kind=DriftKind.HEADER_CHANGED,
                    table=label,
                    detail=f"header overlap {overlap:.2f}",
                    severity="warning",
                )
            )
        lost = [measure for measure in expected.measures if measure not in actual.measures]
        if lost:
            drifts.append(
                DriftItem(
                    kind=DriftKind.MEASURE_LOST,
                    table=label,
                    detail=", ".join(lost),
                    severity="error",
                )
            )
        return drifts

    def _header_overlap(
        self, expected: TableSignature, actual: TableSignature
    ) -> float:
        left = {header for header in expected.header_signature if header}
        right = {header for header in actual.header_signature if header}
        if not left or not right:
            return 1.0
        return len(left & right) / len(left | right)

    def _match(
        self,
        expected: TableSignature,
        current: list[TableSignature],
        unmatched: list[int],
    ) -> int | None:
        key = caption_key(expected.caption)
        if key:
            for index in unmatched:
                if caption_key(current[index].caption) == key:
                    return index
        best_index = None
        best_overlap = 0.0
        for index in unmatched:
            overlap = self._header_overlap(expected, current[index])
            if overlap > best_overlap:
                best_index, best_overlap = index, overlap
        if best_overlap >= HEADER_MATCH_THRESHOLD:
            return best_index
        return None

    @staticmethod
    def _label(table: TableSignature) -> str:
        return table.caption or ",".join(table.header_signature[:3])
