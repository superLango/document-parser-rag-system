import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_m2_dataset", ROOT / "tools" / "build_m2_dataset.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class M2DatasetTests(unittest.TestCase):
    def test_derive_mapping_roles(self) -> None:
        rows = [
            ["牌号", "状态", "方向", "Rm", "A"],
            ["2A14", "T6", "切向", "430", "10"],
        ]
        records = [
            {
                "grade": "2A14",
                "condition": "T6 / 切向",
                "facets": {"direction": "切向"},
                "properties": {
                    "Rm": {
                        "raw": "430",
                        "unit": "MPa",
                        "comparator": "min",
                        "evidence": {"row": 1, "col": 3},
                    },
                    "A": {
                        "raw": "10",
                        "unit": "%",
                        "comparator": "min",
                        "evidence": {"row": 1, "col": 4},
                    },
                },
            }
        ]
        mapping, error = module._derive_mapping(rows, records)
        self.assertIsNone(error)
        self.assertEqual(mapping[0], {"role": "grade"})
        self.assertEqual(mapping[1], {"role": "condition"})
        self.assertEqual(mapping[2], {"role": "condition"})
        self.assertEqual(mapping[3]["role"], "property")
        self.assertEqual(mapping[3]["property"], "Rm")
        self.assertEqual(mapping[4]["property"], "A")

    def test_derive_mapping_conflict(self) -> None:
        rows = [["牌号", "Rm"], ["2A14", "430"], ["2A14", "350"]]
        records = [
            {
                "grade": "2A14",
                "properties": {
                    "Rm": {"evidence": {"row": 1, "col": 1}},
                    "Rp0.2": {"evidence": {"row": 2, "col": 1}},
                },
            }
        ]
        mapping, error = module._derive_mapping(rows, records)
        self.assertEqual(mapping, {})
        self.assertIn("mapping_conflict", error or "")

    def test_splits_and_leakage(self) -> None:
        splits = module._build_splits(
            [
                {"doc_id": "a", "split": "mini"},
                {"doc_id": "b", "split": "dev"},
                {"doc_id": "c", "split": "heldout"},
            ]
        )
        self.assertEqual(splits, {"train": ["a"], "dev": ["b"], "heldout": ["c"]})
        self.assertEqual(module._leakage_issues(splits), [])
        leaked = {"train": ["a"], "dev": ["a"], "heldout": []}
        self.assertTrue(module._leakage_issues(leaked))

    def test_clause_sample_shape(self) -> None:
        sample = module._clause_sample(
            {
                "clause_id": "4.2.2",
                "title": "氢含量应不大于 0.18ml/100g",
                "kind": "technical_requirement",
                "fields": {
                    "hydrogen_content": {
                        "raw": "不大于 0.18ml/100g",
                        "comparator": "max",
                        "unit": "ml/100g",
                        "evidence": {"quote": "氢含量应不大于0.18ml/100g。"},
                    }
                },
            },
            "doc",
            "train",
        )
        assert sample is not None
        self.assertEqual(sample["task"], "clause_extract")
        self.assertEqual(sample["output"]["fields"]["hydrogen_content"]["unit"], "ml/100g")
        self.assertEqual(sample["input"]["quotes"], ["氢含量应不大于0.18ml/100g。"])
        self.assertIn("氢含量应不大于0.18ml/100g。", sample["input"]["text"])

    def _row_sample(self, grade: str | None = "2A14") -> dict:
        return {
            "task": "row_record",
            "doc_id": "doc",
            "table_id": "T1",
            "profile": "mechanical_properties",
            "input": {
                "header_paths": [["牌号"], ["状态"], ["Rm/MPa"], ["A/%"]],
                "mapping": {
                    "columns": [
                        {"index": 0, "role": "grade"},
                        {"index": 1, "role": "condition"},
                        {
                            "index": 2,
                            "role": "property",
                            "property": "Rm",
                            "unit": "MPa",
                        },
                        {"index": 3, "role": "property", "property": "A", "unit": "%"},
                    ]
                },
                "row": ["2A14", "T6", "430", "10"],
            },
            "output": {
                "grade": grade,
                "condition": "T6",
                "properties": {"Rm": {"raw": "430"}, "A": {"raw": "10"}},
            },
            "meta": {"split": "train", "row_index": 0},
        }

    def test_perturb_variants_are_surface_only(self) -> None:
        variants = module._perturb_samples(self._row_sample(), "train")
        self.assertEqual(len(variants), 2)
        numeric, surface = variants
        self.assertEqual(numeric["task"], "row_record_perturb")
        self.assertEqual(numeric["input"]["row"][2], "4 30")
        self.assertEqual(numeric["output"], self._row_sample()["output"])
        self.assertEqual(numeric["meta"]["ops"][0]["kind"], "digit_space")
        self.assertEqual(surface["input"]["row"][0], "2A14a")
        self.assertEqual(surface["meta"]["ops"][0]["kind"], "grade_footnote")

        alias = module._perturb_samples(self._row_sample(grade=None), "train")[1]
        self.assertEqual(alias["meta"]["ops"][0]["kind"], "header_alias")
        self.assertEqual(alias["input"]["header_paths"][2][-1], "抗拉强度/MPa")

    def test_heldout_has_no_perturbations(self) -> None:
        self.assertEqual(module._perturb_samples(self._row_sample(), "heldout"), [])

    def test_citation_samples_carry_replay_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            payload = {
                "budget": {"max_documents": 2},
                "references": [
                    self._reference("S1", "schema", True, "selected"),
                    self._reference("S2", "schema", True, "selected"),
                    self._reference("S1", "schema", True, "duplicate"),
                    self._reference("S3", "schema", False, "budget_exceeded"),
                ],
            }
            (run_dir / "references.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            samples = module._citation_samples(run_dir, "doc", "dev")
            self.assertEqual(len(samples), 4)
            self.assertEqual(samples[1]["input"]["context"]["duplicate"], True)
            self.assertEqual(samples[1]["input"]["context"]["rank"], 2)
            self.assertEqual(samples[2]["input"]["context"]["selected_before"], 1)
            self.assertEqual(samples[3]["input"]["context"]["selected_before"], 2)
            self.assertEqual(samples[3]["output"]["selection_reason"], "budget_exceeded")

    @staticmethod
    def _reference(
        standard_no: str, relevance: str, expand: bool, reason: str
    ) -> dict:
        return {
            "raw": standard_no,
            "standard_no": standard_no,
            "title": "方法",
            "relation": "normative",
            "dated": False,
            "relevance": relevance,
            "expand": expand,
            "selection_reason": reason,
        }


if __name__ == "__main__":
    unittest.main()
