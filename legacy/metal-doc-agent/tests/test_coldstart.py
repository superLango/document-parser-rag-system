"""M2.5.4 cold-start: triage, clustering and dashboard metrics."""

from __future__ import annotations

import unittest

from metal_doc_agent.contracts import TableGrid
from metal_doc_agent.recipes import (
    build_report,
    cluster_long_tail,
    load_recipes,
    render_markdown,
    triage_table,
)


def make_table(
    header_paths: list[list[str]],
    *,
    table_id: str = "T1",
    profile: str = "unknown",
    orientation: str = "grade_rows",
) -> TableGrid:
    return TableGrid(
        table_id=table_id,
        page_no=5,
        n_rows=2,
        n_cols=len(header_paths),
        header_rows=1,
        rows=[[""] * len(header_paths), [""] * len(header_paths)],
        header_paths=header_paths,
        profile=profile,
        orientation=orientation,
    )


def mechanical_table(table_id: str = "T1") -> TableGrid:
    """Nine-column mechanical table; matches mechanical_properties_v1 closely."""
    return make_table(
        [
            ["牌号"],
            ["规格"],
            ["力学性能", "室温拉伸", "Rm(MPa)"],
            ["力学性能", "室温拉伸", "Rp0.2(MPa)"],
            ["力学性能", "室温拉伸", "A(%)"],
            ["力学性能", "冲击", "KU2(J)"],
            ["力学性能", "持久", "试验温度(℃)"],
            ["力学性能", "持久", "应力(MPa)"],
            ["力学性能", "持久", "时间(h)"],
        ],
        table_id=table_id,
        profile="mechanical_properties",
        orientation="grade_rows",
    )


def classification_table(table_id: str = "T1") -> TableGrid:
    # Classification now has an active recipe; use a truly unknown profile so
    # T3/novelty expectations stay meaningful.
    return make_table(
        [["类别"], ["说明"]], table_id=table_id, profile="unknown"
    )


class TriageTests(unittest.TestCase):
    def test_matching_table_is_t1(self) -> None:
        item = triage_table("doc_a", mechanical_table(), load_recipes())
        self.assertEqual(item.tier, "T1")
        self.assertEqual(item.queue, "production")
        self.assertEqual(item.recipe_id, "mechanical_properties_v1")

    def test_close_variant_is_t2(self) -> None:
        table = make_table(
            [["牌号"], ["Rm(MPa)"]], profile="mechanical_properties", orientation="property_rows"
        )
        item = triage_table("doc_a", table, load_recipes())
        self.assertNotEqual(item.queue, "production")
        self.assertEqual(item.tier, "T2")
        self.assertGreaterEqual(item.overlap, 0.4)

    def test_unknown_profile_is_t3(self) -> None:
        item = triage_table("doc_a", classification_table(), load_recipes())
        self.assertEqual(item.tier, "T3")
        self.assertEqual(item.queue, "explore")
        self.assertIsNone(item.recipe_id)


class ClusteringTests(unittest.TestCase):
    def test_similar_tables_share_one_cluster(self) -> None:
        items = [
            triage_table(doc, make_table([["项目"], ["要求"]], table_id="T1"), [])
            for doc in ("doc_a", "doc_b", "doc_c")
        ]
        clusters = cluster_long_tail(items)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].tables, 3)
        self.assertEqual(clusters[0].documents, 3)
        self.assertEqual(clusters[0].tier, "T3")
        self.assertEqual(clusters[0].representative_table, "T1")

    def test_different_profiles_never_merge(self) -> None:
        left = make_table([["项目"], ["要求"]], table_id="T1", profile="unknown")
        right = make_table([["项目"], ["要求"]], table_id="T2", profile="dimension")
        items = [triage_table("doc_a", left, []), triage_table("doc_b", right, [])]
        clusters = cluster_long_tail(items)
        self.assertEqual(len(clusters), 2)
        self.assertEqual({cluster.profile for cluster in clusters}, {"unknown", "dimension"})

    def test_cluster_tier_is_t2_when_any_member_is_t2(self) -> None:
        t2 = triage_table(
            "doc_a",
            make_table(
                [["牌号"], ["Rm(MPa)"]],
                profile="mechanical_properties",
                orientation="property_rows",
            ),
            load_recipes(),
        )
        t3 = triage_table(
            "doc_b",
            make_table(
                [["牌号"], ["Rm(MPa)"]],
                table_id="T2",
                profile="mechanical_properties",
                orientation="property_rows",
            ),
            [],
        )
        clusters = cluster_long_tail([t2, t3])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].tier, "T2")

    def test_t1_tables_are_not_clustered(self) -> None:
        item = triage_table("doc_a", mechanical_table(), load_recipes())
        self.assertEqual(item.tier, "T1")
        self.assertEqual(cluster_long_tail([item]), [])


class MetricsTests(unittest.TestCase):
    def test_report_metrics_and_gaps(self) -> None:
        report = build_report(
            [("doc_a", mechanical_table()), ("doc_b", classification_table())],
            load_recipes(),
            queue_stats={"production": 1, "explore": 1, "human": 0},
        )
        metrics = report["metrics"]
        self.assertEqual(metrics["tables"], 2)
        self.assertEqual(metrics["hit_rate"], 0.5)
        self.assertEqual(metrics["novelty_rate"], 0.5)
        self.assertEqual(metrics["t3_ratio"], 0.5)
        self.assertEqual(metrics["backlog"], {"production": 1, "explore": 1, "human": 0})
        self.assertEqual(metrics["clusters"], 1)
        self.assertTrue(any("novelty_rate" in gap for gap in metrics["gaps"]))
        self.assertTrue(any("t3_ratio" in gap for gap in metrics["gaps"]))
        self.assertTrue(any("hit_rate" in gap for gap in metrics["gaps"]))

    def test_markdown_has_dashboard_sections(self) -> None:
        report = build_report([("doc_a", mechanical_table())], load_recipes())
        markdown = render_markdown(report)
        self.assertIn("# 冷启动运营报告", markdown)
        self.assertIn("hit_rate", markdown)
        self.assertIn("长尾聚类", markdown)
        self.assertIn("表型分布", markdown)


if __name__ == "__main__":
    unittest.main()
