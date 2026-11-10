"""SFT v2 builder: constrained header payload + engine-canonical gold."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import build_sft_v2


class SftV2BuilderTests(unittest.TestCase):
    def test_constrained_header_and_canonical_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset"
            runs = root / "runs"
            (dataset).mkdir()
            (runs / "d1" / "tablegrid").mkdir(parents=True)
            table = {
                "caption": "表1 化学成分",
                "profile": "chemical_composition",
                "orientation": "grade_rows",
                "n_cols": 3,
            }
            (runs / "d1" / "tablegrid" / "T1.json").write_text(
                json.dumps(table, ensure_ascii=False), encoding="utf-8"
            )
            header = {
                "task": "header_mapping",
                "doc_id": "d1",
                "table_id": "T1",
                "profile": "chemical_composition",
                "input": {"header_paths": [["牌号"], ["C"], ["其他"]], "sample_rows": [["2A14", "0.03", "0.05"]]},
                "output": {
                    "columns": [
                        {"index": 0, "role": "grade"},
                        {"index": 1, "role": "property", "property": "C", "unit": "%"},
                        {"index": 2, "role": "property", "property": "其他杂质", "unit": "%"},
                    ]
                },
            }
            row = {
                "task": "row_record",
                "doc_id": "d1",
                "table_id": "T1",
                "profile": "chemical_composition",
                "input": {"header_paths": [["牌号"], ["C"]], "mapping": {"columns": []}, "row": ["2A14", "0.03"]},
                "output": {
                    "grade": "2A14",
                    "properties": {
                        "C": {"raw": "0.03", "unit": "%"},
                        "其他杂质": {"raw": "0.05", "unit": "%"},
                    },
                },
            }
            lines = [
                json.dumps(header, ensure_ascii=False),
                json.dumps(row, ensure_ascii=False),
            ]
            (dataset / "train.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

            build_sft_v2.main(
                [
                    "--dataset",
                    str(dataset),
                    "--runs",
                    str(runs),
                    "--out",
                    str(root / "out"),
                ]
            )

            rows = [
                json.loads(line)
                for line in (root / "out" / "train.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            header_row = next(item for item in rows if item["task"] == "header_mapping_constrained")
            user = header_row["messages"][1]["content"]
            self.assertIn("allowed_properties", user)
            self.assertIn("allowed_elements", user)
            gold = json.loads(header_row["messages"][2]["content"])
            roles = {col["index"]: col["role"] for col in gold["columns"]}
            self.assertEqual(roles[1], "property")
            self.assertEqual(roles[2], "ignore")

            row_row = next(item for item in rows if item["task"] == "row_record")
            properties = json.loads(row_row["messages"][2]["content"])["properties"]
            self.assertIn("C", properties)
            self.assertNotIn("其他杂质", properties)

            report = json.loads((root / "out" / "report.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(report["train"]["header_property_dropped"], 1)
            self.assertGreaterEqual(report["train"]["row_property_dropped"], 1)


if __name__ == "__main__":
    unittest.main()
