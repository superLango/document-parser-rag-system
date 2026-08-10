"""parsekit 阶段编排：渲染→擦除→版面→顺序→拼装（阶段 A-E）。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logging import get_logger

from .assemble import assemble_markdown
from .errors import InvalidParseOptions
from .header_footer import EraseOptions, apply_header_footer_erase
from .layout import DocLayoutEngine, RuleLayoutEngine
from .reading_order import sort_reading_order
from .render import render_pdf
from .types import LayoutBlock, RenderPage

logger = get_logger(__name__)


@dataclass(slots=True)
class ParseOptions:
    """解析参数（与配置项一一对应）。"""

    dpi: int = 200
    layout_engine: str = "rule"
    layout_model_dir: str = "./models/doclayout_yolo"
    header_footer_mode: str = "rule"
    partial_on_page_failure: bool = True
    page_concurrency: int = 4
    block_concurrency: int = 8
    title_font_threshold: float = 14.0
    image_min_area: float = 800.0

    @classmethod
    def from_settings(cls) -> "ParseOptions":
        return cls(
            dpi=settings.PARSEKIT_DPI,
            layout_engine=settings.PARSEKIT_LAYOUT_ENGINE,
            layout_model_dir=settings.PARSEKIT_LAYOUT_MODEL_DIR,
            header_footer_mode=settings.PARSEKIT_HEADER_FOOTER_MODE,
            partial_on_page_failure=settings.PARSEKIT_PARTIAL_ON_PAGE_FAILURE,
            page_concurrency=settings.PARSEKIT_PAGE_CONCURRENCY,
            block_concurrency=settings.PARSEKIT_BLOCK_CONCURRENCY,
            title_font_threshold=settings.PARSEKIT_TITLE_FONT_THRESHOLD,
            image_min_area=settings.PARSEKIT_IMAGE_MIN_AREA,
        )


@dataclass(slots=True)
class ParseResult:
    """解析产物（Phase 2）。"""

    markdown: str
    layout: dict
    pages: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    page_failures: list[dict] = field(default_factory=list)


def _validate_options(options: ParseOptions) -> None:
    if not 50 <= options.dpi <= 600:
        raise InvalidParseOptions(f"DPI 必须介于 50-600，当前 {options.dpi}")
    if options.layout_engine not in ("rule", "doclayout"):
        raise InvalidParseOptions(
            f"未知版面引擎：{options.layout_engine}（可选 rule|doclayout）"
        )
    if options.header_footer_mode != "rule":
        raise InvalidParseOptions(
            f"未知页眉页脚方案：{options.header_footer_mode}"
            "（U3 评测后仅保留方案 A：rule）"
        )


def _get_layout_engine(options: ParseOptions):
    if options.layout_engine == "doclayout":
        return DocLayoutEngine(options.layout_model_dir)
    return RuleLayoutEngine(
        title_font_threshold=options.title_font_threshold,
        image_min_area=options.image_min_area,
    )


def _build_layout_json(
    page_layouts: list[list[LayoutBlock]],
    pages: list[RenderPage],
    options: ParseOptions,
    failures: list[dict],
) -> dict:
    """layout.json 契约（U9：path/title/type/structural 预留）。"""
    page_entries = []
    for idx, page in enumerate(pages):
        blocks = page_layouts[idx] if idx < len(page_layouts) else []
        page_entries.append(
            {
                "page_index": page.page_index,
                "path": f"pages/page-{page.page_index:04d}.png",
                "title": None,
                "type": "page",
                "structural": {
                    "width_pt": round(page.width, 2),
                    "height_pt": round(page.height, 2),
                    "dpi": options.dpi,
                },
                "blocks": [
                    {
                        "type": b.type,
                        "bbox": b.bbox.as_list(),
                        "order": b.order,
                        "confidence": b.confidence,
                        "content": b.content,
                        "path": b.path,
                        "title": b.title,
                        "structural": b.structural,
                    }
                    for b in blocks
                ],
            }
        )
    return {
        "schema_version": "1.0",
        "producer": "parsekit",
        "layout_engine": options.layout_engine,
        "header_footer_mode": options.header_footer_mode,
        "page_count": len(pages),
        "pages": page_entries,
        "page_failures": failures,
    }


def parse_pdf(
    pdf_bytes: bytes,
    options: ParseOptions | None = None,
) -> ParseResult:
    """执行完整解析管线，返回 Markdown + layout.json + 页面图片。"""
    opts = options or ParseOptions.from_settings()
    _validate_options(opts)
    started = time.monotonic()

    render_result = render_pdf(
        pdf_bytes,
        dpi=opts.dpi,
        partial_on_page_failure=opts.partial_on_page_failure,
    )
    pages = render_result.pages
    failures = list(render_result.failures)

    erase_result = apply_header_footer_erase(
        pages,
        mode=opts.header_footer_mode,
        options=EraseOptions(),
    )
    for page, kept in zip(pages, erase_result.pages):
        page.text_blocks = kept

    engine = _get_layout_engine(opts)
    page_layouts = engine.analyze(pages)
    ordered_layouts = [sort_reading_order(blocks) for blocks in page_layouts]
    all_ordered = [b for blocks in ordered_layouts for b in blocks]
    markdown = assemble_markdown(all_ordered)

    layout_json = _build_layout_json(
        ordered_layouts, pages, opts, failures
    )
    elapsed = round(time.monotonic() - started, 3)
    stats = {
        "engine": opts.layout_engine,
        "header_footer_mode": opts.header_footer_mode,
        "pages": len(pages),
        "blocks": len(all_ordered),
        "erased_blocks": len(erase_result.erased),
        "page_failures": len(failures),
        "elapsed_seconds": elapsed,
    }
    logger.info(
        "parsekit 解析完成",
        pages=len(pages),
        blocks=len(all_ordered),
        elapsed=elapsed,
    )
    return ParseResult(
        markdown=markdown,
        layout=layout_json,
        pages=[
            {
                "path": f"pages/page-{p.page_index:04d}.png",
                "page_index": p.page_index,
                "width": p.width,
                "height": p.height,
                "image_bytes": p.image_bytes,
            }
            for p in pages
        ],
        stats=stats,
        page_failures=failures,
    )
