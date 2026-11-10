"""Tests for the hansonDoc_RAG schema projection."""

from __future__ import annotations

import unittest

from tools.export_hanson_schema import build_payload


def table(table_id: str, profile: str, header_rows: int, rows: list[list[str]], context: str = "") -> dict:
    return {
        "table_id": table_id,
        "profile": profile,
        "header_rows": header_rows,
        "rows": rows,
        "caption": "",
        "context": context,
        "header_paths": [],
    }


RESULT = {
    "document": {"title": "钛及钛合金棒材", "standard_no": "GB/T 2965-2007"},
    "tables": [
        table("T2", "mechanical_properties", 2, [
            ["牌号", "Rm", "A"],
            ["牌号", "Rm", "A"],
            ["TA1", "240", "24"],
        ], context="其纵向室温力学性能应符合表2的规定"),
        table("T3", "mechanical_properties", 2, [
            ["牌号", "试验温度", "Rm"],
            ["牌号", "试验温度", "Rm"],
            ["TA6", "350", "420"],
        ]),
        table("T7", "classification", 1, [
            ["牌号", "加热温度，保温时间，冷却方式"],
            ["TB2", "淬火：800℃~850℃，30min，空冷或水冷。 时效：450℃~500℃，8h，空冷"],
            ["注1：当合同中注明时，可选等温退火。", "注1：当合同中注明时，可选等温退火。"],
        ]),
    ],
    "records": [
        {
            "source_table_id": "T2",
            "grade": "TA1",
            "condition": None,
            "properties": {
                "Rm": {"raw": "240", "comparator": "min", "unit": "MPa"},
                "A": {"raw": "24", "comparator": "min", "unit": "%"},
            },
        },
        {
            "source_table_id": "T3",
            "grade": "TA6",
            "condition": "350°C",
            "properties": {
                "Rm": {"raw": "420", "comparator": "min", "unit": "MPa"},
                "σ100h": {"raw": "390", "comparator": "min", "unit": "MPa"},
                "σ50h": {"raw": "-", "comparator": "na", "unit": "MPa"},
            },
        },
    ],
}


class HansonSchemaExportTests(unittest.TestCase):
    def test_projection_categories_and_comparators(self) -> None:
        payload = build_payload(RESULT, timing_seconds=1.5)
        self.assertEqual(payload["schema_name"], "产品标准抽取模板")
        features = [c["feature"] for c in payload["categories"]]
        self.assertIn("标准信息", features)
        self.assertIn("热处理制度", features)
        self.assertIn("室温拉伸", features)
        self.assertIn("高温拉伸", features)
        self.assertIn("高温光滑持久", features)

        standard = payload["categories"][0]["records"][0]
        self.assertEqual(standard["标准编号"], "GB/T 2965-2007")

        room = [r for c in payload["categories"] if c["feature"] == "室温拉伸" for r in c["records"]]
        self.assertEqual(room[0]["标准要求"], "≥240")
        self.assertEqual(room[0]["试验温度"], "室温")
        self.assertEqual(room[0]["方向"], "纵向")

        hot = [r for c in payload["categories"] if c["feature"] == "高温拉伸" for r in c["records"]]
        self.assertEqual(hot[0]["试验温度"], "350℃")

        persistence = [
            r for c in payload["categories"] if c["feature"] == "高温光滑持久" for r in c["records"]
        ]
        self.assertEqual(len(persistence), 1)
        self.assertEqual(persistence[0]["项目名称"], "持久强度σ100h")
        self.assertEqual(persistence[0]["标准要求"], "≥390")

        heat = [r for c in payload["categories"] if c["feature"] == "热处理制度" for r in c["records"]]
        self.assertEqual(len(heat), 2)
        self.assertEqual(heat[0]["工艺名称"], "淬火")
        self.assertEqual(heat[0]["保温温度"], "800℃~850℃")
        self.assertEqual(heat[1]["工艺名称"], "时效")

    def test_slim_projection_from_job_artifacts(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        result = {
            "document": {
                "doc_id": "demo-ta15",
                "source_path": "demo-TA15.pdf",
                "title": "TA15 钛合金锻制棒材",
                "standard_no": "Q/S 10-0351-2004",
                "file_name": "demo-TA15.pdf",
                "page_count": 1,
            },
            "tables": [
                {"table_id": "T2", "profile": "chemical_composition", "rows": []},
                {"table_id": "T3", "profile": "mechanical_properties", "rows": []},
                {"table_id": "T4", "profile": "mechanical_properties", "rows": []},
            ],
            "records": [
                {
                    "record_id": "rec-chem",
                    "source_table_id": "T2",
                    "grade": "TA15",
                    "condition": "化学成分",
                    "properties": {
                        "Al": {
                            "raw": "5.50~7.00",
                            "unit": "%",
                            "comparator": "range",
                        }
                    },
                },
                {
                    "record_id": "rec-room",
                    "source_table_id": "T3",
                    "grade": "TA15",
                    "condition": "20°C",
                    "properties": {
                        "Rm": {"raw": "885~1130", "unit": "MPa", "comparator": "range"},
                        "A": {"raw": "8", "unit": "%", "comparator": "min"},
                    },
                },
                {
                    "record_id": "rec-hot",
                    "source_table_id": "T4",
                    "grade": "TA15",
                    "condition": "500°C",
                    "properties": {
                        "Rm": {"raw": "570", "unit": "MPa", "comparator": "min"}
                    },
                },
            ],
            "inspection_items": [
                {
                    "item": "化学成分",
                    "quantities": {"default": "1"},
                    "sample_location": "一",
                    "requirement_clause": "3.2",
                },
                {
                    "item": "室温拉伸",
                    "quantities": {"default": "2"},
                    "sample_location": "D/4弦向",
                    "requirement_clause": "3.4",
                },
                {
                    "item": "高温拉伸",
                    "quantities": {"default": "2"},
                    "sample_location": "D/4弦向",
                    "requirement_clause": "3.4",
                },
            ],
            "clauses": [
                {
                    "clause_id": "3.2",
                    "fields": {"requirement": {"raw": "化学成分应符合表1的规定。"}},
                },
                {
                    "clause_id": "3.4",
                    "fields": {"requirement": {"raw": "力学性能应符合表2的规定。"}},
                },
            ],
        }
        inventory = {
            "doc_id": "demo",
            "items": [
                {
                    "item_raw": "化学成分",
                    "item_family": "chemical_composition",
                    "business_category_name": "化学成分",
                    "properties": ["Al"],
                    "method_standard": "GB/T 4698",
                    "facets": {"sampling_quantity": "1", "sampling_position": "一"},
                    "status": "confirmed",
                },
                {
                    "item_raw": "室温拉伸",
                    "item_family": "tensile",
                    "business_category_name": "室温拉伸",
                    "properties": ["Rm", "A"],
                    "method_standard": "GB/T 228.1",
                    "facets": {"temperature": "室温", "sampling_quantity": "2"},
                    "status": "confirmed",
                },
                {
                    "item_raw": "高温拉伸",
                    "item_family": "tensile",
                    "business_category_name": "高温拉伸",
                    "properties": [],
                    "method_standard": "GB/T 228.2",
                    "facets": {"temperature": "高温", "sampling_quantity": "2"},
                    "status": "confirmed",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "result.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            (root / "item_inventory_aligned.json").write_text(
                json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
            )
            payload = build_payload(result, timing_seconds=2.0, job_dir=root)
            reviewed = json.loads(json.dumps(result))
            reviewed["records"][0]["properties"]["Al"]["raw"] = "6.00~7.50"
            payload_reviewed = build_payload(reviewed, timing_seconds=2.0, job_dir=root)

        features = [category["feature"] for category in payload["categories"]]
        self.assertEqual(features, ["标准信息", "化学成分", "室温拉伸", "高温拉伸"])
        self.assertEqual(payload["categories"][0]["records"][0]["标准名称"], "TA15 钛合金锻制棒材")
        for category in payload["categories"]:
            self.assertNotIn("rejected", category)
            self.assertNotIn("hit_score", category)
            self.assertIn("missing_fields", category)
        room = next(c for c in payload["categories"] if c["feature"] == "室温拉伸")
        hot = next(c for c in payload["categories"] if c["feature"] == "高温拉伸")
        self.assertEqual(room["records"][0]["试验温度"], "室温")
        self.assertEqual(room["records"][0]["标准要求"], "885~1130")
        self.assertEqual(hot["records"][0]["试验温度"], "500℃")
        self.assertEqual(hot["records"][0]["标准要求"], "≥570")
        self.assertNotIn("取样说明", room["records"][0])
        chemical = next(c for c in payload["categories"] if c["feature"] == "化学成分")
        reviewed_chemical = next(
            c for c in payload_reviewed["categories"] if c["feature"] == "化学成分"
        )
        self.assertEqual(chemical["records"][0]["标准要求"], "5.50~7.00")
        self.assertEqual(reviewed_chemical["records"][0]["标准要求"], "6.00~7.50")
        self.assertEqual(payload["summary"]["total_records"], 5)


if __name__ == "__main__":
    unittest.main()
