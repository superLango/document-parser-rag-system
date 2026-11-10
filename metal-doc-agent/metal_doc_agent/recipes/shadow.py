"""Binding-level shadow run for candidate recipes (M2.5.3-03).

A candidate is never promoted on structure alone: it is replayed over the
same-family tables of a baseline corpus and compared against the binding the
active recipe (or the rule engine when no recipe applies) would produce. The
three gating metrics mirror the plan: agreement ≥98%, coverage ≥95%,
orphan rate <1%. Optional gold tables add a human-truth agreement check.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..contracts import ColumnBinding, ColumnBindingResult, Recipe, TableGrid
from ..tablegrid.normalize import ELEMENTS
from .binding import AliasConfig, bind_columns
from .router import match_recipe

DEFAULT_THRESHOLDS = {
    "agreement": 0.98,
    "coverage": 0.95,
    "orphan_rate": 0.01,
    "gold_agreement": 0.98,
}


@dataclass(frozen=True)
class GoldTable:
    doc_id: str
    table_id: str
    table: TableGrid
    columns: dict[str, dict]


@dataclass(frozen=True)
class ShadowReport:
    recipe_id: str
    profile: str
    documents: int
    tables: int
    columns: int
    baseline_columns: int
    shadow_columns: int
    matched: int
    drifted: int
    orphaned: int
    extra: int
    coverage: float
    agreement: float
    orphan_rate: float
    gold_tables: int
    gold_agreement: float | None
    passed: bool
    reasons: list[str]
    thresholds: dict = field(default_factory=dict)
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def evidence(self) -> dict:
        """Compact dict accepted by ``RecipeRegistry.promote(..., level='L3')``."""
        return {
            "agreement": self.agreement,
            "coverage": self.coverage,
            "orphan_rate": self.orphan_rate,
            "gold_agreement": self.gold_agreement,
            "tables": self.tables,
            "documents": self.documents,
        }


def evaluate_shadow(
    recipe: Recipe,
    tables: list[TableGrid],
    *,
    recipes: list[Recipe] | None = None,
    aliases: AliasConfig | None = None,
    gold_tables: list[GoldTable] | None = None,
    documents: int = 0,
    thresholds: dict | None = None,
) -> ShadowReport:
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    counters = {
        "columns": 0,
        "baseline_columns": 0,
        "shadow_columns": 0,
        "matched": 0,
        "drifted": 0,
        "orphaned": 0,
        "extra": 0,
        "unit_drift": 0,
    }
    details: list[dict] = []
    unit_drift = 0
    for table in tables:
        if table.profile != recipe.profile:
            continue
        baseline_recipe = None
        if recipes is not None:
            baseline_recipe = match_recipe(
                table, [item for item in recipes if item.recipe_id != recipe.recipe_id]
            ).recipe
        baseline = bind_columns(table, recipe=baseline_recipe, aliases=aliases, match_status="baseline")
        shadow = bind_columns(table, recipe=recipe, aliases=aliases, match_status="candidate")
        row = _compare(baseline, shadow)
        for key in ("columns", "baseline_columns", "shadow_columns", "matched", "drifted", "orphaned", "extra"):
            counters[key] += row[key]
        unit_drift += row["unit_drift"]
        details.append({"table_id": table.table_id, "page_no": table.page_no, **row})

    gold_tables_count = 0
    gold_correct = 0
    gold_total = 0
    if gold_tables:
        for item in gold_tables:
            if item.table.profile != recipe.profile:
                continue
            gold_tables_count += 1
            result = bind_columns(
                item.table, recipe=recipe, aliases=aliases, match_status="candidate"
            )
            correct, total = _gold_score(result, item.columns)
            gold_correct += correct
            gold_total += total

    gold_agreement = (
        round(gold_correct / gold_total, 4) if gold_total else None
    )
    baseline_columns = counters["baseline_columns"]
    coverage = (
        round((counters["matched"] + counters["drifted"]) / baseline_columns, 4)
        if baseline_columns
        else 1.0
    )
    compared = counters["matched"] + counters["drifted"]
    agreement = round(counters["matched"] / compared, 4) if compared else 1.0
    orphan_rate = (
        round(counters["orphaned"] / baseline_columns, 4) if baseline_columns else 0.0
    )

    reasons: list[str] = [
        f"tables={len(details)}",
        f"agreement={agreement:.4f}",
        f"coverage={coverage:.4f}",
        f"orphan_rate={orphan_rate:.4f}",
    ]
    failures: list[str] = []
    if not details:
        failures.append(f"no same-family tables for profile {recipe.profile}")
    if agreement < limits["agreement"]:
        failures.append(f"agreement {agreement:.4f} < {limits['agreement']}")
    if coverage < limits["coverage"]:
        failures.append(f"coverage {coverage:.4f} < {limits['coverage']}")
    if orphan_rate > limits["orphan_rate"]:
        failures.append(f"orphan_rate {orphan_rate:.4f} > {limits['orphan_rate']}")
    if gold_agreement is not None and gold_agreement < limits["gold_agreement"]:
        failures.append(
            f"gold_agreement {gold_agreement:.4f} < {limits['gold_agreement']}"
        )
    if gold_tables_count == 0:
        reasons.append("gold_skipped:no_gold_tables")
    if unit_drift:
        reasons.append(f"unit_drift={unit_drift}")
    reasons.extend(failures)

    return ShadowReport(
        recipe_id=recipe.recipe_id,
        profile=recipe.profile,
        documents=documents,
        tables=len(details),
        columns=counters["columns"],
        baseline_columns=baseline_columns,
        shadow_columns=counters["shadow_columns"],
        matched=counters["matched"],
        drifted=counters["drifted"],
        orphaned=counters["orphaned"],
        extra=counters["extra"],
        coverage=coverage,
        agreement=agreement,
        orphan_rate=orphan_rate,
        gold_tables=gold_tables_count,
        gold_agreement=gold_agreement,
        passed=not failures,
        reasons=reasons,
        thresholds=dict(limits),
        details=details,
    )


def _effective(binding: ColumnBinding) -> bool:
    return binding.status == "bound"


def _same(left: ColumnBinding, right: ColumnBinding) -> bool:
    if left.role != right.role:
        return False
    if left.role == "measure" and left.property != right.property:
        return False
    return True


def _compare(baseline: ColumnBindingResult, shadow: ColumnBindingResult) -> dict:
    columns = max(len(baseline.bindings), len(shadow.bindings))
    row = {
        "columns": columns,
        "baseline_columns": 0,
        "shadow_columns": 0,
        "matched": 0,
        "drifted": 0,
        "orphaned": 0,
        "extra": 0,
        "unit_drift": 0,
    }
    for index in range(columns):
        left = baseline.bindings[index] if index < len(baseline.bindings) else None
        right = shadow.bindings[index] if index < len(shadow.bindings) else None
        left_on = left is not None and _effective(left)
        right_on = right is not None and _effective(right)
        if left_on:
            row["baseline_columns"] += 1
        if right_on:
            row["shadow_columns"] += 1
        if left_on and right_on:
            if _same(left, right):
                row["matched"] += 1
                if left.unit and right.unit and left.unit != right.unit:
                    row["unit_drift"] += 1
            else:
                row["drifted"] += 1
        elif left_on:
            row["orphaned"] += 1
        elif right_on:
            row["extra"] += 1
    return row


def _gold_score(result: ColumnBindingResult, columns: dict[str, dict]) -> tuple[int, int]:
    correct = 0
    total = 0
    for column_str, expected in columns.items():
        column = int(column_str)
        if column >= len(result.bindings):
            continue
        pred = result.bindings[column]
        total += 1
        if _gold_role_ok(pred, expected):
            correct += 1
        if expected.get("role") == "measure" and expected.get("property"):
            total += 1
            if pred.property == expected["property"]:
                correct += 1
    return correct, total


def _gold_role_ok(pred: ColumnBinding, expected: dict) -> bool:
    status = expected.get("status")
    if status == "ambiguous":
        return pred.status == "ambiguous"
    if status == "unmapped":
        return pred.status == "unmapped"
    return pred.role == expected.get("role")


CORE_FIELDS = {
    "mechanical_properties": {
        "Rm", "Rp0.2", "A", "Z", "KV2", "KU2", "HB", "HBW", "HRC", "HV",
    },
    "chemical_composition": set(ELEMENTS),
}


@dataclass(frozen=True)
class FieldShadowReport:
    """Extraction-level shadow: same-family tables, field by field."""

    recipe_id: str
    profile: str
    tables: int
    compared: int
    matched: int
    regressed: int
    added: int
    core_regressions: int
    agreement: float
    passed: bool
    reasons: list[str] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_field_shadow(
    recipe: Recipe,
    tables: list[TableGrid],
    *,
    active_recipe: Recipe | None = None,
    threshold: float = 0.98,
) -> FieldShadowReport:
    """Replay extraction with the candidate's declared layout.

    Binding-level shadow proves the column mapping is stable; this replay proves
    the *extracted fields* do not regress. Each same-profile table is extracted
    twice: once with the active recipe's layout (baseline) and once with the
    candidate's ``profile``/``orientation`` (shadow). Compared fields are
    ``(record_id, property)`` with comparator, bounds and unit; a changed or
    missing core field (Rm/Rp0.2/A/Z/KV2/hardness) fails the candidate.
    """
    from ..extraction.mock import MockExtractor

    extractor = MockExtractor()
    core = CORE_FIELDS.get(recipe.profile, set())
    compared = matched = regressed = added = core_regressions = 0
    details: list[dict] = []

    for table in tables:
        if table.profile != recipe.profile:
            continue
        baseline_table = _layout(table, active_recipe)
        shadow_table = _layout(table, recipe)
        baseline = _extract_fields(extractor, baseline_table)
        shadow = _extract_fields(extractor, shadow_table)
        table_regressed = 0
        for key, baseline_value in baseline.items():
            if key not in shadow:
                regressed += 1
                table_regressed += 1
                if key[1] in core:
                    core_regressions += 1
                continue
            compared += 1
            if _field_signature(baseline_value) == _field_signature(shadow[key]):
                matched += 1
            else:
                regressed += 1
                table_regressed += 1
                if key[1] in core:
                    core_regressions += 1
        added += sum(1 for key in shadow if key not in baseline)
        details.append(
            {
                "table_id": table.table_id,
                "page_no": table.page_no,
                "fields": len(baseline),
                "regressed": table_regressed,
            }
        )

    agreement = round(matched / compared, 4) if compared else 1.0
    reasons = [
        f"tables={len(details)}",
        f"compared={compared}",
        f"agreement={agreement:.4f}",
        f"regressed={regressed}",
        f"core_regressions={core_regressions}",
    ]
    passed = bool(details) and agreement >= threshold and core_regressions == 0
    if not details:
        reasons.append(f"no same-family tables for profile {recipe.profile}")
    if agreement < threshold:
        reasons.append(f"field_agreement {agreement:.4f} < {threshold}")
    if core_regressions:
        reasons.append(f"core_field_regressions={core_regressions}")
    return FieldShadowReport(
        recipe_id=recipe.recipe_id,
        profile=recipe.profile,
        tables=len(details),
        compared=compared,
        matched=matched,
        regressed=regressed,
        added=added,
        core_regressions=core_regressions,
        agreement=agreement,
        passed=passed,
        reasons=reasons,
        details=details,
    )


def _layout(table: TableGrid, recipe: Recipe | None) -> TableGrid:
    if recipe is None:
        return table
    return table.model_copy(
        update={
            "profile": recipe.signature.profile or table.profile,
            "orientation": recipe.signature.orientation or table.orientation,
        }
    )


def _extract_fields(extractor, table: TableGrid) -> dict[tuple[str, str], object]:
    from ..contracts import DocumentMeta

    output = extractor.extract(
        table,
        DocumentMeta(doc_id=table.table_id, source_path="", file_name=""),
    )
    fields: dict[tuple[str, str], object] = {}
    for record in output.records:
        for prop, value in record.properties.items():
            fields[(record.record_id, prop)] = value
    return fields


def _field_signature(value) -> tuple:
    return (
        value.comparator,
        value.value,
        value.lower,
        value.upper,
        value.unit,
        value.text,
    )
