from __future__ import annotations

import asyncio

from services.agent.context import HeuristicTokenizer
from services.agent.segmentation import Segmenter, merge_segment_outputs


def _table(rows: int = 30) -> dict:
    return {
        "table_id": "T1",
        "page_no": 1,
        "profile": "mechanical_properties",
        "header_paths": [["牌号"], ["抗拉强度 Rm/MPa"]],
        "units": ["MPa"],
        "rows": [["牌号", "抗拉强度 Rm/MPa"]]
        + [[f"G{index}", str(400 + index)] for index in range(rows)],
    }


def test_long_table_is_split_deterministically() -> None:
    async def scenario() -> None:
        segmenter = Segmenter(HeuristicTokenizer(), max_tokens=80)
        segments = await segmenter.segment_tables([_table()])
        assert len(segments) > 1
        assert [item.segment_id for item in segments] == [
            item.segment_id for item in segments
        ]
        assert all(item.payload["table_id"] == "T1" for item in segments)
        assert all(item.payload["header_paths"] for item in segments)

    asyncio.run(scenario())


def test_merge_is_deterministic_and_reports_conflicts() -> None:
    async def scenario() -> None:
        segmenter = Segmenter(HeuristicTokenizer(), max_tokens=80)
        segments = await segmenter.segment_tables([_table()])
        outputs = []
        for index, segment in enumerate(segments):
            outputs.append(
                {
                    "records": [
                        {
                            "record_id": f"{segment.segment_id}:R1",
                            "value": index,
                        }
                    ]
                }
            )
        first = merge_segment_outputs(segments, outputs)
        second = merge_segment_outputs(segments, outputs)
        assert first.output == second.output
        assert first.merged_items == len(segments)
        assert first.conflicts == []

        conflicting = [
            {"records": [{"record_id": "R1", "value": 1}]},
            {"records": [{"record_id": "R1", "value": 2}]},
        ]
        merged = merge_segment_outputs(segments[:2], conflicting, key_field="record_id")
        assert len(merged.conflicts) == 1
        assert merged.output["record_id"][0]["value"] == 1

    asyncio.run(scenario())
