import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.schema_projection import load_template, project_job

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "configs" / "schema_templates" / "product_standard.json"


def _write_job(root: Path, *, value_raw: str = "430") -> Path:
    result = {
        "document": {
            "doc_id": "doc-test",
            "source_path": "test.pdf",
            "file_name": "doc-test-test.pdf",
            "standard_no": "GB/T 0000-2020",
            "title": "doc-test-test",
            "page_count": 2,
        },
        "records": [
            {
                "record_id": "rec-1",
                "source_table_id": "T1",
                "grade": "2A14",
                "condition": "T6 / 切向",
                "properties": {
                    "Rm": {
                        "raw": value_raw,
                        "value": 430.0 if value_raw.isdigit() else None,
                        "unit": "MPa",
                        "comparator": "min",
                        "evidence_id": "ev:rm",
                    },
                    "A": {
                        "raw": "10",
                        "value": 10.0,
                        "unit": "%",
                        "comparator": "min",
                        "evidence_id": "ev:a",
                    },
                },
            }
        ],
        "inspection_items": [
            {
                "item": "力学性能",
                "quantities": {"Ⅰ类": "逐件"},
                "sample_location": "轧制锻件本体",
                "requirement_clause": "4.5",
                "evidence_id": "ev:insp",
            }
        ],
        "classification_items": [{"grade": "2A14", "evidence_id": "ev:t1"}],
        "clauses": [
            {
                "clause_id": "4.5",
                "title": "室温力学性能",
                "kind": "technical_requirement",
                "fields": {
                    "requirement": {
                        "raw": "轧制锻件热处理后的硬度、力学性能应符合表2的规定。",
                        "text": "轧制锻件热处理后的硬度、力学性能应符合表2的规定。",
                        "comparator": "text",
                        "evidence_id": "ev:clause",
                    }
                },
            }
        ],
    }
    (root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )

    inventory = {
        "doc_id": "doc-test",
        "items": [
            {
                "item_raw": "室温力学性能",
                "item_canonical": "室温拉伸",
                "item_family": "tensile",
                "facets": {"temperature": "室温"},
                "properties": ["Rm", "A"],
                "method_standard": "GB/T 228",
                "table_id": "T1",
                "page_no": 1,
                "evidence": ["ev:item"],
                "status": "confirmed",
                "business_code": "CATEGORY:11",
                "business_name": "室温拉伸",
                "method_code": "TENS_RT:2362",
                "property_matches": [
                    {
                        "raw": "Rm",
                        "canonical_id": "TENS_RT:RM",
                        "canonical_name": "抗拉强度(Rm)",
                        "match_type": "exact",
                        "score": 1.0,
                        "dictionary_version": "test",
                        "status": "matched",
                    },
                    {
                        "raw": "A",
                        "canonical_id": "TENS_RT:3021",
                        "canonical_name": "断后伸长率A/%",
                        "match_type": "exact",
                        "score": 1.0,
                        "dictionary_version": "test",
                        "status": "matched",
                    },
                ],
            }
        ],
    }
    (root / "item_inventory_aligned.json").write_text(
        json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
    )

    outline = {
        "doc_id": "doc-test",
        "nodes": [
            {"node_id": "n1", "kind": "clause", "title": "某某研究院标准", "page_no": 1},
            {
                "node_id": "n2",
                "kind": "clause",
                "title": "铝合金锻件技术条件",
                "page_no": 1,
            },
            {
                "node_id": "n3",
                "kind": "clause",
                "title": "铝合金锻件技术条件",
                "page_no": 2,
            },
        ],
    }
    (root / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False), encoding="utf-8"
    )
    return root


class SchemaProjectionTests(unittest.TestCase):
    def test_template_shape(self) -> None:
        template = load_template(TEMPLATE_PATH)
        self.assertEqual(template.name, "产品标准抽取模板")
        self.assertEqual(len(template.categories), 3)
        self.assertEqual(sum(len(category.fields) for category in template.categories), 27)

    def test_project_items_and_standard_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp))
            payload = project_job(job, load_template(TEMPLATE_PATH))

        categories = {item["key"]: item for item in payload["categories"]}
        rows = categories["items"]["rows"]
        self.assertEqual(len(rows), 2)
        rm_row = rows[0]
        self.assertEqual(rm_row["项目名称"], "抗拉强度 Rm")
        self.assertEqual(rows[1]["项目名称"], "断后伸长率A")
        self.assertEqual(rm_row["材料牌号"], "2A14")
        self.assertEqual(rm_row["标准要求"], "≥430")
        self.assertEqual(rm_row["单位"], "MPa")
        self.assertEqual(rm_row["试验方法"], "GB/T 228.1-2021")
        self.assertEqual(rm_row["试验温度"], "室温")
        self.assertEqual(rm_row["方向"], "切向")
        self.assertEqual(rm_row["试样状态"], "T6")
        self.assertEqual(rm_row["取样数量"], 1)
        self.assertEqual(rm_row["位置"], "轧制锻件本体")

        info = categories["standard_info"]["rows"][0]
        self.assertEqual(info["标准名称"], "铝合金锻件技术条件")
        self.assertEqual(info["标准编号"], "GB/T 0000-2020")
        self.assertEqual(categories["heat_treatment"]["rows"], [])
        self.assertIn("热处理", categories["heat_treatment"]["note"])
        self.assertEqual(payload["coverage"]["required_rate"], 1.0)
        self.assertEqual(payload["errors"], [])

    def test_qualitative_item_uses_full_grade_and_clause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp))
            result_path = job / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["document"]["standard_no"] = "GB/T 1591-2018"
            result["records"] = []
            result["classification_items"] = [{"grade": "Q355B"}, {"grade": "Q390B"}]
            result["inspection_items"] = [
                {
                    "item": "弯曲试验",
                    "quantities": {"每批": "1个"},
                    "requirement_clause": None,
                    "evidence_id": "ev:bend",
                }
            ]
            result["clauses"] = [
                {
                    "clause_id": "7.4.3.1",
                    "title": "弯曲",
                    "kind": "technical_requirement",
                    "fields": {
                        "requirement": {
                            "raw": "根据需方要求，钢材可进行弯曲试验，其指标应符合表12的规定。",
                            "text": "根据需方要求，钢材可进行弯曲试验，其指标应符合表12的规定。",
                            "comparator": "text",
                            "evidence_id": "ev:bend-clause",
                        }
                    },
                }
            ]
            result_path.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            inventory_path = job / "item_inventory_aligned.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["items"] = [
                {
                    "item_raw": "弯曲试验",
                    "item_canonical": "弯曲",
                    "item_family": "bend",
                    "facets": {},
                    "properties": [],
                    "method_standard": "GB/T 232",
                    "table_id": "T1",
                    "page_no": 1,
                    "status": "confirmed",
                    "property_matches": [],
                }
            ]
            inventory_path.write_text(
                json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
            )
            payload = project_job(job, load_template(TEMPLATE_PATH))

        rows = payload["categories"][0]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["项目名称"], "弯曲")
        self.assertEqual(rows[0]["材料牌号"], "全部牌号")
        self.assertEqual(
            rows[0]["标准要求"],
            "根据需方要求，钢材可进行弯曲试验，其指标应符合表12的规定。",
        )
        self.assertEqual(payload["errors"], [])

    def test_missing_requirement_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp), value_raw="")
            result_path = job / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["clauses"] = []
            result["inspection_items"][0]["requirement_clause"] = None
            result_path.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            payload = project_job(job, load_template(TEMPLATE_PATH))

        errors = payload["errors"]
        self.assertTrue(
            any(
                error["field"] == "标准要求" and error["row"] == 0
                for error in errors
            )
        )
        self.assertLess(payload["coverage"]["required_rate"], 1.0)
        fields = payload["coverage"]["by_category"]["items"]["fields"]
        self.assertEqual(fields["标准要求"]["filled"], 1)

    def test_qualitative_item_has_no_unit_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp))
            inventory_path = job / "item_inventory_aligned.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["items"].append(
                {
                    "item_raw": "表面质量",
                    "item_canonical": "表面质量",
                    "item_family": "surface",
                    "facets": {"sampling_position": "轧制锻件本体"},
                    "properties": [],
                    "table_id": "T3",
                    "page_no": 1,
                    "status": "confirmed",
                    "business_code": "CATEGORY:69",
                    "business_name": "表面质量",
                    "property_matches": [],
                }
            )
            inventory_path.write_text(
                json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
            )
            result_path = job / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["inspection_items"].append(
                {
                    "item": "表面质量",
                    "quantities": {"Ⅰ类": "逐件"},
                    "sample_location": "轧制锻件本体",
                    "requirement_clause": "4.9",
                    "evidence_id": "ev:surface",
                }
            )
            result["clauses"].append(
                {
                    "clause_id": "4.9",
                    "title": "表面质量",
                    "kind": "technical_requirement",
                    "fields": {
                        "requirement": {
                            "raw": "轧制锻件表面不允许存在裂纹。",
                            "text": "轧制锻件表面不允许存在裂纹。",
                            "comparator": "text",
                        }
                    },
                }
            )
            result_path.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            payload = project_job(job, load_template(TEMPLATE_PATH))

        rows = payload["categories"][0]["rows"]
        surface = next(row for row in rows if row["项目名称"] == "表面质量")
        self.assertIsNone(surface["单位"])
        self.assertEqual(surface["标准要求"], "轧制锻件表面不允许存在裂纹。")
        self.assertFalse(
            any(error["field"] == "单位" for error in payload["errors"]),
        )
        self.assertEqual(payload["coverage"]["required_rate"], 1.0)

    def test_ambiguous_sample_count_is_left_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp))
            result_path = job / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["inspection_items"][0]["quantities"] = {
                "Ⅰ类": "逐件",
                "Ⅱ类": "每批抽2件",
            }
            result_path.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            payload = project_job(job, load_template(TEMPLATE_PATH))

        rows = payload["categories"][0]["rows"]
        self.assertTrue(all(row["取样数量"] is None for row in rows))
        self.assertIn("Ⅱ类:每批抽2件", rows[0]["取样说明"])
        self.assertEqual(
            payload["categories"][0]["meta"][0]["sample_quantities"],
            {"Ⅰ类": "逐件", "Ⅱ类": "每批抽2件"},
        )

    def test_chemical_element_matches_grade_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp))
            result_path = job / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["records"].append(
                {
                    "record_id": "rec-chem",
                    "source_table_id": "T9",
                    "grade": "Q355B",
                    "condition": "热轧",
                    "properties": {
                        "Si": {
                            "raw": "0.55",
                            "value": 0.55,
                            "unit": "%",
                            "comparator": "max",
                            "evidence_id": "ev:si",
                        }
                    },
                }
            )
            result_path.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            inventory_path = job / "item_inventory_aligned.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["items"].append(
                {
                    "item_raw": "化学成分",
                    "item_canonical": "化学成分",
                    "item_family": "chemical_composition",
                    "facets": {},
                    "properties": ["Si"],
                    "table_id": "T9",
                    "page_no": 1,
                    "status": "confirmed",
                    "business_code": "CATEGORY:3",
                    "business_name": "化学成分",
                    "property_matches": [
                        {
                            "raw": "Si",
                            "canonical_id": "CHEM:18",
                            "canonical_name": "Si",
                            "match_type": "exact",
                            "score": 1.0,
                            "dictionary_version": "test",
                            "status": "matched",
                        }
                    ],
                }
            )
            inventory_path.write_text(
                json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
            )
            payload = project_job(job, load_template(TEMPLATE_PATH))

        rows = payload["categories"][0]["rows"]
        silicon = next(row for row in rows if row["项目名称"] == "Si")
        self.assertEqual(silicon["材料牌号"], "Q355B")
        self.assertEqual(silicon["标准要求"], "≤0.55")
        self.assertEqual(silicon["单位"], "%")


    def test_condition_columns_for_impact_and_cev(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp))
            result_path = job / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["records"].extend(
                [
                    {
                        "record_id": "rec-kv2",
                        "source_table_id": "T9",
                        "grade": "Q355B",
                        "condition": "20℃/纵向",
                        "properties": {
                            "KV2": {
                                "raw": "34",
                                "value": 34.0,
                                "unit": "J",
                                "comparator": "min",
                                "condition": "20℃/纵向",
                                "evidence_id": "ev:kv2",
                            }
                        },
                    },
                    {
                        "record_id": "rec-cev",
                        "source_table_id": "T9",
                        "grade": "Q355B",
                        "condition": "≤30",
                        "properties": {
                            "CEV": {
                                "raw": "0.39",
                                "value": 0.39,
                                "unit": "%",
                                "comparator": "max",
                                "condition": "≤30",
                                "evidence_id": "ev:cev",
                            }
                        },
                    },
                ]
            )
            result_path.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            inventory_path = job / "item_inventory_aligned.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["items"].extend(
                [
                    {
                        "item_raw": "冲击试验",
                        "item_canonical": "夏比冲击",
                        "item_family": "impact",
                        "facets": {"impact_type": "夏比"},
                        "properties": ["KV2"],
                        "table_id": "T9",
                        "page_no": 1,
                        "status": "confirmed",
                        "business_code": "CATEGORY:12",
                        "business_name": "夏比冲击",
                        "property_matches": [
                            {
                                "raw": "KV2",
                                "canonical_id": "IMPACT:KV2",
                                "canonical_name": "冲击吸收功(KV2)",
                                "match_type": "exact",
                                "score": 1.0,
                                "dictionary_version": "test",
                                "status": "matched",
                            }
                        ],
                    },
                    {
                        "item_raw": "化学成分",
                        "item_canonical": "化学成分",
                        "item_family": "chemical_composition",
                        "facets": {},
                        "properties": ["CEV"],
                        "table_id": "T9",
                        "page_no": 1,
                        "status": "confirmed",
                        "business_code": "CATEGORY:3",
                        "business_name": "化学成分",
                        "property_matches": [
                            {
                                "raw": "CEV",
                                "canonical_id": "CHEM:CEV",
                                "canonical_name": "碳当量CEV",
                                "match_type": "exact",
                                "score": 1.0,
                                "dictionary_version": "test",
                                "status": "matched",
                            }
                        ],
                    },
                ]
            )
            inventory_path.write_text(
                json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
            )
            payload = project_job(job, load_template(TEMPLATE_PATH))

        rows = payload["categories"][0]["rows"]
        impact = next(row for row in rows if row["项目名称"] == "冲击吸收功 KV2")
        self.assertEqual(impact["试验温度"], "20℃")
        self.assertEqual(impact["方向"], "纵向")
        self.assertIsNone(impact["试样状态"])
        self.assertEqual(impact["标准要求"], "≥34")
        self.assertEqual(impact["单位"], "J")
        cev = next(row for row in rows if row["项目名称"] == "碳当量CEV")
        self.assertEqual(cev["尺寸厚度"], "≤30")
        self.assertEqual(cev["标准要求"], "≤0.39")
        self.assertEqual(cev["单位"], "%")
        self.assertIsNone(cev["试样状态"])


class InspectionMatchingTests(unittest.TestCase):
    def test_persistence_synonym_prefers_row_with_quantity(self) -> None:
        from metal_doc_agent.contracts import InspectionItem, ItemInventoryEntry
        from metal_doc_agent.schema_projection import _find_inspection

        item = ItemInventoryEntry(
            item_raw="高温纵向持久",
            item_canonical="持久",
            item_family="stress_rupture",
        )
        inspections = [
            InspectionItem(item="持久", quantities={"取样部位和数量": "-"}),
            InspectionItem(
                item="高温纵向持久",
                quantities={"取样数量，个": "1"},
                sample_location="头或尾",
            ),
        ]
        match = _find_inspection(item, inspections, "高温光滑持久")
        self.assertIsNotNone(match)
        self.assertEqual(match.item, "高温纵向持久")

    def test_two_character_dimension_name_matches(self) -> None:
        from metal_doc_agent.contracts import InspectionItem, ItemInventoryEntry
        from metal_doc_agent.schema_projection import _find_inspection

        item = ItemInventoryEntry(item_raw="尺寸", item_canonical="尺寸")
        inspections = [
            InspectionItem(
                item="尺寸、外形",
                quantities={"取样数量": "逐支"},
                sample_location="整支",
            )
        ]
        match = _find_inspection(item, inspections, "尺寸")
        self.assertIsNotNone(match)
        self.assertEqual(match.item, "尺寸、外形")

    def test_sample_count_range_and_minimum(self) -> None:
        from metal_doc_agent.contracts import InspectionItem
        from metal_doc_agent.schema_projection import _sample_count

        self.assertEqual(
            _sample_count(InspectionItem(item="硬度", quantities={"q": "1~2个/批"})),
            1,
        )
        self.assertEqual(
            _sample_count(
                InspectionItem(item="硬度", quantities={"q": "环形件10%，且不少于3件"})
            ),
            3,
        )
        self.assertIsNone(
            _sample_count(InspectionItem(item="硬度", quantities={"q": "10%"}))
        )
        self.assertEqual(
            _sample_count(InspectionItem(item="化学", quantities={"q": "每一炉号"})),
            1,
        )
        self.assertEqual(
            _sample_count(
                InspectionItem(item="化学", quantities={"q": "同一炉中的锻件"})
            ),
            1,
        )
        self.assertEqual(
            _sample_count(
                InspectionItem(
                    item="力学",
                    quantities={
                        "q": "每批钢板质量不大于3000kg，则截取一块试料"
                    },
                )
            ),
            1,
        )
        self.assertEqual(
            _sample_count(
                InspectionItem(item="力学", quantities={"q": "每10件随机抽取1件"})
            ),
            1,
        )
        self.assertEqual(
            _sample_count(InspectionItem(item="力学", quantities={"q": "每批取5个"})),
            5,
        )
        self.assertEqual(
            _sample_count(
                InspectionItem(
                    item="力学",
                    quantities={"q": "不多于100根钢管为一试验批，每批一次"},
                )
            ),
            1,
        )

    def test_sample_variants_expand_by_class(self) -> None:
        from metal_doc_agent.contracts import InspectionItem
        from metal_doc_agent.schema_projection import _expand_sample_variants

        inspection = InspectionItem(
            item="室温冲击",
            quantities={
                "I类环形件": "逐件试验环，1个",
                "II类环形件": "环形件或试验环，2个",
                "III类环形件": "-",
                "IV类环形件": "-",
            },
        )
        rows = _expand_sample_variants(
            [{"项目名称": "冲击吸收功"}], inspection, "夏比冲击"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["类别"], "I类环形件")
        self.assertEqual(rows[0]["取样数量"], 1)
        self.assertEqual(rows[1]["取样数量"], 2)

    def test_sample_variants_keep_single_row_when_identical(self) -> None:
        from metal_doc_agent.contracts import InspectionItem
        from metal_doc_agent.schema_projection import _expand_sample_variants

        inspection = InspectionItem(
            item="尺寸",
            quantities={
                "I类环形件": "逐件，整件",
                "II类环形件": "逐件，整件",
                "III类环形件": "逐件，整件",
                "IV类环形件": "逐件，整件",
            },
        )
        rows = _expand_sample_variants([{"项目名称": "尺寸"}], inspection, "尺寸")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("类别", rows[0])

    def test_chemical_rows_are_not_expanded(self) -> None:
        from metal_doc_agent.contracts import InspectionItem
        from metal_doc_agent.schema_projection import _expand_sample_variants

        inspection = InspectionItem(
            item="化学成分",
            quantities={"I类": "1个", "II类": "2个"},
        )
        rows = _expand_sample_variants([{"项目名称": "C"}], inspection, "化学成分")
        self.assertEqual(len(rows), 1)

    def test_temperature_range_is_not_negative(self) -> None:
        from metal_doc_agent.schema_projection import _temperature_from

        self.assertEqual(
            _temperature_from("固溶：1100-1200℃，保温8h"), "1100-1200℃"
        )
        self.assertEqual(_temperature_from("试验温度-40℃"), "-40℃")

    def test_hardness_prefers_room_temperature(self) -> None:
        from metal_doc_agent.contracts import ItemInventoryEntry, Record
        from metal_doc_agent.schema_projection import _hanson_temperature

        record = Record(
            record_id="r1",
            source_table_id="T1",
            grade="8896",
            condition="固溶：1100-1200℃ / 室温",
            properties={},
        )
        item = ItemInventoryEntry(item_raw="硬度", item_canonical="硬度")
        self.assertEqual(
            _hanson_temperature("布氏硬度", record, item), "室温"
        )
        range_record = Record(
            record_id="r2",
            source_table_id="T1",
            grade="8896",
            condition="固溶：990~1010℃",
            properties={},
        )
        self.assertEqual(
            _hanson_temperature("布氏硬度", range_record, item), "室温"
        )
        self.assertEqual(
            _hanson_temperature("夏比冲击", range_record, item), "室温"
        )

    def test_persistence_skips_footnote_rows(self) -> None:
        from metal_doc_agent.schema_projection import _hanson_persistence_rows

        footnote = "a GH1016高温拉伸和持久试验任选一个温度进行，合同中未注明时检验750℃性能。"
        tables = {
            "T1": {
                "header_paths": [
                    ["牌号"],
                    ["温度"],
                    ["持久应力σ"],
                    ["保持时间"],
                ],
                "header_rows": 1,
                "rows": [
                    ["牌号", "温度", "持久应力σ", "保持时间"],
                    ["GH1016", "750℃", "137", "100"],
                    [footnote, footnote, footnote, footnote],
                ],
            }
        }
        rows = _hanson_persistence_rows(tables, None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["材料牌号"], "GH1016")

    def test_test_temperature_ignores_heat_treatment(self) -> None:
        from metal_doc_agent.schema_projection import _test_temperature_from

        self.assertEqual(
            _test_temperature_from(
                "冷拉棒材a / ≤30 / 纵向 / 四熔:940℃~980℃ / I级或II级+固溶+时效 / 650°C"
            ),
            "650℃",
        )
        self.assertIsNone(
            _test_temperature_from(
                "15~400 / 固溶+时效 / 固溶(1020℃~1050℃保温1h~3h,水冷或空冷)"
            )
        )
        self.assertEqual(_test_temperature_from("A状态 / 400°C"), "400℃")

    def test_tensile_feature_uses_numeric_temperature(self) -> None:
        from metal_doc_agent.contracts import ItemInventoryEntry
        from metal_doc_agent.schema_projection import _hanson_feature

        item = ItemInventoryEntry(
            item_raw="400℃拉伸",
            item_canonical="拉伸",
            item_family="tensile",
            business_category_name="室温拉伸",
            business_name="室温拉伸",
        )
        self.assertEqual(_hanson_feature(item), "高温拉伸")

    def test_hanson_grade_replaces_level_or_upload_id(self) -> None:
        from metal_doc_agent.schema_projection import _hanson_grade

        self.assertEqual(_hanson_grade("A", "GH4169", "tensile"), "GH4169")
        self.assertEqual(_hanson_grade("7079", "GH4720Li", "tensile"), "GH4720Li")
        self.assertEqual(_hanson_grade("2A14", None, "tensile"), "2A14")
        self.assertEqual(_hanson_grade("7075", None, "tensile"), "7075")
        self.assertEqual(_hanson_grade("1476", None, "tensile"), "")
        self.assertEqual(
            _hanson_grade(
                "4985",
                None,
                "tensile",
                "56009ac958bd4985a927f9a2c942fa241788510524268",
            ),
            "",
        )
        self.assertEqual(
            _hanson_grade("7075", None, "tensile", "7075铝合金棒材"), "7075"
        )
        self.assertEqual(_hanson_grade("", None, "dimension"), "全部牌号")

    def test_hardness_method_selects_matching_scale(self) -> None:
        from metal_doc_agent.schema_projection import _select_hardness_method

        self.assertEqual(
            _select_hardness_method("GB/T230.1,GB/T231.1", "洛氏硬度"),
            "GB/T230.1",
        )
        self.assertEqual(
            _select_hardness_method("GB/T230.1,GB/T231.1", "布氏硬度"),
            "GB/T231.1",
        )

    def test_document_grade_ignores_upload_prefix(self) -> None:
        from metal_doc_agent.contracts import DocumentMeta
        from metal_doc_agent.extraction.qwen import _document_grade

        prefixed = DocumentMeta(
            doc_id="x",
            source_path="x",
            file_name="8896bcd83fe247e1a2b812b72b2fc241-jx25_035.pdf",
            title="8896bcd83fe247e1a2b812b72b2fc241-jx25_035",
        )
        self.assertIsNone(_document_grade(prefixed))
        real = DocumentMeta(
            doc_id="x",
            source_path="x",
            file_name="GH4698高温合金棒材.pdf",
            title="GH4698高温合金棒材",
        )
        self.assertEqual(_document_grade(real), "GH4698")

    def test_hardness_candidates_filter_by_scale(self) -> None:
        from metal_doc_agent.contracts import (
            ExtractedValue,
            ItemInventoryEntry,
            Record,
        )
        from metal_doc_agent.schema_projection import _hanson_candidates

        def value() -> ExtractedValue:
            return ExtractedValue(raw="1", value=1.0, comparator="min")

        hb = Record(record_id="hb", properties={"HB": value()})
        hrc = Record(record_id="hrc", properties={"HRC": value()})
        brinell = ItemInventoryEntry(
            item_raw="布氏硬度",
            item_family="hardness",
            facets={"hardness_scale": "brinell"},
        )
        rockwell = ItemInventoryEntry(
            item_raw="洛氏硬度",
            item_family="hardness",
            facets={"hardness_scale": "rockwell"},
        )
        records = [hb, hrc]
        self.assertEqual(
            [record.record_id for record in _hanson_candidates(
                brinell, "布氏硬度", records, {}
            )],
            ["hb"],
        )
        self.assertEqual(
            [record.record_id for record in _hanson_candidates(
                rockwell, "洛氏硬度", records, {}
            )],
            ["hrc"],
        )

    def test_chemistry_sampling_default(self) -> None:
        from metal_doc_agent.schema_projection import _sampling_default

        chemical = _sampling_default("chemical_composition")
        self.assertIsNotNone(chemical)
        self.assertEqual(chemical["quantity"], 1)
        self.assertIsNone(_sampling_default("tensile"))

    def test_document_method_index_fills_reference_methods(self) -> None:
        from metal_doc_agent.schema_projection import _document_method_index

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pages.json").write_text(
                json.dumps(
                    [
                        {
                            "page_no": 1,
                            "markdown": (
                                "GB/T 223 钢铁及合金化学分析方法 "
                                "GB/T 228.1-2021 金属材料拉伸试验 "
                                "GB/T 229-2020 金属材料夏比摆锤冲击试验方法"
                            ),
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            index = _document_method_index(root)

        self.assertTrue(index["chemical_composition"].startswith("GB/T 223"))
        self.assertTrue(index["tensile"].startswith("GB/T 228.1"))
        self.assertTrue(index["impact"].startswith("GB/T 229"))

    def test_document_method_index_supports_external_standards(self) -> None:
        from metal_doc_agent.schema_projection import _document_method_index

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pages.json").write_text(
                json.dumps(
                    [
                        {
                            "page_no": 1,
                            "markdown": (
                                "ASTM A751 钢制品化学分析的标准测试方法 "
                                "ASTM A370 钢制品机械性能标准试验方法 "
                                "ISO 148-1 金属材料夏比摆锤冲击试验 "
                                "JIS Z 2241 金属材料引張試験方法"
                            ),
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            index = _document_method_index(root)

        self.assertEqual(index["chemical_composition"], "ASTM A751")
        self.assertEqual(index["tensile"], "ASTM A370")
        self.assertEqual(index["impact"], "ISO 148-1")

    def test_inspection_method_is_used_as_fallback(self) -> None:
        from metal_doc_agent.schema_projection import project_hanson_schema

        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp))
            inventory_path = job / "item_inventory_aligned.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            item = inventory["items"][0]
            item["method_standard"] = None
            item["method_code"] = None
            item["method_name"] = None
            inventory_path.write_text(
                json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
            )
            result_path = job / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["inspection_items"][0]["method_standard"] = "ASTM A370"
            result_path.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            payload = project_hanson_schema(job, load_template(TEMPLATE_PATH))

        tensile = next(
            category
            for category in payload["categories"]
            if category.get("feature") == "室温拉伸"
        )
        self.assertEqual(tensile["records"][0]["试验方法"], "ASTM A370")

    def test_not_applicable_category_is_not_projected(self) -> None:
        from metal_doc_agent.schema_projection import project_hanson_schema

        with tempfile.TemporaryDirectory() as tmp:
            job = _write_job(Path(tmp))
            inventory_path = job / "item_inventory_aligned.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["items"].append(
                {
                    "item_raw": "产品标识",
                    "item_canonical": "产品标识",
                    "item_family": "marking",
                    "facets": {},
                    "evidence": ["ev:item"],
                    "status": "not_applicable",
                }
            )
            inventory_path.write_text(
                json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
            )
            payload = project_hanson_schema(job, load_template(TEMPLATE_PATH))

        features = {
            category.get("feature") for category in payload["categories"]
        }
        self.assertNotIn("产品标识", features)

    def test_referenced_table_content_is_inlined_into_requirement(self) -> None:
        from metal_doc_agent.schema_projection import (
            _augment_requirements_with_tables,
        )

        tables = {
            "T1": {
                "table_id": "T1",
                "caption": "表 B.4 晶粒度和显微组织",
                "header_rows": 1,
                "header_paths": [
                    ["级别"],
                    ["晶粒度"],
                    ["δ相"],
                    ["Laves相"],
                ],
                "rows": [
                    ["级别", "晶粒度", "δ相", "Laves相"],
                    ["B", "2级或更细", "晶界不应有针状δ相", "不应有Laves相"],
                ],
            }
        }
        groups = {
            "高倍组织": [
                {"标准要求": "显微组织应符合表B.4的规定。"}
            ],
            "晶粒度": [{"标准要求": ""}],
        }
        _augment_requirements_with_tables(groups, tables)
        high_magnification = groups["高倍组织"][0]["标准要求"]
        grain_size = groups["晶粒度"][0]["标准要求"]
        self.assertIn("表 B.4 晶粒度和显微组织", high_magnification)
        self.assertIn("级别=B", high_magnification)
        self.assertIn("2级或更细", high_magnification)
        self.assertIn("不应有Laves相", grain_size)

    def test_stainless_grade_from_document_title(self) -> None:
        from metal_doc_agent.schema_projection import _grade_from_text

        self.assertEqual(
            _grade_from_text("0Cr17Ni4Cu4Nb不锈钢锻件技术条件"),
            "0Cr17Ni4Cu4Nb",
        )
        self.assertEqual(
            _grade_from_text("04Cr13Ni5Mo不锈钢锭采购技术协议"),
            "04Cr13Ni5Mo",
        )

    def test_header_like_row_is_detected(self) -> None:
        from metal_doc_agent.extraction.qwen import _is_header_like_row

        paths = [
            ["序号"],
            ["材料牌号"],
            ["供应状态"],
            ["力学性能", "纵向", "抗拉强度RmMPa"],
            ["力学性能", "纵向", "断后伸长率A%"],
        ]
        self.assertTrue(
            _is_header_like_row(
                ["序号", "材料牌号", "供应状态", "抗拉强度RmMPa", "断后伸长率A%"],
                paths,
            )
        )
        self.assertFalse(
            _is_header_like_row(["1", "2A11", "T4", "≥355", "≥6"], paths)
        )

    def test_captionless_table_number_falls_back_to_document_order(self) -> None:
        from metal_doc_agent.schema_projection import _tables_for_requirement

        tables = {
            "T1": {
                "table_id": "T1",
                "caption": None,
                "profile": "chemical_composition",
                "rows": [],
            },
            "T2": {
                "table_id": "T2",
                "caption": None,
                "profile": "mechanical_properties",
                "rows": [],
            },
            "T4": {
                "table_id": "T4",
                "caption": None,
                "profile": "mechanical_properties",
                "rows": [],
            },
        }
        chemical = _tables_for_requirement(
            "化学成分", "应符合表1的规定", tables
        )
        self.assertEqual([table["table_id"] for table in chemical], ["T1"])
        low_mag = _tables_for_requirement(
            "低倍", "锻件按表4中规定检查低倍组织", tables
        )
        self.assertEqual(low_mag, [])


if __name__ == "__main__":
    unittest.main()
