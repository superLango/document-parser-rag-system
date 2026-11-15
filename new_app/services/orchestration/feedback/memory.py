"""Verified repair case memory: header fingerprint -> proven patch."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .measures import canonical_measure, normalize
from .outline import table_headers

MAX_CASES = 500
_NOISE_RE = re.compile(r"[0-9./%（）()℃°c]+")


def header_fingerprint(table: dict[str, Any]) -> str:
    """Fingerprint the stable shape of a table (headers + measures + section)."""
    headers = table_headers(table)
    tokens: list[str] = []
    for header in headers:
        text = _NOISE_RE.sub("", normalize(header))
        if text:
            tokens.append(text)
    measures = sorted(
        {measure for header in headers if (measure := canonical_measure(header))}
    )
    section = str(table.get("section_kind") or "")
    payload = "|".join(sorted(set(tokens))) + "#" + ",".join(measures) + "#" + section
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _default_path() -> Path:
    # Mounted by compose (services/orchestration/data), so cases survive rebuilds.
    return Path(
        os.getenv("HANSON_FEEDBACK_CASES")
        or "services/orchestration/data/feedback/cases.json"
    )


class CaseStore:
    """Small JSON-backed store; only verified repairs are recorded."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _default_path()

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        cases = payload.get("cases") if isinstance(payload, dict) else payload
        return [item for item in cases or [] if isinstance(item, dict)]

    def remember(self, case: dict[str, Any]) -> dict[str, Any]:
        fingerprint = str(case.get("fingerprint") or "")
        if not fingerprint:
            raise ValueError("case.fingerprint is required")
        cases = self.load()
        identity = "|".join(
            [
                fingerprint,
                str(case.get("concept_id") or ""),
                str(case.get("operator") or ""),
                json.dumps(case.get("patch") or {}, ensure_ascii=False, sort_keys=True),
            ]
        )
        for existing in cases:
            if existing.get("_identity") == identity:
                return existing
        stored = {**case, "_identity": identity}
        cases.append(stored)
        cases = cases[-MAX_CASES:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"version": "1.0.0", "cases": cases}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        return stored

    def find(
        self,
        fingerprint: str,
        concept_id: str = "",
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        matches = [
            item
            for item in self.load()
            if item.get("fingerprint") == fingerprint
            and (not concept_id or item.get("concept_id") == concept_id)
        ]
        return matches[-limit:][::-1]


def select_reusable_case(
    cases: list[dict[str, Any]],
    *,
    rule_id: str,
    level: str = "",
) -> dict[str, Any] | None:
    """Pick the newest verified case that matches the rule (and level)."""
    for case in cases:
        if str(case.get("rule_id") or "") != rule_id:
            continue
        if level and str(case.get("level") or "") != level:
            continue
        if not case.get("patch"):
            continue
        return case
    return None


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier: dict[str, int] = {}
    concepts: dict[str, int] = {}
    for case in cases:
        tier = str(case.get("action_tier") or "unknown")
        by_tier[tier] = by_tier.get(tier, 0) + 1
        concept = str(case.get("concept_id") or "")
        if concept:
            concepts[concept] = concepts.get(concept, 0) + 1
    return {
        "total": len(cases),
        "by_tier": by_tier,
        "concepts": concepts,
        "fingerprints": len({case.get("fingerprint") for case in cases}),
    }
