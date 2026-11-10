import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.contracts import Evidence, Page
from metal_doc_agent.pipeline import attach_evidence_bboxes


class EvidenceBboxTests(unittest.TestCase):
    def test_quote_and_table_blocks_are_attached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout_path = root / "layout-0001.json"
            layout_path.write_text(
                json.dumps(
                    {
                        "page_no": 1,
                        "blocks": [
                            {
                                "type": "text",
                                "bbox": [0.1, 0.2, 0.9, 0.3],
                                "text": "毛坯材料化学成份应符合 GB/T 3190 规定。",
                            },
                            {
                                "type": "table",
                                "bbox": [0.1, 0.4, 0.9, 0.8],
                                "text": "",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            page = Page(page_no=1, markdown="", layout_path=str(layout_path))
            evidence = [
                Evidence(
                    evidence_id="e1",
                    page_no=1,
                    quote="化学成份应符合 GB/T 3190",
                ),
                Evidence(
                    evidence_id="e2",
                    page_no=1,
                    table_id="T1",
                    quote="430",
                ),
                Evidence(
                    evidence_id="e3",
                    page_no=1,
                    quote="不存在的文本",
                ),
            ]

            enriched = attach_evidence_bboxes(evidence, [page])

            self.assertEqual(enriched, 2)
            self.assertEqual(evidence[0].bbox, [0.1, 0.2, 0.9, 0.3])
            self.assertEqual(evidence[1].bbox, [0.1, 0.4, 0.9, 0.8])
            self.assertIsNone(evidence[2].bbox)

    def test_existing_bbox_is_preserved(self) -> None:
        evidence = [
            Evidence(
                evidence_id="e1",
                page_no=1,
                quote="anything",
                bbox=[0.0, 0.0, 1.0, 1.0],
            )
        ]
        self.assertEqual(attach_evidence_bboxes(evidence, []), 0)
        self.assertEqual(evidence[0].bbox, [0.0, 0.0, 1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
