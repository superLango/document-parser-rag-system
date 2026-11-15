"""Simulation markers for fake stages.

A run produced by any ``*_USE_FAKE`` stage must never be accepted as a
verified snapshot. Fake payloads carry ``simulated=true``; the snapshot
capture path rejects them.
"""

from __future__ import annotations

from typing import Any

SIMULATED = "simulated"
SIMULATED_RUN_NOT_ACCEPTABLE = "SIMULATED_RUN_NOT_ACCEPTABLE"


def is_simulated(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get(SIMULATED))


def reject_simulated(payload: Any, *, role: str = "artifact") -> None:
    if is_simulated(payload):
        raise ValueError(f"{SIMULATED_RUN_NOT_ACCEPTABLE}: {role} is simulated")
