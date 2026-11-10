"""Review metrics (M4.2-03/04): throughput, first-pass rate, correction mix."""

from __future__ import annotations

from .events import ReviewEvent
from .risk import FieldRisk, coverage_of_high_risk


def summarize_events(events: list[ReviewEvent]) -> dict:
    actions = {"accept": 0, "edit": 0, "reject": 0}
    reviewers: dict[str, int] = {}
    for event in events:
        actions[event.action] = actions.get(event.action, 0) + 1
        reviewers[event.reviewer] = reviewers.get(event.reviewer, 0) + 1
    changed = actions["edit"] + actions["reject"]
    return {
        "events": len(events),
        "actions": actions,
        "fields_reviewed": len({event.field_path for event in events}),
        "changed_fields": changed,
        "reviews_with_reason": sum(1 for event in events if event.reason.strip()),
        "reviewers": reviewers,
    }


def review_metrics(
    events: list[ReviewEvent],
    *,
    documents_confirmed: int,
    documents_with_changes: int,
    risks: list[FieldRisk] | None = None,
    minutes: float | None = None,
) -> dict:
    summary = summarize_events(events)
    first_pass = (
        round((documents_confirmed - documents_with_changes) / documents_confirmed, 4)
        if documents_confirmed
        else None
    )
    reviewed_paths = {event.field_path for event in events}
    high_risk = (
        coverage_of_high_risk(risks, reviewed_paths) if risks is not None else None
    )
    return {
        **summary,
        "documents_confirmed": documents_confirmed,
        "documents_with_changes": documents_with_changes,
        "first_pass_rate": first_pass,
        "high_risk": high_risk,
        "human_minutes": round(minutes, 2) if minutes is not None else None,
        "human_minutes_per_doc": (
            round(minutes / documents_confirmed, 2)
            if minutes is not None and documents_confirmed
            else None
        ),
    }
