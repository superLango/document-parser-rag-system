import unittest

from metal_doc_agent.contracts import TableGrid
from metal_doc_agent.recipes import (
    bind_columns,
    build_signature,
    load_recipes,
    match_recipe,
    token_similarity,
)


def make_table(
    header_paths: list[list[str]],
    *,
    profile: str = "mechanical_properties",
    orientation: str = "grade_rows",
    units: list[str] | None = None,
    blocks: int = 0,
) -> TableGrid:
    n_cols = len(header_paths)
    return TableGrid(
        table_id="T1",
        page_no=1,
        n_rows=2,
        n_cols=n_cols,
        header_rows=1,
        rows=[[""] * n_cols, [""] * n_cols],
        header_paths=header_paths,
        profile=profile,
        orientation=orientation,
        units=units or [],
        blocks=[] if blocks == 0 else [{"block_id": f"B{i}"} for i in range(blocks)],
    )


def mechanical_table() -> TableGrid:
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
        ]
    )


class SignatureTests(unittest.TestCase):
    def test_tokens_strip_units_and_footnotes(self) -> None:
        tokens = build_signature(mechanical_table()).tokens
        self.assertIn("rm", tokens)
        self.assertIn("rp0.2", tokens)
        self.assertIn("ku2", tokens)
        self.assertIn("时间", tokens)
        self.assertNotIn("rm(mpa)", tokens)

    def test_token_similarity(self) -> None:
        self.assertEqual(token_similarity(["a", "b"], ["a", "b"]), 1.0)
        self.assertEqual(token_similarity(["a"], ["b"]), 0.0)
        self.assertAlmostEqual(token_similarity(["a", "b"], ["b", "c"]), 1 / 3)


class RouterTests(unittest.TestCase):
    def test_exact_recipe_match(self) -> None:
        match = match_recipe(mechanical_table(), load_recipes())
        self.assertEqual(match.status, "exact")
        self.assertIsNotNone(match.recipe)
        self.assertEqual(match.recipe.recipe_id, "mechanical_properties_v1")

    def test_unknown_profile_does_not_match(self) -> None:
        table = make_table([["性能"], ["特殊项"]], profile="unknown")
        match = match_recipe(table, load_recipes())
        self.assertEqual(match.status, "unknown")
        self.assertIsNone(match.recipe)

    def test_load_recipes(self) -> None:
        recipes = load_recipes()
        ids = {recipe.recipe_id for recipe in recipes}
        self.assertIn("mechanical_properties_v1", ids)
        self.assertIn("chemical_composition_v1", ids)
        self.assertIn("inspection_rules_v1", ids)
        self.assertIn("dimension_v1", ids)
        self.assertIn("hardness_v1", ids)
        self.assertIn("chemical_element_rows_v1", ids)


class ColumnBindingTests(unittest.TestCase):
    def test_mechanical_columns(self) -> None:
        recipe = next(
            item
            for item in load_recipes()
            if item.recipe_id == "mechanical_properties_v1"
        )
        result = bind_columns(mechanical_table(), recipe, match_status="exact")
        self.assertEqual(result.match_status, "exact")
        bindings = {item.column: item for item in result.bindings}
        self.assertEqual(bindings[0].role, "row_key")
        self.assertEqual(bindings[1].role, "condition")
        self.assertEqual(bindings[2].item_family, "tensile")
        self.assertEqual(bindings[2].property, "Rm")
        self.assertEqual(bindings[2].role, "measure")
        self.assertEqual(bindings[2].unit, "MPa")
        self.assertEqual(bindings[2].facets.get("temperature"), "室温")
        self.assertEqual(bindings[5].item_family, "impact")
        self.assertEqual(bindings[5].property, "KU2")
        self.assertEqual(bindings[5].facets.get("impact_type"), "夏比")
        self.assertEqual(bindings[6].role, "condition")
        self.assertEqual(bindings[8].property, "持久时间")
        self.assertEqual(bindings[8].role, "measure")
        self.assertIn("试验温度", bindings[8].facets.get("conditions", ""))
        families = {group.item_family for group in result.item_groups}
        self.assertEqual(families, {"tensile", "impact", "stress_rupture"})
        self.assertEqual(result.conflicts, [])
        self.assertEqual(result.ambiguous, [])

    def test_chemical_columns(self) -> None:
        table = make_table(
            [
                ["牌号"],
                ["化学成分", "C"],
                ["化学成分", "Si"],
                ["化学成分", "Mn"],
            ],
            profile="chemical_composition",
            units=["%"],
        )
        result = bind_columns(table)
        bindings = {item.column: item for item in result.bindings}
        self.assertEqual(bindings[1].item_family, "chemical_composition")
        self.assertEqual(bindings[1].property, "C")
        self.assertEqual(bindings[1].unit, "%")
        self.assertEqual(bindings[3].property, "Mn")
        self.assertEqual(result.item_groups[0].columns, [1, 2, 3])

    def test_hardness_scales(self) -> None:
        table = make_table(
            [["硬度", "HRC"], ["硬度", "HV"], ["硬度", "HBW"]]
        )
        result = bind_columns(table)
        bindings = {item.column: item for item in result.bindings}
        self.assertEqual(bindings[0].item_family, "hardness")
        self.assertEqual(bindings[0].facets.get("hardness_scale"), "rockwell")
        self.assertEqual(bindings[1].facets.get("hardness_scale"), "vickers")
        self.assertEqual(bindings[2].facets.get("hardness_scale"), "brinell")

    def test_group_property_conflict(self) -> None:
        table = make_table([["拉伸", "KU2(J)"]])
        result = bind_columns(table)
        binding = result.bindings[0]
        self.assertEqual(binding.status, "conflict")
        self.assertIn("冲突", binding.reason)
        self.assertEqual(result.conflicts[0]["column"], 0)

    def test_ambiguous_column(self) -> None:
        table = make_table([["性能", "σ"]])
        result = bind_columns(table)
        self.assertEqual(result.bindings[0].status, "ambiguous")
        self.assertEqual(result.ambiguous[0]["column"], 0)

    def test_empty_header_is_unmapped(self) -> None:
        table = make_table([[""]])
        result = bind_columns(table)
        self.assertEqual(result.bindings[0].status, "unmapped")
        self.assertEqual(result.unmapped_columns, [0])

    def test_cev_columns_are_measures(self) -> None:
        table = make_table(
            [
                ["牌号", "钢级"],
                ["牌号", "质量等级"],
                ["碳当量CEV(质量分数)/%不大于", "公称厚度或直径/mm", "≤30"],
            ],
            profile="dimension",
        )
        result = bind_columns(table)
        binding = result.bindings[2]
        self.assertEqual(binding.role, "measure")
        self.assertEqual(binding.property, "CEV")
        self.assertEqual(binding.item_family, "chemical_composition")

    def test_sampling_position_and_method_roles(self) -> None:
        table = make_table(
            [
                ["序号"],
                ["检验项目"],
                ["取样数量"],
                ["取样部位及方法"],
                ["试验方法"],
            ],
            profile="inspection",
        )
        result = bind_columns(table)
        roles = {binding.header_path[-1]: binding.role for binding in result.bindings}
        self.assertEqual(roles["取样部位及方法"], "condition")
        self.assertEqual(roles["试验方法"], "method")

    def test_process_parameter_table_is_not_bound(self) -> None:
        table = make_table(
            [
                ["序号"],
                ["工艺参数偏差/%"],
                ["轧制锻件1(首件)"],
                ["备注"],
            ],
            profile="dimension",
        )
        table = table.model_copy(update={"caption": "表5 工艺参数偏差记录"})
        result = bind_columns(table, match_recipe(table, load_recipes()).recipe)
        self.assertEqual([item for item in result.bindings if item.role == "measure"], [])
        self.assertEqual(result.item_groups, [])
        self.assertTrue(all(item.status == "unmapped" for item in result.bindings))


if __name__ == "__main__":
    unittest.main()
