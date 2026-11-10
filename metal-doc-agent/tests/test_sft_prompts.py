"""SFT prompt texts must match between training-data builder and inference."""

from __future__ import annotations

import unittest

from metal_doc_agent.extraction import sft_prompts
from tools import prepare_sft


class SftPromptTests(unittest.TestCase):
    def test_prepare_sft_uses_shared_prompts(self) -> None:
        self.assertEqual(prepare_sft.SYSTEM, sft_prompts.SYSTEM)
        self.assertEqual(prepare_sft.INSTRUCTIONS, sft_prompts.INSTRUCTIONS)

    def test_tasks_cover_sft_dataset(self) -> None:
        for task in (
            "header_mapping",
            "header_mapping_constrained",
            "row_record",
            "row_record_perturb",
            "clause_extract",
            "citation_constraint",
        ):
            self.assertIn(task, sft_prompts.INSTRUCTIONS)

    def test_row_instruction_requires_raw_from_row(self) -> None:
        instruction = sft_prompts.INSTRUCTIONS["row_record"]
        self.assertIn("raw 必须逐字来自 row", instruction)
        self.assertIn("只输出 JSON", sft_prompts.SYSTEM)


if __name__ == "__main__":
    unittest.main()
