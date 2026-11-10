import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_sft", ROOT / "tools" / "prepare_sft.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SftDataTests(unittest.TestCase):
    def test_row_messages_and_json_output(self) -> None:
        rows = [
            {
                "task": "row_record",
                "doc_id": "doc",
                "input": {"row": ["2A14", "430"]},
                "output": {"grade": "2A14", "properties": {"Rm": {"raw": "430"}}},
            }
        ]
        converted = module._convert(rows)
        self.assertEqual(len(converted), 1)
        messages = converted[0]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("row_record", messages[1]["content"])
        self.assertIn('"row"', messages[1]["content"])
        self.assertEqual(
            json.loads(messages[2]["content"])["properties"]["Rm"]["raw"], "430"
        )

    def test_unknown_task_is_skipped(self) -> None:
        rows = [{"task": "unknown", "doc_id": "doc", "input": {}, "output": {}}]
        self.assertEqual(module._convert(rows), [])


if __name__ == "__main__":
    unittest.main()
