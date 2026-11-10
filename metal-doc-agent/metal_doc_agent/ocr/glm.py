"""GLM-OCR adapter: PDF -> layout -> block crop -> GLM-OCR -> page Markdown."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..clients import LayoutClient, ModelServiceError, build_glm_client, build_layout_client
from ..clients.openai import GlmOcrClient
from ..contracts import Page
from ..settings import Settings
from .assemble import assemble_page_markdown
from .mock import MockOcrAdapter
from .pdf import RenderedPdfPage, crop_block, render_pdf

logger = logging.getLogger(__name__)

OCR_BLOCK_TYPES = {
    "title",
    "text",
    "table",
    "formula",
    "image_caption",
    "table_caption",
    "footnote",
    "aside_text",
}

# Titles are always OCRed: scanned GB covers often carry a broken embedded
# font encoding, and trusting the text layer produced symbol soup titles.
TEXT_LAYER_BLOCK_TYPES = {"text", "footnote", "aside_text"}
TEXT_LAYER_MIN_CHARS = 50
COMMON_CJK = set(
    "的一是不了在人有我他这中大为上个国以要他时来用们生到作地于出就分对成会可主发年动"
    "同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自"
    "二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四"
    "日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命"
    "此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入"
    "常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根"
    "论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七"
    "海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打"
    "白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话"
    "米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复"
    "容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克"
    "何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片"
    "始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严钢锈钛镍铬钼钒铝铜棒板"
    "管丝材热冷轧锻焊腐蚀耐强度伸长收缩硬"
)


def _text_layer_usable(text: str) -> bool:
    """Reject text-layer output produced from broken embedded font encodings."""

    stripped = text.strip()
    if len(stripped) < 10:
        return False
    meaningful = sum(1 for char in stripped if char.isalnum() or char.isspace())
    if meaningful / len(stripped) < 0.5:
        return False
    cjk = [char for char in stripped if "\u4e00" <= char <= "\u9fff"]
    if cjk and sum(1 for char in cjk if char in COMMON_CJK) / len(cjk) < 0.15:
        return False
    if not cjk and not re.search(r"[A-Za-z]{3,}", stripped):
        return False
    return True


class GlmOcrAdapter:
    name = "glm-ocr"

    def __init__(
        self,
        settings: Settings,
        *,
        layout_client: LayoutClient | None = None,
        glm_client: GlmOcrClient | None = None,
        dpi: int | None = None,
    ) -> None:
        self.settings = settings
        self._layout = layout_client
        self._glm = glm_client
        self.dpi = dpi or settings.ocr_dpi
        self.last_errors: list[dict] = []
        # Keep the number of in-flight OCR calls aligned with the OCR service
        # capacity; the page/block pools alone can oversubscribe it.
        self._slots = threading.BoundedSemaphore(
            max(1, int(settings.ocr_max_inflight))
        )
        # Long table generations lose responses when too many run at once, so
        # give them a small dedicated budget instead of the shared pool.
        self._table_slots = threading.BoundedSemaphore(
            max(1, int(settings.ocr_table_inflight))
        )
        # The layout service serializes inference internally; keeping one
        # request in flight avoids queuing behind a slow page.
        self._layout_lock = threading.Lock()

    def recognize(self, path: Path, out_dir: Path | None = None) -> list[Page]:
        path = Path(path)
        if path.suffix.lower() == ".md":
            return MockOcrAdapter().recognize(path, out_dir=out_dir)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"unsupported OCR input: {path.suffix}")

        page_images = self._page_dir(path, out_dir)
        page_images.mkdir(parents=True, exist_ok=True)

        owned_layout = self._layout is None
        owned_glm = self._glm is None
        if owned_layout:
            self._layout = build_layout_client(self.settings)
        if owned_glm:
            self._glm = build_glm_client(self.settings)
        assert self._layout is not None and self._glm is not None

        self.last_errors = []
        pages: list[Page] = []
        try:
            rendered_pages = list(render_pdf(path, dpi=self.dpi))
            for rendered in rendered_pages:
                image_path = page_images / f"page-{rendered.page_no:04d}.png"
                image_path.write_bytes(rendered.image_bytes)

            def process(rendered: RenderedPdfPage) -> Page:
                image_path = page_images / f"page-{rendered.page_no:04d}.png"
                page_error: str | None = None
                try:
                    markdown, blocks = self._page_content(rendered)
                except Exception as exc:  # noqa: BLE001 - keep the rest of the PDF
                    page_error = str(exc)[:300]
                    blocks = []
                    markdown = self._text_layer_markdown(rendered)
                    self.last_errors.append(
                        {
                            "page_no": rendered.page_no,
                            "block_type": "page",
                            "bbox": None,
                            "error": page_error,
                        }
                    )
                    logger.warning(
                        "page OCR failed page=%s error=%s", rendered.page_no, page_error
                    )
                layout_path = page_images / f"layout-{rendered.page_no:04d}.json"
                layout_body: dict[str, object] = {
                    "page_no": rendered.page_no,
                    "width": rendered.width,
                    "height": rendered.height,
                    "dpi": self.dpi,
                    "blocks": blocks,
                }
                if page_error:
                    layout_body["error"] = page_error
                layout_path.write_text(
                    json.dumps(layout_body, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                return Page(
                    page_no=rendered.page_no,
                    markdown=markdown,
                    image_path=str(image_path),
                    layout_path=str(layout_path),
                )

            page_workers = max(1, int(self.settings.ocr_page_concurrency))
            if page_workers > 1 and len(rendered_pages) > 1:
                with ThreadPoolExecutor(max_workers=page_workers) as pool:
                    pages = list(pool.map(process, rendered_pages))
            else:
                pages = [process(rendered) for rendered in rendered_pages]
        finally:
            if owned_layout:
                self._layout.close()
                self._layout = None
            if owned_glm:
                self._glm.close()
                self._glm = None
        return pages

    def _page_dir(self, path: Path, out_dir: Path | None) -> Path:
        if out_dir is not None:
            return Path(out_dir) / "pages"
        safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", path.stem).strip("-") or "document"
        return self.settings.data_dir / "pages" / safe

    def _text_layer_markdown(self, page: RenderedPdfPage) -> str:
        """Keep whatever text the PDF already carries when layout fails."""
        texts = [text.strip() for _, text in page.text_blocks if text.strip()]
        if not texts:
            return ""
        return assemble_page_markdown([("text", text) for text in texts])

    def _page_content(
        self, page: RenderedPdfPage
    ) -> tuple[str, list[dict]]:
        assert self._layout is not None and self._glm is not None
        with self._layout_lock:
            blocks = self._layout.analyze(
                page.image_bytes,
                page_index=page.page_no,
                dpi=self.dpi,
                width=page.width,
                height=page.height,
            )
        text_layer = page.text_blocks
        text_layer_chars = sum(len(text) for _, text in text_layer)
        use_text_layer = bool(text_layer) and text_layer_chars >= TEXT_LAYER_MIN_CHARS
        payload: list[dict] = []
        targets: list[tuple[dict, object, bytes]] = []
        for block in sorted(blocks, key=lambda item: item.order):
            entry = {
                "type": block.type,
                "bbox": [round(float(value), 3) for value in block.bbox],
                "order": block.order,
                "confidence": round(float(block.confidence), 4),
                "structural": dict(block.structural or {}),
                "text": "",
                "error": None,
            }
            if use_text_layer and block.type in TEXT_LAYER_BLOCK_TYPES:
                parts = []
                for text_bbox, text in text_layer:
                    cx = (text_bbox[0] + text_bbox[2]) / 2
                    cy = (text_bbox[1] + text_bbox[3]) / 2
                    if (
                        block.bbox[0] <= cx <= block.bbox[2]
                        and block.bbox[1] <= cy <= block.bbox[3]
                    ):
                        parts.append(text)
                if parts:
                    text = " ".join(parts)
                    if _text_layer_usable(text):
                        entry["text"] = text
                        entry["structural"]["ocr_source"] = "text-layer"
            if not entry["text"] and block.type in OCR_BLOCK_TYPES:
                try:
                    crop = crop_block(page.image_bytes, block.bbox)
                except (ValueError, OSError) as exc:
                    entry["error"] = str(exc)[:300]
                else:
                    targets.append((entry, block, crop))
            payload.append(entry)

        def recognize(target: tuple[dict, object, bytes]) -> object:
            _, block, crop = target
            started = time.monotonic()
            slots = self._table_slots if block.type == "table" else self._slots
            with slots:
                try:
                    return self._glm.ocr_image(crop, block.type)  # type: ignore[union-attr]
                except (ModelServiceError, RuntimeError, ValueError, OSError) as exc:
                    return exc
                finally:
                    elapsed = time.monotonic() - started
                    if elapsed > 30.0:
                        logger.warning(
                            "slow block OCR page=%s type=%s elapsed=%.1fs",
                            page.page_no,
                            block.type,
                            elapsed,
                        )

        block_workers = max(1, int(self.settings.ocr_block_concurrency))
        if block_workers > 1 and len(targets) > 1:
            with ThreadPoolExecutor(max_workers=block_workers) as pool:
                outcomes = list(pool.map(recognize, targets))
        else:
            outcomes = [recognize(target) for target in targets]

        for (entry, block, _), outcome in zip(targets, outcomes):
            if isinstance(outcome, Exception):
                entry["error"] = str(outcome)[:300]
                self.last_errors.append(
                    {
                        "page_no": page.page_no,
                        "block_type": block.type,
                        "bbox": block.bbox,
                        "error": str(outcome)[:300],
                    }
                )
                logger.warning(
                    "block OCR failed page=%s type=%s error=%s",
                    page.page_no,
                    block.type,
                    str(outcome)[:200],
                )
            elif outcome and str(outcome).strip():
                entry["text"] = str(outcome)

        contents = [
            (entry["type"], entry["text"])
            for entry in payload
            if entry["text"]
        ]
        return assemble_page_markdown(contents), payload
