import unittest

from metal_doc_agent.contracts import (
    ColumnBinding,
    ColumnBindingResult,
    DocumentMeta,
    ExtractedValue,
    Record,
    TableGrid,
)
from metal_doc_agent.extraction.base import ExtractionOutput
from metal_doc_agent.extraction.matrix import extract_bound_matrix, merge_matrix_output


def doc() -> DocumentMeta:
    return DocumentMeta(doc_id="doc", source_path="x.md", file_name="x.md")


def impact_table() -> TableGrid:
    return TableGrid(
        table_id="T13",
        page_no=1,
        n_rows=5,
        n_cols=4,
        header_rows=3,
        rows=[
            ["牌号", "牌号", "KV2", "KV2"],
            ["钢级", "质量等级", "20℃", "20℃"],
            ["钢级", "质量等级", "纵向", "横向"],
            ["Q355、Q390", "B", "34", "27"],
            ["Q355", "C", "-", "30a"],
        ],
        header_paths=[
            ["牌号", "钢级"],
            ["牌号", "质量等级"],
            ["以下试验温度的冲击吸收能量最小值 KV2/J", "20℃", "纵向"],
            ["以下试验温度的冲击吸收能量最小值 KV2/J", "20℃", "横向"],
        ],
        profile="mechanical_properties",
    )


def impact_binding() -> ColumnBindingResult:
    return ColumnBindingResult(
        table_id="T13",
        bindings=[
            ColumnBinding(column=0, header_path=["牌号", "钢级"], role="row_key"),
            ColumnBinding(
                column=1, header_path=["牌号", "质量等级"], role="row_key"
            ),
            ColumnBinding(
                column=2,
                header_path=["冲击", "20℃", "纵向"],
                property="KV2",
                role="measure",
                unit="J",
            ),
            ColumnBinding(
                column=3,
                header_path=["冲击", "20℃", "横向"],
                property="KV2",
                role="measure",
                unit="J",
            ),
        ],
    )


class MatrixExtractionTests(unittest.TestCase):
    def test_impact_temperature_and_direction(self) -> None:
        output = extract_bound_matrix(impact_table(), impact_binding(), doc())
        self.assertIsNotNone(output)
        assert output is not None
        self.assertEqual(len(output.records), 5)
        first = output.records[0]
        self.assertEqual(first.grade, "Q355B")
        self.assertEqual(first.condition, "20℃/纵向")
        value = first.properties["KV2"]
        self.assertEqual(value.raw, "34")
        self.assertEqual(value.unit, "J")
        self.assertEqual(value.comparator, "min")
        self.assertEqual(output.records[1].grade, "Q390B")
        last = output.records[-1]
        self.assertEqual(last.grade, "Q355C")
        self.assertEqual(last.condition, "20℃/横向")
        self.assertEqual(last.properties["KV2"].raw, "30")
        self.assertEqual(len(output.evidence), 5)

    def test_cev_thickness_condition(self) -> None:
        table = TableGrid(
            table_id="T3",
            page_no=1,
            n_rows=4,
            n_cols=4,
            header_rows=2,
            rows=[
                ["牌号", "牌号", "碳当量", "碳当量"],
                ["钢级", "质量等级", "≤30", ">30~63"],
                ["Q355", "B", "0.36", "0.39"],
                ["Q390", "C", "0.40", "0.43"],
            ],
            header_paths=[
                ["牌号", "钢级"],
                ["牌号", "质量等级"],
                ["碳当量CEV(质量分数)/%不大于", "≤30"],
                ["碳当量CEV(质量分数)/%不大于", ">30~63"],
            ],
            profile="chemical_composition",
        )
        binding = ColumnBindingResult(
            table_id="T3",
            bindings=[
                ColumnBinding(column=0, header_path=["牌号", "钢级"], role="row_key"),
                ColumnBinding(
                    column=1, header_path=["牌号", "质量等级"], role="row_key"
                ),
                ColumnBinding(
                    column=2,
                    header_path=["碳当量", "≤30"],
                    property="CEV",
                    role="measure",
                    unit="%",
                ),
                ColumnBinding(
                    column=3,
                    header_path=["碳当量", ">30~63"],
                    property="CEV",
                    role="measure",
                    unit="%",
                ),
            ],
        )
        output = extract_bound_matrix(table, binding, doc())
        assert output is not None
        self.assertEqual(len(output.records), 4)
        self.assertEqual(output.records[0].grade, "Q355B")
        self.assertEqual(output.records[0].condition, "≤30")
        self.assertEqual(output.records[0].properties["CEV"].comparator, "max")
        self.assertEqual(output.records[0].properties["CEV"].unit, "%")
        self.assertEqual(output.records[1].condition, ">30~63")

    def test_footnote_letters_and_quality_list_are_expanded(self) -> None:
        table = TableGrid(
            table_id="T9",
            page_no=1,
            n_rows=3,
            n_cols=3,
            header_rows=3,
            rows=[
                ["牌号", "牌号", "碳当量"],
                ["钢级", "质量等级", "公称厚度"],
                ["钢级", "质量等级", ">120~150°"],
                ["Q355a", "B、C", "0.49b"],
            ],
            header_paths=[
                ["牌号", "钢级"],
                ["牌号", "质量等级"],
                ["碳当量CEV(质量分数)/%不大于", "公称厚度或直径/mm", ">120~150°"],
            ],
        )
        binding = ColumnBindingResult(
            table_id="T9",
            bindings=[
                ColumnBinding(column=0, header_path=["牌号", "钢级"], role="row_key"),
                ColumnBinding(
                    column=1, header_path=["牌号", "质量等级"], role="row_key"
                ),
                ColumnBinding(
                    column=2,
                    header_path=["碳当量", ">120~150°"],
                    property="CEV",
                    role="measure",
                    unit="%",
                ),
            ],
        )
        output = extract_bound_matrix(table, binding, doc())
        assert output is not None
        self.assertEqual([row.grade for row in output.records], ["Q355B", "Q355C"])
        self.assertEqual(output.records[0].condition, ">120~150")
        self.assertEqual(output.records[0].properties["CEV"].raw, "0.49")

    def test_plain_measure_merges_into_existing_row(self) -> None:
        record = Record(
            record_id="qwen-1",
            source_table_id="T4",
            grade="30Si2MnCrMoVE",
            condition="推荐热处理制度:正火+回火",
            properties={"Rm": ExtractedValue(raw="1080", value=1080.0)},
        )
        output = ExtractionOutput(
            records=[
                Record(
                    record_id="matrix-1",
                    source_table_id="T4",
                    grade="30Si2MnCrMoVE",
                    properties={"KV2": ExtractedValue(raw="34", value=34.0)},
                )
            ]
        )
        merged, replace = merge_matrix_output([record], output, "T4")
        self.assertFalse(replace)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].record_id, "qwen-1")
        self.assertEqual(merged[0].condition, "推荐热处理制度:正火+回火")
        self.assertEqual(set(merged[0].properties), {"Rm", "KV2"})

    def test_conditioned_matrix_replaces_collapsed_rows(self) -> None:
        record = Record(
            record_id="qwen-1",
            source_table_id="T13",
            grade="Q355B",
            properties={"KV2": ExtractedValue(raw="34", value=34.0)},
        )
        output = ExtractionOutput(
            records=[
                Record(
                    record_id="matrix-1",
                    source_table_id="T13",
                    grade="Q355B",
                    condition="20℃/纵向",
                    properties={"KV2": ExtractedValue(raw="34", value=34.0)},
                )
            ]
        )
        merged, replace = merge_matrix_output([record], output, "T13")
        self.assertTrue(replace)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].record_id, "matrix-1")
        self.assertEqual(merged[0].condition, "20℃/纵向")


if __name__ == "__main__":
    unittest.main()
