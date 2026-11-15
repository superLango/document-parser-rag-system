"""Promote repeated verified cases into a hash-protected learned overlay.

The production concept dictionary and recipes stay read-only.  Only this
overlay is written, and it carries a sha256 over its content so consumers can
detect tampering or partial writes.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OVERLAY_VERSION = "1.0.0"
DEFAULT_MIN_HITS = 2


def _default_path() -> Path:
    return Path(
        os.getenv("HANSON_LEARNED_OVERLAY")
        or "services/orchestration/data/feedback/learned_overlay.json"
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(version: str, entries: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        _canonical({"version": version, "entries": entries}).encode("utf-8")
    ).hexdigest()


def build_overlay(
    cases: list[dict[str, Any]], *, min_hits: int = DEFAULT_MIN_HITS
) -> dict[str, Any]:
    """Group verified cases and keep groups that repeated at least ``min_hits``."""
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for case in cases:
        fingerprint = str(case.get("fingerprint") or "")
        patch = case.get("patch") or {}
        if not fingerprint or not patch:
            continue
        key = (
            fingerprint,
            str(case.get("rule_id") or ""),
            str(case.get("level") or ""),
            str(case.get("concept_id") or ""),
            _canonical(patch),
        )
        groups.setdefault(key, []).append(case)

    entries: list[dict[str, Any]] = []
    for (fingerprint, rule_id, level, concept_id, _), group in groups.items():
        if len(group) < min_hits:
            continue
        newest = max(group, key=lambda item: str(item.get("verified_at") or ""))
        entries.append(
            {
                "fingerprint": fingerprint,
                "rule_id": rule_id,
                "level": level,
                "concept_id": concept_id,
                "operator": str(newest.get("operator") or ""),
                "root_cause": str(newest.get("root_cause") or ""),
                "patch": newest.get("patch") or {},
                "hits": len(group),
                "feedback_ids": [
                    str(item.get("feedback_id") or "") for item in group
                ][:10],
                "first_verified": min(
                    str(item.get("verified_at") or "") for item in group
                ),
                "last_verified": str(newest.get("verified_at") or ""),
            }
        )
    entries.sort(key=lambda item: (item["fingerprint"], item["rule_id"], item["level"]))
    payload: dict[str, Any] = {
        "version": OVERLAY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "min_hits": min_hits,
        "entries": entries,
    }
    payload["sha256"] = _digest(OVERLAY_VERSION, entries)
    return payload


def save_overlay(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(_canonical(payload), encoding="utf-8")
    tmp.replace(target)
    return target


def load_overlay(path: str | Path) -> list[dict[str, Any]]:
    """Return entries only when the stored hash matches the content."""
    target = Path(path)
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    expected = _digest(str(payload.get("version") or ""), entries)
    if payload.get("sha256") != expected:
        return []
    return [item for item in entries if isinstance(item, dict)]


class OverlayStore:
    """Read-only access to promoted learned entries."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _default_path()

    def entries(self) -> list[dict[str, Any]]:
        return load_overlay(self.path)

    def find(
        self,
        fingerprint: str,
        *,
        rule_id: str = "",
        level: str = "",
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        matches = [
            item
            for item in self.entries()
            if str(item.get("fingerprint") or "") == fingerprint
            and (not rule_id or str(item.get("rule_id") or "") == rule_id)
            and (not level or str(item.get("level") or "") == level)
        ]
        return matches[:limit]
