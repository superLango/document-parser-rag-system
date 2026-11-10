"""M4 review: field events, feedback, risk, silent-error audit and metrics."""

from .events import (
    FeedbackStore,
    ReviewEvent,
    apply_events,
    diff_records,
    events_from_payloads,
    field_path_for,
    latest_events,
    parse_field_path,
)
from .risk import (
    FieldRisk,
    coverage_of_high_risk,
    document_risk_level,
    field_risks,
    risk_summary,
)
from .silent import AuditResult, SilentError, audit_document, summarize_audits
from .summary import review_metrics, summarize_events

__all__ = [
    "AuditResult",
    "FeedbackStore",
    "FieldRisk",
    "ReviewEvent",
    "SilentError",
    "apply_events",
    "audit_document",
    "coverage_of_high_risk",
    "diff_records",
    "document_risk_level",
    "events_from_payloads",
    "field_path_for",
    "field_risks",
    "latest_events",
    "parse_field_path",
    "review_metrics",
    "risk_summary",
    "summarize_audits",
    "summarize_events",
]
