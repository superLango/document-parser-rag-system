"""Tests for PDF page assembly and the GLM-OCR adapter orchestration."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from metal_doc_agent.clients.layout import LayoutBlock
from metal_doc_agent.ocr.assemble import assemble_page_markdown
from metal_doc_agent.ocr.glm import GlmOcrAdapter
from metal_doc_agent.ocr.pdf import RenderedPdfPage, crop_block, render_pdf
from metal_doc_agent.settings import Settings


def white_png(width: int = 100, height: int = 100) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeLayoutClient:
    def __init__(self, blocks: list[LayoutBlock]) -> None:
        self.blocks = blocks
        self.calls: list[dict] = []

    def analyze(self, image_bytes: bytes, **kwargs) -> list[LayoutBlock]:
        self.calls.append(kwargs)
        return self.blocks

    def close(self) -> None:
        pass


class FakeGlmClient:
    def __init__(self) -> None:
        self.types: list[str] = []

    def ocr_image(self, image_bytes: bytes, block_type: str, **kwargs) -> str:
        self.types.append(block_type)
        return {
            "title": "材料标准",
            "text": "正文内容",
            "table": "<table><tr><td>2A14</td></tr></table>",
            "table_caption": "表1 化学成分",
        }.get(block_type, "")

    def close(self) -> None:
        pass


class AssembleTests(unittest.TestCase):
    def test_markdown_format(self) -> None:
        markdown = assemble_page_markdown(
            [
                ("title", "材料标准"),
                ("text", "正文"),
                ("table_caption", "表1 化学成分"),
                ("table", "<table><tr><td>430</td></tr></table>"),
                ("formula", r"\sigma_b"),
                ("footnote", "注：a"),
                ("image", "ignored"),
            ]
        )
        self.assertIn("## 材料标准", markdown)
        self.assertIn("<table>", markdown)
        self.assertIn("$$\n\\sigma_b\n$$", markdown)
        self.assertIn("> 注：a", markdown)
        self.assertNotIn("ignored", markdown)

    def test_crop_block(self) -> None:
        cropped = crop_block(white_png(100, 100), (0.1, 0.2, 0.5, 0.6))
        image = Image.open(io.BytesIO(cropped))
        self.assertEqual(image.size, (40, 40))

    def test_crop_rejects_tiny_block(self) -> None:
        with self.assertRaises(ValueError):
            crop_block(white_png(100, 100), (0.5, 0.5, 0.5001, 0.5001))


class AdapterTests(unittest.TestCase):
    def test_glm_adapter_orchestration(self) -> None:
        page = RenderedPdfPage(
            page_no=1, width=100.0, height=100.0, image_bytes=white_png()
        )
        layout = FakeLayoutClient(
            [
                LayoutBlock("title", (0.0, 0.0, 1.0, 0.1), 1, 0.99),
                LayoutBlock("text", (0.0, 0.1, 1.0, 0.3), 2, 0.99),
                LayoutBlock("table", (0.0, 0.3, 1.0, 0.7), 3, 0.99),
                LayoutBlock("image", (0.0, 0.7, 1.0, 1.0), 4, 0.99),
            ]
        )
        glm = FakeGlmClient()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                project_root=Path(tmp),
                data_dir=Path(tmp),
                ocr_backend="glm",
                extractor_backend="mock",
                glm_ocr_base_url="http://test",
                glm_ocr_model="GLM-OCR",
                qwen_base_url=None,
                qwen_model="Qwen3.5-9B",
                api_key=None,
                request_timeout=10.0,
                layout_service_url="http://test",
            )
            adapter = GlmOcrAdapter(
                settings, layout_client=layout, glm_client=glm, dpi=200
            )
            with patch("metal_doc_agent.ocr.glm.render_pdf", return_value=[page]):
                pages = adapter.recognize(Path("fake.pdf"), out_dir=Path(tmp))

            self.assertEqual(len(pages), 1)
            self.assertIn("## 材料标准", pages[0].markdown)
            self.assertIn("<table>", pages[0].markdown)
            self.assertNotIn("ignored", pages[0].markdown)
            self.assertEqual(glm.types, ["title", "text", "table"])
            self.assertTrue(Path(pages[0].image_path or "").exists())
            self.assertEqual(adapter.last_errors, [])

    def test_ocr_inflight_is_capped(self) -> None:
        import threading
        import time

        class SlowGlmClient(FakeGlmClient):
            def __init__(self) -> None:
                super().__init__()
                self.active = 0
                self.peak = 0
                self._lock = threading.Lock()

            def ocr_image(self, image_bytes: bytes, block_type: str, **kwargs) -> str:
                with self._lock:
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                try:
                    time.sleep(0.05)
                    return super().ocr_image(image_bytes, block_type, **kwargs)
                finally:
                    with self._lock:
                        self.active -= 1

        page = RenderedPdfPage(
            page_no=1, width=100.0, height=100.0, image_bytes=white_png()
        )
        blocks = [
            LayoutBlock("table", (0.0, index / 10, 1.0, (index + 1) / 10), index, 0.99)
            for index in range(8)
        ]
        layout = FakeLayoutClient(blocks)
        glm = SlowGlmClient()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                project_root=Path(tmp),
                data_dir=Path(tmp),
                ocr_backend="glm",
                extractor_backend="mock",
                glm_ocr_base_url="http://test",
                glm_ocr_model="GLM-OCR",
                qwen_base_url=None,
                qwen_model="Qwen3.5-9B",
                api_key=None,
                request_timeout=10.0,
                layout_service_url="http://test",
                ocr_page_concurrency=2,
                ocr_block_concurrency=8,
                ocr_max_inflight=8,
                ocr_table_inflight=1,
            )
            adapter = GlmOcrAdapter(
                settings, layout_client=layout, glm_client=glm, dpi=200
            )
            with patch("metal_doc_agent.ocr.glm.render_pdf", return_value=[page]):
                adapter.recognize(Path("fake.pdf"), out_dir=Path(tmp))
        self.assertEqual(glm.peak, 1)
        self.assertEqual(len(glm.types), 8)

    def test_layout_failure_keeps_page(self) -> None:
        import json

        from metal_doc_agent.clients import ModelServiceError

        class FailingLayoutClient:
            def analyze(self, image_bytes: bytes, **kwargs) -> list[LayoutBlock]:
                raise ModelServiceError("layout", "request failed: timed out")

            def close(self) -> None:
                pass

        page = RenderedPdfPage(
            page_no=1,
            width=100.0,
            height=100.0,
            image_bytes=white_png(),
            text_blocks=(((0.0, 0.0, 1.0, 0.3), "文本层内容保留"),),
        )
        glm = FakeGlmClient()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                project_root=Path(tmp),
                data_dir=Path(tmp),
                ocr_backend="glm",
                extractor_backend="mock",
                glm_ocr_base_url="http://test",
                glm_ocr_model="GLM-OCR",
                qwen_base_url=None,
                qwen_model="Qwen3.5-9B",
                api_key=None,
                request_timeout=10.0,
                layout_service_url="http://test",
            )
            adapter = GlmOcrAdapter(
                settings, layout_client=FailingLayoutClient(), glm_client=glm, dpi=200
            )
            with patch("metal_doc_agent.ocr.glm.render_pdf", return_value=[page]):
                pages = adapter.recognize(Path("fake.pdf"), out_dir=Path(tmp))

            self.assertEqual(len(pages), 1)
            self.assertIn("文本层内容保留", pages[0].markdown)
            self.assertEqual(glm.types, [])
            self.assertEqual(adapter.last_errors[0]["block_type"], "page")
            layout_path = Path(tmp) / "pages" / "layout-0001.json"
            body = json.loads(layout_path.read_text(encoding="utf-8"))
            self.assertEqual(body["blocks"], [])
            self.assertIn("timed out", body["error"])

    def test_text_layer_skips_text_blocks(self) -> None:
        page = RenderedPdfPage(
            page_no=1,
            width=100.0,
            height=100.0,
            image_bytes=white_png(),
            text_blocks=(
                ((0.0, 0.0, 1.0, 0.1), "材料标准（文本层）标题文字用于覆盖标题块"),
                ((0.0, 0.1, 1.0, 0.3), "正文内容（文本层）段落文字用于覆盖正文块并满足文本层阈值，补充测试字符"),
            ),
        )
        layout = FakeLayoutClient(
            [
                LayoutBlock("title", (0.0, 0.0, 1.0, 0.1), 1, 0.99),
                LayoutBlock("text", (0.0, 0.1, 1.0, 0.3), 2, 0.99),
                LayoutBlock("table", (0.0, 0.3, 1.0, 0.7), 3, 0.99),
            ]
        )
        glm = FakeGlmClient()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                project_root=Path(tmp),
                data_dir=Path(tmp),
                ocr_backend="glm",
                extractor_backend="mock",
                glm_ocr_base_url="http://test",
                glm_ocr_model="GLM-OCR",
                qwen_base_url=None,
                qwen_model="Qwen3.5-9B",
                api_key=None,
                request_timeout=10.0,
                layout_service_url="http://test",
            )
            adapter = GlmOcrAdapter(
                settings, layout_client=layout, glm_client=glm, dpi=200
            )
            with patch("metal_doc_agent.ocr.glm.render_pdf", return_value=[page]):
                pages = adapter.recognize(Path("fake.pdf"), out_dir=Path(tmp))
        # Titles are OCRed even when a text layer exists (broken GB covers),
        # while body text still reuses the text layer.
        self.assertIn("材料标准", pages[0].markdown)
        self.assertIn("正文内容（文本层）", pages[0].markdown)
        self.assertEqual(glm.types, ["title", "table"])
        self.assertEqual(adapter.last_errors, [])


class PdfTests(unittest.TestCase):
    def test_render_pdf(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = pymupdf.open()
            doc.new_page(width=200, height=300)
            doc.save(path)
            doc.close()
            pages = render_pdf(path, dpi=100)
            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0].page_no, 1)
            self.assertTrue(pages[0].image_bytes.startswith(b"\x89PNG"))


class TextLayerQualityTests(unittest.TestCase):
    def test_garbled_text_layer_is_rejected(self) -> None:
        from metal_doc_agent.ocr.glm import _text_layer_usable

        self.assertTrue(
            _text_layer_usable("本标准规定了不锈钢棒的尺寸、外形和技术要求")
        )
        self.assertFalse(_text_layer_usable("犠狉狅狌犵犺狋狋犻狋犪狀犻狌犿"))
        self.assertFalse(_text_layer_usable("! \" # $ % & ’ ’ ( ) * + , -"))


if __name__ == "__main__":
    unittest.main()
