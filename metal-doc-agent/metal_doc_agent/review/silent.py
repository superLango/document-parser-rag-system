"""Silent-error audit (M4.3-04).

A silent error is a value that looks valid but has no evidence, points at a
missing evidence row, contradicts its own quote, or is numeric without the unit
the audit requires. The audit runs offline over result artifacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..contracts import DocumentResult, Evidence, ExtractedValue

UNIT_REQUIRED = {"Rm", "Rp0.2", "KV2", "KU2", "HBW", "HRC", "HV", "持久时间", "持久应力"}
NUMERIC_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class SilentError:
    doc_id: str
    field_path: str
    code: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "field_path": self.field_path,
            "code": self.code,
            "detail": self.detail,
        }


@dataclass
class AuditResult:
    doc_id: str
    findings: list[SilentError] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings


def audit_document(
    result: DocumentResult, evidence: list[Evidence]
) -> AuditResult:
    index = {item.evidence_id: item for item in evidence}
    findings: list[SilentError] = []
    for record in result.records:
        for prop, value in record.properties.items():
            path = f"records.{record.record_id}.properties.{prop}"
            findings.extend(_check_value(result.document.doc_id, path, prop, value, index))
    return AuditResult(doc_id=result.document.doc_id, findings=findings)


def summarize_audits(audits: list[AuditResult]) -> dict:
    findings = [item for audit in audits for item in audit.findings]
    by_code: dict[str, int] = {}
    for item in findings:
        by_code[item.code] = by_code.get(item.code, 0) + 1
    return {
        "documents": len(audits),
        "documents_with_errors": sum(1 for audit in audits if audit.findings),
        "silent_errors": len(findings),
        "by_code": by_code,
        "passed": sum(1 for audit in audits if audit.passed),
        "findings": [item.to_dict() for item in findings[:200]],
    }


def _check_value(
    doc_id: str,
    path: str,
    prop: str,
    value: ExtractedValue,
    index: dict[str, Evidence],
) -> list[SilentError]:
    findings: list[SilentError] = []
    if not value.evidence_id:
        findings.append(SilentError(doc_id, path, "MISSING_EVIDENCE", "value has no evidence_id"))
    else:
        item = index.get(value.evidence_id)
        if item is None:
            findings.append(
                SilentError(doc_id, path, "EVIDENCE_UNRESOLVED", value.evidence_id)
            )
        else:
            if item.table_id and (item.row is None or item.col is None):
                findings.append(
                    SilentError(doc_id, path, "LOCATOR_MISSING", "table evidence without row/col")
                )
            if value.value is not None and not _quote_supports(value, item.quote):
                findings.append(
                    SilentError(
                        doc_id,
                        path,
                        "VALUE_QUOTE_MISMATCH",
                        f"value={value.value} quote={item.quote!r}",
                    )
                )
    if value.value is not None and prop in UNIT_REQUIRED and not value.unit:
        findings.append(SilentError(doc_id, path, "UNIT_MISSING", prop))
    return findings


def _quote_supports(value: ExtractedValue, quote: str) -> bool:
    haystack = f"{value.raw or ''} {quote or ''}"
    numbers = [float(token) for token in NUMERIC_RE.findall(haystack)]
    if not numbers:
        return False
    target = float(value.value)
    return any(abs(number - target) <= 1e-6 for number in numbers)
