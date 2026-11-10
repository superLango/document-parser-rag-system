"""Recipe lifecycle L0–L5 registry (M2.5.3-02/04/05).

The registry is the operational source of truth for promotion state; recipe
files keep their authored ``status`` (active/candidate/retired) so a promotion
never rewrites configuration. ``load_recipes`` applies the registry on load,
which makes promotion and rollback effective everywhere without touching files.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..contracts import Recipe

LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
LEVEL_LABELS = {
    "L0": "unknown",
    "L1": "explored",
    "L2": "candidate",
    "L3": "shadow",
    "L4": "active",
    "L5": "deprecated",
}
LEVEL_STATUS = {
    "L0": "retired",
    "L1": "retired",
    "L2": "candidate",
    "L3": "candidate",
    "L4": "active",
    "L5": "retired",
}
STATUS_LEVEL = {"active": "L4", "candidate": "L2", "retired": "L5"}

# Promotion paths; a demotion is expressed as a rollback, not a promote.
ALLOWED_TRANSITIONS = {
    "L0": {"L1", "L2"},
    "L1": {"L2"},
    "L2": {"L1", "L3", "L5"},
    "L3": {"L2", "L4", "L5"},
    "L4": {"L3", "L5"},
    "L5": {"L4"},
}
ROLLBACKABLE = {
    "L0": set(),
    "L1": {"L0"},
    "L2": {"L0", "L1"},
    "L3": {"L1", "L2"},
    "L4": {"L2", "L3"},
    "L5": {"L3", "L4"},
}

# Gate thresholds: L2 candidate, L3 shadow, L4 active (human sign-off).
GATE_L2 = {"gold_samples": 3, "header_mapping": 0.98}
GATE_L3 = {"agreement": 0.98, "coverage": 0.95, "orphan_rate": 0.01}
GATE_L4_KEYS = ("approved_by", "approval_note")

SCHEMA_VERSION = "0.1.0"


class LifecycleError(ValueError):
    """A transition violates the state machine or fails its gate."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gate_failures(level: str, evidence: dict | None) -> list[str]:
    """Return human-readable reasons why ``evidence`` does not satisfy the gate."""
    data = evidence or {}
    failures: list[str] = []
    if level == "L2":
        samples = data.get("gold_samples")
        if not isinstance(samples, int) or samples < GATE_L2["gold_samples"]:
            failures.append(f"gold_samples={samples!r} < {GATE_L2['gold_samples']}")
        mapping = data.get("header_mapping")
        if not isinstance(mapping, (int, float)) or mapping < GATE_L2["header_mapping"]:
            failures.append(
                f"header_mapping={mapping!r} < {GATE_L2['header_mapping']}"
            )
    elif level == "L3":
        for key in ("agreement", "coverage"):
            value = data.get(key)
            if not isinstance(value, (int, float)) or value < GATE_L3[key]:
                failures.append(f"{key}={value!r} < {GATE_L3[key]}")
        orphan = data.get("orphan_rate")
        if not isinstance(orphan, (int, float)) or orphan > GATE_L3["orphan_rate"]:
            failures.append(
                f"orphan_rate={orphan!r} > {GATE_L3['orphan_rate']}"
            )
    elif level == "L4":
        approved = data.get("approved_by")
        if isinstance(approved, str):
            approved = [approved] if approved.strip() else []
        if not approved:
            failures.append("approved_by is empty (human sign-off required)")
        note = data.get("approval_note")
        if not isinstance(note, str) or not note.strip():
            failures.append("approval_note is empty")
    return failures


class RecipeRegistry:
    """File-backed lifecycle registry.

    ``path`` points at ``configs/recipes/registry.json``; recipe files are read
    from the same directory (and its ``candidates/`` subdirectory) only to
    derive a level when no registry entry exists yet.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.root = self.path.parent
        data = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        self.schema_version = str(data.get("schema_version") or SCHEMA_VERSION)
        self.entries: dict[str, dict] = dict(data.get("recipes") or {})

    # -- read helpers -----------------------------------------------------
    def entry(self, recipe_id: str) -> dict | None:
        return self.entries.get(recipe_id)

    def level_of(self, recipe_id: str) -> str | None:
        entry = self.entries.get(recipe_id)
        if entry is not None:
            return str(entry.get("level"))
        return self.derived_level(recipe_id)

    def derived_level(self, recipe_id: str) -> str | None:
        recipe = self._read_recipe(recipe_id)
        if recipe is None:
            return None
        return STATUS_LEVEL.get(str(recipe.get("status")), "L0")

    def level_for(self, recipe: Recipe) -> str:
        return self.level_of(recipe.recipe_id) or STATUS_LEVEL.get(recipe.status, "L0")

    def apply(self, recipes: list[Recipe]) -> list[Recipe]:
        """Overlay registry levels onto recipe status used by routing."""
        output: list[Recipe] = []
        for recipe in recipes:
            level = self.level_of(recipe.recipe_id)
            if level is None:
                output.append(recipe)
                continue
            status = LEVEL_STATUS[level]
            output.append(recipe if status == recipe.status else recipe.model_copy(update={"status": status}))
        return output

    def levels(self, recipes: list[Recipe]) -> dict[str, str]:
        return {recipe.recipe_id: self.level_for(recipe) for recipe in recipes}

    def snapshot(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "updated_at": _now(),
            "recipes": self.entries,
        }

    def success_rates(self) -> dict[str, float]:
        """Recipe_id → historical success rate, the ``history`` input of routing."""
        rates: dict[str, float] = {}
        for recipe_id, entry in self.entries.items():
            stats = entry.get("stats") or {}
            runs = int(stats.get("runs") or 0)
            if runs <= 0:
                continue
            rates[recipe_id] = round(float(stats.get("successes") or 0) / runs, 4)
        return rates

    # -- transitions ------------------------------------------------------
    def promote(
        self,
        recipe_id: str,
        target: str,
        *,
        actor: str,
        note: str = "",
        evidence: dict | None = None,
        force: bool = False,
    ) -> dict:
        if target not in LEVELS:
            raise LifecycleError(f"unknown level: {target}")
        if not actor.strip():
            raise LifecycleError("actor is required")
        current = self.level_of(recipe_id) or "L0"
        if target == current:
            raise LifecycleError(f"{recipe_id} is already {target}")
        if not force and target not in ALLOWED_TRANSITIONS[current]:
            raise LifecycleError(
                f"illegal transition {current}->{target} for {recipe_id}"
            )
        failures = gate_failures(target, evidence)
        if failures and not force:
            raise LifecycleError(f"gate {target} failed: {'; '.join(failures)}")
        entry = self._ensure_entry(recipe_id, current)
        entry["level"] = target
        entry["updated_at"] = _now()
        entry["actor"] = actor
        entry["note"] = note
        entry["evidence"] = dict(evidence or {})
        entry.setdefault("history", []).append(
            {
                "kind": "promote",
                "from": current,
                "to": target,
                "actor": actor,
                "note": note,
                "evidence": dict(evidence or {}),
                "forced": bool(force),
                "at": entry["updated_at"],
            }
        )
        self.save()
        return entry

    def rollback(
        self,
        recipe_id: str,
        *,
        actor: str,
        to_level: str | None = None,
        note: str = "",
    ) -> dict:
        if not actor.strip():
            raise LifecycleError("actor is required")
        entry = self.entries.get(recipe_id)
        if entry is None:
            raise LifecycleError(f"no lifecycle history for {recipe_id}")
        current = str(entry.get("level"))
        target = to_level
        if target is None:
            history = entry.get("history") or []
            # Undo the last promotion that is still in effect: skip rollback
            # entries themselves, otherwise repeated rollbacks would toggle.
            target = None
            for item in reversed(history):
                if item.get("kind") != "promote":
                    continue
                candidate_level = str(item.get("from"))
                if candidate_level != current:
                    target = candidate_level
                    break
            if target is None and history:
                target = str(history[-1].get("from"))
        if not target or target not in LEVELS:
            raise LifecycleError(f"cannot infer rollback target for {recipe_id}")
        if target == current:
            raise LifecycleError(f"{recipe_id} is already {target}")
        seen = {item.get("from") for item in entry.get("history") or []}
        if target not in seen and target not in ROLLBACKABLE.get(current, set()):
            raise LifecycleError(
                f"rollback target {target} was never visited by {recipe_id}"
            )
        entry["level"] = target
        entry["updated_at"] = _now()
        entry["actor"] = actor
        entry["note"] = note
        entry.setdefault("history", []).append(
            {
                "kind": "rollback",
                "from": current,
                "to": target,
                "actor": actor,
                "note": note,
                "at": entry["updated_at"],
            }
        )
        self.save()
        return entry

    def deprecate(self, recipe_id: str, *, actor: str, note: str = "") -> dict:
        return self.promote(recipe_id, "L5", actor=actor, note=note)

    def record_run(self, recipe_id: str, *, success: bool, source: str = "shadow") -> None:
        entry = self._ensure_entry(recipe_id, self.level_of(recipe_id) or "L0")
        stats = entry.setdefault("stats", {"runs": 0, "successes": 0})
        stats["runs"] = int(stats.get("runs") or 0) + 1
        if success:
            stats["successes"] = int(stats.get("successes") or 0) + 1
        entry["updated_at"] = _now()
        entry.setdefault("last_run_source", source)
        self.save()

    # -- persistence ------------------------------------------------------
    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + "\n"
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)
        return self.path

    def _ensure_entry(self, recipe_id: str, level: str) -> dict:
        entry = self.entries.get(recipe_id)
        if entry is None:
            entry = {
                "recipe_id": recipe_id,
                "level": level,
                "version": 1,
                "created_at": _now(),
                "history": [],
                "stats": {"runs": 0, "successes": 0},
            }
            self.entries[recipe_id] = entry
        return entry

    def _read_recipe(self, recipe_id: str) -> dict | None:
        for base in (self.root, self.root / "candidates"):
            path = base / f"{recipe_id}.json"
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    return None
        return None
