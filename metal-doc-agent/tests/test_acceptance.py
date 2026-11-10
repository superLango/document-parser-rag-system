"""M1-S8 acceptance gate tests."""

from __future__ import annotations

import unittest

from metal_doc_agent.acceptance import (
    AcceptanceReport,
    Check,
    _p95,
    _profile_field_f1,
    render_acceptance,
)


class AcceptanceTests(unittest.TestCase):
    def test_p95_uses_nearest_rank(self) -> None:
        self.assertEqual(_p95([10, 20, 30, 40, 50]), 50)
        self.assertEqual(_p95([]), 0.0)

    def test_profile_field_f1_combines_chemical_and_mechanical(self) -> None:
        by_profile = {
            "chemical_composition": {
                "counts": {"field_tp": 8, "field_fp": 2, "field_fn": 2}
            },
            "mechanical_properties": {
                "counts": {"field_tp": 0, "field_fp": 0, "field_fn": 0}
            },
            "inspection": {"counts": {"field_tp": 0, "field_fp": 99, "field_fn": 99}},
        }
        self.assertEqual(
            _profile_field_f1(by_profile, ("chemical_composition", "mechanical_properties")),
            0.8,
        )

    def test_go_no_go_and_markdown(self) -> None:
        report = AcceptanceReport(
            generated_at="2026-10-26T00:00:00+00:00",
            runs_dir="runs/m1",
            goldset_version="v0",
            checks=[
                Check("schema", "Schema", 1.0, 1.0, True),
                Check("evidence", "Evidence", 0.9, 0.95, False),
            ],
        )
        self.assertEqual(report.go_no_go, "NO-GO")
        self.assertEqual([check.check_id for check in report.blockers], ["evidence"])
        markdown = render_acceptance(report)
        self.assertIn("NO-GO", markdown)
        self.assertIn("## 阻断项", markdown)
        self.assertIn("Evidence：实际 0.9", markdown)


if __name__ == "__main__":
    unittest.main()
