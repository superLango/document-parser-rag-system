import unittest

from metal_doc_agent.contracts import (
    ClauseRecord,
    ExtractedValue,
    InspectionItem,
    ItemInventory,
    ItemInventoryEntry,
    Page,
    TableGrid,
)
from metal_doc_agent.items import attach_clause_methods, discover_items
from metal_doc_agent.items.discover import _merge
from metal_doc_agent.recipes import bind_columns
from tests.test_recipes import make_table, mechanical_table


def inspection_table() -> TableGrid:
    return TableGrid(
        table_id="T3",
        page_no=3,
        n_rows=3,
        n_cols=3,
        header_rows=1,
        rows=[
            ["检验项目", "取样数量", "试验方法"],
            ["化学成分", "每批1", "GB/T 223"],
            ["室温拉伸", "每批2", "GB/T 228.1"],
        ],
        header_paths=[["检验项目"], ["取样数量"], ["试验方法"]],
        profile="inspection",
        orientation="grade_rows",
    )


class ItemDiscoveryTests(unittest.TestCase):
    def test_inspection_table_items(self) -> None:
        table = inspection_table()
        bound = bind_columns(table)
        inventory = discover_items(
            [], [table], {"T3": bound}, doc_id="doc"
        )
        raws = {item.item_raw for item in inventory.items}
        self.assertEqual(raws, {"化学成分", "室温拉伸"})
        by_raw = {item.item_raw: item for item in inventory.items}
        self.assertEqual(by_raw["化学成分"].item_family, "chemical_composition")
        self.assertEqual(by_raw["室温拉伸"].item_family, "tensile")
        self.assertEqual(by_raw["室温拉伸"].facets.get("temperature"), "室温")
        self.assertEqual(by_raw["室温拉伸"].method_standard, "GB/T 228.1")
        self.assertEqual(by_raw["室温拉伸"].status, "confirmed")
        self.assertEqual(inventory.unknown_candidates, [])

    def test_merge_skips_cross_family_properties(self) -> None:
        merged = _merge(
            [
                ItemInventoryEntry(
                    item_raw="尺寸",
                    item_canonical="尺寸",
                    item_family="dimension",
                    source="inspection_table",
                ),
                ItemInventoryEntry(
                    item_raw="尺寸",
                    item_canonical="尺寸",
                    item_family="dimension",
                    properties=["A"],
                    source="property_table",
                ),
                ItemInventoryEntry(
                    item_raw="弯曲",
                    item_canonical="弯曲",
                    item_family="bend",
                    source="inspection_table",
                ),
                ItemInventoryEntry(
                    item_raw="弯曲",
                    item_canonical="弯曲",
                    item_family="bend",
                    properties=["厚度"],
                    source="property_table",
                ),
            ]
        )
        by_name = {entry.item_canonical: entry for entry in merged}
        self.assertEqual(by_name["尺寸"].properties, [])
        self.assertEqual(by_name["弯曲"].properties, [])

    def test_inspection_method_text_and_reference(self) -> None:
        table = TableGrid(
            table_id="T15",
            page_no=20,
            n_rows=4,
            n_cols=5,
            header_rows=1,
            rows=[
                ["序号", "检验项目", "取样数量", "取样部位及方法", "试验方法"],
                ["1", "化学成分", "1个/炉", "GB/T 20066", "见8.2"],
                ["6", "无损检验", "逐张", "-", "双方协商"],
                ["7", "尺寸、外形", "逐张", "-", "相应精度的量具"],
            ],
            header_paths=[
                ["序号"],
                ["检验项目"],
                ["取样数量"],
                ["取样部位及方法"],
                ["试验方法"],
            ],
            profile="inspection",
            orientation="grade_rows",
        )
        inventory = discover_items([], [table], None)
        by_raw = {item.item_raw: item for item in inventory.items}
        self.assertIsNone(by_raw["化学成分"].method_standard)
        self.assertEqual(by_raw["无损检验"].method_standard, "双方协商")
        self.assertEqual(by_raw["尺寸"].method_standard, "相应精度的量具")
        self.assertEqual(by_raw["尺寸"].facets.get("sampling_position"), "-")

    def test_attach_clause_methods(self) -> None:
        inventory = ItemInventory(
            doc_id="doc",
            items=[
                ItemInventoryEntry(
                    item_raw="超声波检测",
                    item_canonical="超声检测",
                    item_family="ndt",
                ),
                ItemInventoryEntry(item_raw="表面质量", item_family="surface"),
                ItemInventoryEntry(item_raw="化学成分", item_family="chemical_composition"),
            ],
        )
        inspections = [
            InspectionItem(item="超声波检测", method_clause="5.2.6.5"),
            InspectionItem(item="表面质量", method_clause="5.2.6.7"),
            InspectionItem(item="化学成分", method_clause="见8.2"),
        ]
        clauses = [
            ClauseRecord(
                clause_id="5.2.6.5",
                fields={
                    "method_standard": ExtractedValue(
                        raw="GB/T6519", text="GB/T6519", comparator="text"
                    )
                },
            ),
            ClauseRecord(
                clause_id="8.2",
                fields={
                    "method_standard": ExtractedValue(
                        raw="GB/T4336", text="GB/T4336", comparator="text"
                    )
                },
            ),
        ]
        updated = attach_clause_methods(inventory, inspections, clauses)
        self.assertEqual(updated, 2)
        self.assertEqual(inventory.items[0].method_standard, "GB/T6519")
        self.assertIsNone(inventory.items[1].method_standard)
        self.assertEqual(inventory.items[2].method_standard, "GB/T4336")

    def test_property_group_items(self) -> None:
        table = mechanical_table()
        bound = bind_columns(table)
        inventory = discover_items([], [table], {"T1": bound}, doc_id="doc")
        by_canonical = {item.item_canonical: item for item in inventory.items}
        self.assertIn("室温拉伸", by_canonical)
        self.assertIn("夏比冲击", by_canonical)
        self.assertIn("持久", by_canonical)
        tensile = by_canonical["室温拉伸"]
        self.assertIn("Rm", tensile.properties)
        self.assertIn("Rp0.2", tensile.properties)
        self.assertIn("A", tensile.properties)
        self.assertIn("KU2", by_canonical["夏比冲击"].properties)
        self.assertIn("持久时间", by_canonical["持久"].properties)
        self.assertGreater(inventory.coverage["measure_column_coverage"], 0.9)

    def test_clause_items_and_unknown(self) -> None:
        pages = [
            Page(
                page_no=4,
                markdown=(
                    "## 4.5 晶间腐蚀\n"
                    "应进行晶间腐蚀检验。\n"
                    "## 4.6 低倍组织\n"
                    "低倍组织按 GB/T 226 的规定进行检验。\n"
                    "应进行发货检验。\n"
                ),
            )
        ]
        inventory = discover_items(pages, [], doc_id="doc")
        raws = {item.item_raw for item in inventory.items}
        self.assertIn("晶间腐蚀", raws)
        self.assertIn("低倍组织", raws)
        low_item = next(item for item in inventory.items if item.item_raw == "低倍组织")
        self.assertEqual(low_item.item_family, "metallography")
        self.assertEqual(low_item.method_standard, "GB/T 226")
        self.assertTrue(any(item["raw"] == "发货" for item in inventory.unknown_candidates))

    def test_merge_table_and_clause(self) -> None:
        table = inspection_table()
        bound = bind_columns(table)
        pages = [Page(page_no=5, markdown="应进行室温拉伸试验。")]
        inventory = discover_items(
            pages, [table], {"T3": bound}, doc_id="doc"
        )
        tensile = [
            item for item in inventory.items if item.item_canonical == "室温拉伸"
        ]
        self.assertEqual(len(tensile), 1)
        self.assertEqual(tensile[0].status, "confirmed")
        self.assertGreaterEqual(len(tensile[0].evidence), 2)

    def test_not_applicable_for_classification(self) -> None:
        inventory = discover_items(
            [], [], doc_id="doc", document_profile="classification"
        )
        self.assertEqual(inventory.items, [])
        self.assertTrue(inventory.not_applicable)

    def test_inspection_table_cleans_footnote_and_units(self) -> None:
        table = TableGrid(
            table_id="T9",
            page_no=12,
            n_rows=4,
            n_cols=3,
            header_rows=1,
            rows=[
                ["检验项目", "取样数量", "试验方法"],
                ["晶粒度d", "2个/批", "GB/T 6394"],
                ["侧向膨胀值mm", "2个/批", "GB/T 229"],
                ["化学成分(质量分数)%", "2个/炉", "GB/T 223"],
            ],
            header_paths=[["检验项目"], ["取样数量"], ["试验方法"]],
            profile="inspection",
            orientation="grade_rows",
        )
        inventory = discover_items([], [table], doc_id="doc")
        raws = {item.item_raw for item in inventory.items}
        self.assertIn("晶粒度", raws)
        self.assertIn("侧向膨胀值", raws)
        self.assertIn("化学成分", raws)

    def test_inspection_table_skips_merged_footnote_rows(self) -> None:
        table = TableGrid(
            table_id="T9",
            page_no=12,
            n_rows=3,
            n_cols=3,
            header_rows=1,
            rows=[
                ["检验项目", "取样数量", "试验方法"],
                [
                    "对于碳、铝、钛和铌元素，应按子炉号从合金锭头部、尾部取样分析。",
                    "对于碳、铝、钛和铌元素，应按子炉号从合金锭头部、尾部取样分析。",
                    "对于碳、铝、钛和铌元素，应按子炉号从合金锭头部、尾部取样分析。",
                ],
                ["室温拉伸b", "2个/批", "GB/T 228.1"],
            ],
            header_paths=[["检验项目"], ["取样数量"], ["试验方法"]],
            profile="inspection",
            orientation="grade_rows",
        )
        inventory = discover_items([], [table], doc_id="doc")
        raws = {item.item_raw for item in inventory.items}
        self.assertEqual(raws, {"室温拉伸"})
        self.assertEqual(inventory.unknown_candidates, [])


    def test_generic_items_inherit_single_identity_facet(self) -> None:
        table = make_table(
            [
                ["牌号"],
                ["力学性能", "冲击", "KU2(J)"],
                ["力学性能", "硬度", "HRC"],
            ]
        )
        inspection = TableGrid(
            table_id="T9",
            page_no=9,
            n_rows=3,
            n_cols=1,
            header_rows=1,
            rows=[["检验项目"], ["室温冲击"], ["硬度"]],
            header_paths=[["检验项目"]],
            profile="inspection",
            orientation="grade_rows",
        )
        inventory = discover_items(
            [],
            [table, inspection],
            {"T1": bind_columns(table), "T9": bind_columns(inspection)},
            doc_id="doc",
        )
        canonicals = [item.item_canonical for item in inventory.items]
        self.assertEqual(canonicals.count("室温夏比冲击"), 1)
        self.assertEqual(canonicals.count("洛氏硬度"), 1)
        self.assertNotIn("冲击", canonicals)
        self.assertNotIn("硬度", canonicals)
        impact = next(item for item in inventory.items if item.item_family == "impact")
        self.assertEqual(impact.facets.get("temperature"), "室温")
        self.assertEqual(impact.facets.get("impact_type"), "夏比")

    def test_tensile_defaults_to_room_temperature(self) -> None:
        table = make_table(
            [
                ["牌号"],
                ["力学性能", "Rm(MPa)"],
                ["力学性能", "Rp0.2(MPa)"],
            ]
        )
        inventory = discover_items(
            [], [table], {"T1": bind_columns(table)}, doc_id="doc"
        )
        self.assertEqual(len(inventory.items), 1)
        self.assertEqual(inventory.items[0].item_canonical, "室温拉伸")
        self.assertEqual(
            inventory.items[0].facets.get("temperature_basis"), "default"
        )

    def test_unknown_profile_single_property_group_skipped(self) -> None:
        table = make_table([["级别"], ["A"]], profile="unknown")
        inventory = discover_items(
            [], [table], {"T1": bind_columns(table)}, doc_id="doc"
        )
        self.assertEqual(inventory.items, [])


if __name__ == "__main__":
    unittest.main()
