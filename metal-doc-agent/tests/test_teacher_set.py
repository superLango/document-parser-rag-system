import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_teacher_set", ROOT / "tools" / "build_teacher_set.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class TeacherSetTests(unittest.TestCase):
    def test_l0_drops_row_values_not_in_cells(self) -> None:
        gold = {
            "task": "row_record",
            "input": {"row": ["2A14", "430"]},
        }
        raw = {
            "id": "d:row_record",
            "output": {
                "grade": "2A14",
                "condition": None,
                "properties": {
                    "Rm": {"raw": "430", "comparator": "min", "unit": "MPa"},
                    "A": {"raw": "999", "comparator": "min", "unit": "%"},
                },
            },
        }
        cleaned, dropped = module._apply_l0(raw, gold)
        assert cleaned is not None
        self.assertEqual(dropped, 1)
        self.assertEqual(list(cleaned["output"]["properties"]), ["Rm"])

    def test_l0_drops_clause_fields_not_in_text(self) -> None:
        gold = {
            "task": "clause_extract",
            "input": {"text": "氢含量应不大于0.18ml/100g。"},
        }
        raw = {
            "id": "d:clause_extract",
            "output": {
                "fields": {
                    "hydrogen_content": {
                        "raw": "不大于0.18ml/100g",
                        "text": "不大于0.18ml/100g",
                    },
                    "invented": {"raw": "0.001", "text": "0.001"},
                }
            },
        }
        cleaned, dropped = module._apply_l0(raw, gold)
        assert cleaned is not None
        self.assertEqual(dropped, 1)
        self.assertEqual(list(cleaned["output"]["fields"]), ["hydrogen_content"])

    def test_compare_row_record_counts_grade_condition_and_fields(self) -> None:
        teacher = {
            "grade": "2A14",
            "condition": "T6",
            "properties": {"Rm": {"raw": "430"}, "A": {"raw": "10"}},
        }
        gold = {
            "grade": "2A14",
            "condition": "T6 / 切向",
            "properties": {"Rm": {"raw": "430"}, "A": {"raw": "10"}},
        }
        ok, total = module._compare(teacher, gold, "row_record")
        self.assertEqual(total, 4)
        self.assertEqual(ok, 3)


if __name__ == "__main__":
    unittest.main()
