"""SFT prompt style: header mapping, row supplement, fallback, row filtering."""

from __future__ import annotations

import unittest
from pathlib import Path

from metal_doc_agent.contracts import DocumentMeta, TableGrid
from metal_doc_agent.extraction.qwen import QwenExtractor
from metal_doc_agent.extraction.sft_prompts import SYSTEM as SFT_SYSTEM
from metal_doc_agent.settings import Settings
from metal_doc_agent.tablegrid.parser import parse_table

MECH_HTML = (
    "<table>"
    "<tr><td>牌号</td><td>热处理状态</td><td>取样方向</td>"
    "<td>抗拉强度Rm/MPa(不小于)</td><td>断后伸长率A/%(不小于)</td></tr>"
    "<tr><td>2A14</td><td>T6</td><td>切向</td><td>430</td><td>10</td></tr>"
    "</table>"
)

CHEM_HTML = (
    "<table>"
    "<tr><td>牌号</td><td>化学成分(%)</td><td>化学成分(%)</td><td>其他杂质(%)</td></tr>"
    "<tr><td></td><td>C</td><td>Si</td><td>总和</td></tr>"
    "<tr><td>2A14</td><td>0.015~0.060</td><td>0.35</td><td>0.05</td></tr>"
    "</table>"
)

CHEM_DUP_HTML = (
    "<table>"
    "<tr><td>牌号</td><td>C</td><td>Si</td></tr>"
    "<tr><td>2A14</td><td>0.03</td><td>0.35</td></tr>"
    "<tr><td>牌号</td><td>C</td><td>Si</td></tr>"
    "<tr><td>2A14</td><td>0.03</td><td>0.35</td></tr>"
    "</table>"
)

MECH_MAPPING = (
    '{"columns":[{"index":0,"role":"grade"},{"index":1,"role":"condition"},'
    '{"index":2,"role":"condition"},{"index":3,"role":"property","property":"Rm","unit":"MPa"},'
    '{"index":4,"role":"property","property":"A","unit":"%"}]}'
)
CHEM_MAPPING = (
    '{"columns":[{"index":0,"role":"grade"},{"index":1,"role":"property","property":"C","unit":"%"},'
    '{"index":2,"role":"property","property":"Si","unit":"%"},{"index":3,"role":"ignore"}]}'
)
MECH_MAPPING_NO_GRADE = (
    '{"columns":[{"index":0,"role":"condition"},'
    '{"index":1,"role":"property","property":"Rm","unit":"MPa"}]}'
)
MECH_ROW = (
    '{"grade":"2A14","condition":"T6 / 切向","properties":{'
    '"Rm":{"raw":"430","comparator":"min","unit":"MPa"},'
    '"A":{"raw":"10","comparator":"min","unit":"%"}}}'
)
CHEM_ROW = (
    '{"grade":"2A14","properties":{'
    '"C":{"raw":"0.015~0.060","comparator":"range","unit":"%"},'
    '"Si":{"raw":"0.35","comparator":"max","unit":"%"},'
    '"其他元素":{"raw":"0.05","comparator":"max","unit":"%"}}}'
)


class FakeQwen:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses.pop(0)


def make_settings(style: str = "native", row_limit: int = 30) -> Settings:
    return Settings(
        project_root=Path("."),
        data_dir=Path("."),
        ocr_backend="mock",
        extractor_backend="qwen",
        glm_ocr_base_url=None,
        glm_ocr_model="GLM-OCR",
        qwen_base_url="http://test/v1",
        qwen_model="Qwen3.5-9B",
        api_key=None,
        request_timeout=10.0,
        layout_service_url=None,
        extractor_prompt_style=style,
        sft_row_limit=row_limit,
    )


class RoutedQwen:
    """Routes calls by system prompt: native prompt vs constrained SFT prompt."""

    def __init__(self, native: str, sft: str) -> None:
        self.native = native
        self.sft = sft
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        kind = "sft" if messages[0]["content"] == SFT_SYSTEM else "native"
        self.calls.append({"kind": kind, "messages": messages, **kwargs})
        return self.sft if kind == "sft" else self.native


def doc() -> DocumentMeta:
    return DocumentMeta(doc_id="test-doc", source_path="test.md", file_name="test.md")


class SftPromptStyleTests(unittest.TestCase):
    def test_header_prompt_carries_engine_constraints(self) -> None:
        client = FakeQwen([MECH_MAPPING, MECH_ROW])
        extractor = QwenExtractor(make_settings("sft_m2"), client=client)
        output = extractor.extract(
            parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能"), doc()
        )

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["messages"][0]["content"], SFT_SYSTEM)
        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("任务：header_mapping", user_prompt)
        self.assertIn("allowed_properties", user_prompt)
        self.assertIn("allowed_elements", user_prompt)
        self.assertIn('"profile"', user_prompt)
        self.assertEqual(extractor.last_sft["header_calls"], 1)
        self.assertEqual(extractor.last_sft["row_calls"], 1)
        self.assertEqual(len(output.records), 1)
        self.assertEqual(output.records[0].properties["Rm"].value, 430.0)

    def test_row_stage_ignores_non_canonical_properties(self) -> None:
        client = FakeQwen([CHEM_MAPPING, CHEM_ROW])
        extractor = QwenExtractor(make_settings("sft_m2"), client=client)
        output = extractor.extract(parse_table(CHEM_HTML, "T1", 5, caption="表1"), doc())

        record = output.records[0]
        self.assertIn("C", record.properties)
        self.assertIn("Si", record.properties)
        # "其他元素" is not a canonical element/property: adding it produced
        # field_fp in the first heldout run, so it must be ignored.
        self.assertNotIn("其他元素", record.properties)
        self.assertEqual(extractor.last_sft["properties_added"], 0)
        self.assertEqual(len(output.evidence), 2)

    def test_sft_grade_from_condition_column_is_rejected(self) -> None:
        client = FakeQwen([MECH_MAPPING_NO_GRADE, '{"grade":"T6","properties":{}}'])
        extractor = QwenExtractor(make_settings("sft_m2"), client=client)
        table = TableGrid(
            table_id="T1",
            page_no=5,
            caption="表1 力学性能",
            n_rows=2,
            n_cols=2,
            header_rows=1,
            rows=[
                ["热处理状态", "抗拉强度Rm/MPa"],
                ["T6", "430"],
            ],
            header_paths=[["热处理状态"], ["抗拉强度Rm/MPa"]],
            profile="mechanical_properties",
            orientation="grade_rows",
        )
        document = DocumentMeta(
            doc_id="test-doc",
            source_path="GH4169.md",
            file_name="GH4169.md",
            title="GH4169 高温合金棒材",
        )
        output = extractor.extract(table, document)

        self.assertEqual(len(output.records), 1)
        # T6 is a condition, so the document grade must be used instead.
        self.assertEqual(output.records[0].grade, "GH4169")

    def test_row_stage_falls_back_on_invalid_json(self) -> None:
        client = FakeQwen([CHEM_MAPPING, "not json"])
        extractor = QwenExtractor(make_settings("sft_m2"), client=client)
        output = extractor.extract(parse_table(CHEM_HTML, "T1", 5, caption="表1"), doc())

        self.assertEqual(extractor.last_sft["row_fallbacks"], 1)
        self.assertEqual(len(output.records), 1)
        self.assertIn("C", output.records[0].properties)
        self.assertNotIn("其他元素", output.records[0].properties)

    def test_repeated_header_and_duplicate_rows_are_dropped(self) -> None:
        client = FakeQwen([CHEM_MAPPING, '{"grade":"2A14","properties":{}}'])
        extractor = QwenExtractor(make_settings("sft_m2"), client=client)
        # Artifact-style grid: continuation pages repeat the header row and the
        # previous block (as seen in GB/T 14992 T8).
        table = TableGrid(
            table_id="T1",
            page_no=5,
            caption="表1 化学成分(质量分数)/%",
            n_rows=4,
            n_cols=3,
            header_rows=1,
            rows=[
                ["牌号", "C", "Si"],
                ["2A14", "0.03", "0.35"],
                ["牌号", "C", "Si"],
                ["2A14", "0.03", "0.35"],
            ],
            header_paths=[["牌号"], ["C"], ["Si"]],
            profile="chemical_composition",
            orientation="grade_rows",
        )
        output = extractor.extract(table, doc())

        self.assertEqual(extractor.last_sft["rows_dropped"], 2)
        self.assertEqual(len(output.records), 1)
        self.assertEqual(output.records[0].grade, "2A14")

    def test_row_limit_skips_sft_row_calls(self) -> None:
        client = FakeQwen([CHEM_MAPPING])
        extractor = QwenExtractor(make_settings("sft_m2", row_limit=1), client=client)
        table = parse_table(
            "<table><tr><td>牌号</td><td>C</td></tr>"
            "<tr><td>2A14</td><td>0.03</td></tr>"
            "<tr><td>2B14</td><td>0.04</td></tr></table>",
            "T1",
            5,
            caption="表1 化学成分(质量分数)/%",
        )
        output = extractor.extract(table, doc())

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(extractor.last_sft["rows_skipped"], 2)
        self.assertEqual(len(output.records), 2)

    def test_native_style_keeps_original_mapping_prompt(self) -> None:
        client = FakeQwen([MECH_MAPPING])
        extractor = QwenExtractor(make_settings("native"), client=client)
        extractor.extract(parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能"), doc())

        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("allowed_properties", user_prompt)
        self.assertEqual(extractor.last_sft["header_calls"], 0)


class MappingVoteTests(unittest.TestCase):
    def test_vote_agreement_builds_record_without_row_calls(self) -> None:
        client = RoutedQwen(MECH_MAPPING, MECH_MAPPING)
        extractor = QwenExtractor(make_settings("vote"), client=client)
        output = extractor.extract(
            parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能"), doc()
        )

        self.assertEqual([call["kind"] for call in client.calls], ["native", "sft"])
        self.assertEqual(extractor.last_vote["agree"], 5)
        self.assertEqual(extractor.last_sft["row_calls"], 0)
        self.assertEqual(len(output.records), 1)
        self.assertEqual(output.records[0].properties["Rm"].value, 430.0)

    def test_vote_conflict_prefers_canonical_property(self) -> None:
        native = (
            '{"columns":[{"index":0,"role":"grade"},{"index":1,"role":"condition"},'
            '{"index":2,"role":"condition"},{"index":3,"role":"property","property":"Rm"},'
            '{"index":4,"role":"property","property":"试验值"}]}'
        )
        sft = (
            '{"columns":[{"index":0,"role":"grade"},{"index":1,"role":"condition"},'
            '{"index":2,"role":"condition"},{"index":3,"role":"property","property":"A"},'
            '{"index":4,"role":"property","property":"A"}]}'
        )
        client = RoutedQwen(native, sft)
        extractor = QwenExtractor(make_settings("vote"), client=client)
        output = extractor.extract(
            parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能"), doc()
        )

        self.assertEqual(extractor.last_vote["conflict"], 2)
        record = output.records[0]
        # Col 3: both canonical but disagree -> native (Rm) wins.
        self.assertEqual(record.properties["Rm"].value, 430.0)
        # Col 4: native label is not canonical, SFT's A is -> SFT wins.
        self.assertEqual(record.properties["A"].value, 10.0)

    def test_vote_grade_disagreement_falls_back_to_rules(self) -> None:
        html = (
            "<table><tr><td>牌号</td><td>热处理状态</td><td>抗拉强度Rm/MPa</td></tr>"
            "<tr><td>2A14</td><td>T6</td><td>430</td></tr></table>"
        )
        native = (
            '{"columns":[{"index":0,"role":"grade"},{"index":1,"role":"condition"},'
            '{"index":2,"role":"property","property":"Rm"}]}'
        )
        sft = (
            '{"columns":[{"index":0,"role":"condition"},{"index":1,"role":"grade"},'
            '{"index":2,"role":"property","property":"Rm"}]}'
        )
        client = RoutedQwen(native, sft)
        extractor = QwenExtractor(make_settings("vote"), client=client)
        output = extractor.extract(parse_table(html, "T1", 5, caption="表1 力学性能"), doc())

        self.assertEqual(extractor.last_vote["grade_dropped"], 2)
        self.assertEqual(len(output.records), 1)
        self.assertEqual(output.records[0].grade, "2A14")


if __name__ == "__main__":
    unittest.main()
