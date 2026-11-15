"""Shadow batch state machine.

Kept free of database imports so the promotion decision is unit-testable
without Postgres/asyncpg.

Plan B semantics:
- a verified candidate enters shadow only after a human approval;
- reaching the required document count stops at ``ready`` by default;
- only an explicit ``shadow_auto_promote`` setting promotes to stable;
- timeout moves the batch to ``expired`` and reopens the feedback.
"""

from __future__ import annotations

PENDING = "pending"
RUNNING = "running"
WAITING = "waiting"
READY = "ready"
PROMOTED = "promoted"
FAILED = "failed"
EXPIRED = "expired"
ABANDONED = "abandoned"

ACTIVE = {PENDING, RUNNING, WAITING, READY}
TERMINAL = {PROMOTED, FAILED, EXPIRED, ABANDONED}


def decide_batch_status(
    *,
    completed: int,
    failed: int,
    required: int,
    auto_promote: bool,
    expired: bool = False,
) -> str:
    if failed:
        return FAILED
    if expired:
        return EXPIRED
    if completed >= required:
        return PROMOTED if auto_promote else READY
    return WAITING
