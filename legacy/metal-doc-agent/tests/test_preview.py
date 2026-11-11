import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.preview import (
    build_preview,
    load_layout,
    normalize_bbox,
    page_image_path,
)


class PreviewTests(unittest.TestCase):
    def test_build_preview_with_image_and_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages = root / "pages"
            pages.mkdir()
            (pages / "page-0001.png").write_bytes(b"png")
            (pages / "layout-0001.json").write_text(
                json.dumps(
                    {
                        "page_no": 1,
                        "width": 1000,
                        "height": 2000,
                        "blocks": [
                            {
                                "type": "text",
                                "bbox": [100, 200, 500, 400],
                                "order": 1,
                                "confidence": 0.9,
                                "text": "hello",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "pages.json").write_text(
                json.dumps(
                    [
                        {
                            "page_no": 1,
                            "markdown": "# hello",
                            "image_path": str(pages / "page-0001.png"),
                        }
                    ]
                ),
                encoding="utf-8",
            )

            preview = build_preview(root, "doc-1")
            self.assertEqual(preview["doc_id"], "doc-1")
            self.assertEqual(preview["page_count"], 1)
            self.assertEqual(preview["pages"][0]["image"], "pages/page-0001.png")
            self.assertEqual(preview["pages"][0]["layout"], "pages/layout-0001.json")

            layout = load_layout(root, 1)
            self.assertEqual(layout["blocks"][0]["bbox"], [0.1, 0.1, 0.5, 0.2])
            self.assertEqual(layout["blocks"][0]["text"], "hello")

            image = page_image_path(root, 1)
            self.assertIsNotNone(image)
            self.assertEqual(image.name, "page-0001.png")

    def test_markdown_page_has_no_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pages.json").write_text(
                json.dumps([{"page_no": 1, "markdown": "text only"}]),
                encoding="utf-8",
            )
            preview = build_preview(root)
            self.assertIsNone(preview["pages"][0]["image"])
            self.assertIsNone(preview["pages"][0]["layout"])
            self.assertIsNone(page_image_path(root, 1))

    def test_normalize_bbox(self) -> None:
        self.assertEqual(normalize_bbox([0.1, 0.2, 0.3, 0.4], 100, 200), [0.1, 0.2, 0.3, 0.4])
        self.assertEqual(
            normalize_bbox([10, 20, 30, 40], 100, 200),
            [0.1, 0.1, 0.3, 0.2],
        )
        self.assertEqual(normalize_bbox(None, None, None), [0.0, 0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
