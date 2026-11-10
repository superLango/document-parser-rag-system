"""M2.5.3 shadow run: binding comparison, gates and gold agreement."""

from __future__ import annotations

import unittest

from metal_doc_agent.contracts import (
    ColumnBinding,
    ColumnBindingResult,
    Recipe,
    TableGrid,
)
from metal_doc_agent.recipes import GoldTable, evaluate_field_shadow, evaluate_shadow
from metal_doc_agent.recipes.signature import build_signature
from metal_doc_agent.recipes.shadow import _compare


def mechanical_table() -> TableGrid:
    headers = [["牌号"], ["状态"], ["Rm(MPa)"], ["A(%)"]]
    return TableGrid(
        table_id="T1",
        page_no=5,
        n_rows=2,
        n_cols=len(headers),
        header_rows=1,
        rows=[[""] * len(headers), [""] * len(headers)],
        header_paths=headers,
        profile="mechanical_properties",
        orientation="grade_rows",
    )


def mechanical_data_table() -> TableGrid:
    headers = [["牌号"], ["状态"], ["抗拉强度Rm(MPa)"], ["断后伸长率A(%)"]]
    rows = [
        ["牌号", "状态", "抗拉强度Rm(MPa)", "断后伸长率A(%)"],
        ["Q345", "正火", "≥470", "≥21"],
    ]
    return TableGrid(
        table_id="T1",
        page_no=5,
        n_rows=2,
        n_cols=len(headers),
        header_rows=1,
        rows=rows,
        header_paths=headers,
        profile="mechanical_properties",
        orientation="grade_rows",
    )


def chemical_element_table() -> TableGrid:
    headers = [["元素"], ["牌号A"], ["牌号B"]]
    rows = [
        ["元素", "牌号A", "牌号B"],
        ["C", "0.20", "0.25"],
        ["Si", "0.50", "0.60"],
        ["Mn", "1.20", "1.30"],
    ]
    return TableGrid(
        table_id="T2",
        page_no=6,
        n_rows=4,
        n_cols=3,
        header_rows=1,
        rows=rows,
        header_paths=headers,
        profile="chemical_composition",
        orientation="element_rows",
    )


def recipe(recipe_id: str, table: TableGrid, *, status: str = "candidate", overrides: dict | None = None) -> Recipe:
    return Recipe(
        recipe_id=recipe_id,
        status=status,
        profile=table.profile,
        signature=build_signature(table),
        bindings={"property_overrides": overrides} if overrides else {},
    )


class ShadowReportTests(unittest.TestCase):
    def test_identical_binding_passes(self) -> None:
        table = mechanical_table()
        baseline = recipe("active_base", table, status="active")
        candidate = recipe("cand_v2", table)
        report = evaluate_shadow(candidate, [table], recipes=[baseline])
        self.assertEqual(report.tables, 1)
        self.assertEqual(report.matched, 4)
        self.assertEqual(report.agreement, 1.0)
        self.assertEqual(report.coverage, 1.0)
        self.assertEqual(report.orphan_rate, 0.0)
        self.assertTrue(report.passed)
        self.assertEqual(
            set(report.evidence()),
            {"agreement", "coverage", "orphan_rate", "gold_agreement", "tables", "documents"},
        )

    def test_property_drift_fails_agreement(self) -> None:
        table = mechanical_table()
        baseline = recipe("active_base", table, status="active")
        candidate = recipe("cand_drift", table, overrides={"rm": "RmX"})
        report = evaluate_shadow(candidate, [table], recipes=[baseline])
        self.assertEqual(report.matched, 3)
        self.assertEqual(report.drifted, 1)
        self.assertEqual(report.agreement, 0.75)
        self.assertFalse(report.passed)
        self.assertTrue(any("agreement" in reason for reason in report.reasons))

    def test_profile_mismatch_is_not_ready(self) -> None:
        table = mechanical_table()
        other = recipe("cand_other", table)
        other = other.model_copy(update={"profile": "chemical_composition"})
        report = evaluate_shadow(other, [table])
        self.assertEqual(report.tables, 0)
        self.assertFalse(report.passed)
        self.assertTrue(any("no same-family" in reason for reason in report.reasons))

    def test_gold_agreement_blocks_wrong_property(self) -> None:
        table = mechanical_table()
        baseline = recipe("active_base", table, status="active")
        candidate = recipe("cand_gold", table)
        gold = [
            GoldTable(
                doc_id="doc_a",
                table_id="T1",
                table=table,
                columns={
                    "0": {"role": "row_key"},
                    "1": {"role": "condition"},
                    "2": {"role": "measure", "property": "Rm"},
                },
            )
        ]
        report = evaluate_shadow(candidate, [table], recipes=[baseline], gold_tables=gold)
        self.assertEqual(report.gold_tables, 1)
        self.assertEqual(report.gold_agreement, 1.0)
        self.assertTrue(report.passed)
        wrong = [
            GoldTable(
                doc_id="doc_a",
                table_id="T1",
                table=table,
                columns={
                    "0": {"role": "row_key"},
                    "1": {"role": "condition"},
                    "2": {"role": "measure", "property": "Rp0.2"},
                },
            )
        ]
        report = evaluate_shadow(candidate, [table], recipes=[baseline], gold_tables=wrong)
        self.assertEqual(report.gold_agreement, 0.75)
        self.assertFalse(report.passed)
        self.assertTrue(any("gold_agreement" in reason for reason in report.reasons))


class FieldShadowTests(unittest.TestCase):
    def test_same_layout_has_no_field_regression(self) -> None:
        table = mechanical_data_table()
        active = recipe("active_base", table, status="active")
        candidate = recipe("cand_v2", table)
        report = evaluate_field_shadow(candidate, [table], active_recipe=active)
        self.assertEqual(report.tables, 1)
        self.assertEqual(report.compared, 2)
        self.assertEqual(report.regressed, 0)
        self.assertEqual(report.core_regressions, 0)
        self.assertEqual(report.agreement, 1.0)
        self.assertTrue(report.passed)

    def test_layout_mismatch_is_core_regression(self) -> None:
        table = chemical_element_table()
        active = recipe("active_base", table, status="active")
        signature = build_signature(table).model_copy(update={"orientation": "grade_rows"})
        candidate = recipe("cand_bad", table).model_copy(update={"signature": signature})
        report = evaluate_field_shadow(candidate, [table], active_recipe=active)
        self.assertEqual(report.compared, 0)
        self.assertGreater(report.core_regressions, 0)
        self.assertFalse(report.passed)
        self.assertTrue(any("core_field_regressions" in reason for reason in report.reasons))

    def test_profile_mismatch_is_not_ready(self) -> None:
        table = mechanical_data_table()
        other = recipe("cand_other", table).model_copy(update={"profile": "chemical_composition"})
        report = evaluate_field_shadow(other, [table])
        self.assertEqual(report.tables, 0)
        self.assertFalse(report.passed)
        self.assertTrue(any("no same-family" in reason for reason in report.reasons))


class CompareTests(unittest.TestCase):
    def test_orphaned_columns_are_counted(self) -> None:
        def bound(column: int) -> ColumnBinding:
            return ColumnBinding(
                column=column,
                item_family="tensile",
                property="Rm",
                role="measure",
                status="bound",
            )

        baseline = ColumnBindingResult(
            table_id="T1", bindings=[bound(0), bound(1), bound(2)]
        )
        shadow = ColumnBindingResult(
            table_id="T1",
            bindings=[bound(0), bound(1), ColumnBinding(column=2, role="unknown")],
        )
        row = _compare(baseline, shadow)
        self.assertEqual(row["baseline_columns"], 3)
        self.assertEqual(row["shadow_columns"], 2)
        self.assertEqual(row["matched"], 2)
        self.assertEqual(row["orphaned"], 1)
        self.assertEqual(row["extra"], 0)


if __name__ == "__main__":
    unittest.main()
