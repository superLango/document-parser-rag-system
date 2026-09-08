"""parsekit 阶段编排：渲染→擦除→版面→顺序→拼装（阶段 A-E）。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]

from app.core.config import settings
from app.core.logging import get_logger

from .assemble import assemble_markdown
from .errors import InvalidParseOptions
from .header_footer import EraseOptions, apply_header_footer_erase
from .layout_ppdoc import PPDocLayoutEngine
from .ocr import run_ocr_stage
from .pdf_classify import classify_pdf, fill_text_layer_blocks
from .rebuild import build_tree, mark_cross_page_tables
from .render import render_pdf
from .types import LayoutBlock, RenderPage
from .visual_grouping import group_table_footnotes, merge_inline_formula_into_text

logger = get_logger(__name__)


@dataclass(slots=True)
class ParseOptions:
    """解析参数（与配置项一一对应）。"""

    dpi: int = 200
    layout_model_dir: str = str(PROJECT_ROOT / "models" / "pp_doclayoutv3_finetuned_v2")
    layout_conf_threshold: float = 0.5
    header_footer_mode: str = "rule"
    partial_on_page_failure: bool = True
    page_concurrency: int = 4
    block_concurrency: int = 8
    title_font_threshold: float = 14.0
    image_min_area: float = 800.0
    ocr_enabled: bool = True
    ocr_failure_policy: str = "partial"  # partial | failed（U13）

    @classmethod
    def from_settings(cls) -> ParseOptions:
        return cls(
            dpi=settings.PARSEKIT_DPI,
            layout_model_dir=settings.PARSEKIT_LAYOUT_MODEL_DIR,
            layout_conf_threshold=settings.PARSEKIT_LAYOUT_CONF_THRESHOLD,
            header_footer_mode=settings.PARSEKIT_HEADER_FOOTER_MODE,
            partial_on_page_failure=settings.PARSEKIT_PARTIAL_ON_PAGE_FAILURE,
            page_concurrency=settings.PARSEKIT_PAGE_CONCURRENCY,
            block_concurrency=settings.PARSEKIT_BLOCK_CONCURRENCY,
            title_font_threshold=settings.PARSEKIT_TITLE_FONT_THRESHOLD,
            image_min_area=settings.PARSEKIT_IMAGE_MIN_AREA,
            ocr_enabled=settings.PARSEKIT_OCR_ENABLED,
            ocr_failure_policy=settings.PARSEKIT_OCR_FAILURE_POLICY,
        )


@dataclass(slots=True)
class ParseResult:
    """解析产物（Phase 2 + Phase 3 OCR）。"""

    markdown: str
    layout: dict
    pages: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    page_failures: list[dict] = field(default_factory=list)
    ocr_failures: list[dict] = field(default_factory=list)


def _validate_options(options: ParseOptions) -> None:
    if not 50 <= options.dpi <= 600:
        raise InvalidParseOptions(f"DPI 必须介于 50-600，当前 {options.dpi}")
    if not 0.01 <= options.layout_conf_threshold <= 1.0:
        raise InvalidParseOptions(
            f"版面置信度阈值必须介于 0.01-1.0，当前 {options.layout_conf_threshold}"
        )
    if options.header_footer_mode != "rule":
        raise InvalidParseOptions(
            f"未知页眉页脚方案：{options.header_footer_mode}"
            "（U3 评测后仅保留方案 A：rule）"
        )
    if options.ocr_failure_policy not in ("partial", "failed"):
        raise InvalidParseOptions(
            f"未知 OCR 失败策略：{options.ocr_failure_policy}"
            "（可选 partial|failed，U13）"
        )


def _drop_erased_overlap_blocks(
    page_layouts: list[list[LayoutBlock]],
    pages: list[RenderPage],
    erased_blocks: list,
) -> int:
    """按文本层已擦除页眉页脚区域过滤版面块（REG-18 精化）。

    仅删除与页眉页脚文本块区域重叠的版面块，避免误删顶部真实标题。
    """
    from collections import defaultdict

    by_page: dict[int, list] = defaultdict(list)
    for erased in erased_blocks:
        by_page[erased.page_index].append(erased.bbox)
    dropped = 0
    for page, blocks in zip(pages, page_layouts):
        erased_boxes = by_page.get(page.page_index, [])
        kept = []
        for block in blocks:
            overlap = False
            for box in erased_boxes:
                # 只按版面块自身被覆盖的比例决定是否删除。若反向比例也参与
                # 判定，小型重复页眉完全落在大表格内时会误删整张表格。
                if block.bbox.overlap_ratio(box) <= 0.15:
                    continue
                # 底部页脚区只删除文本类块，避免跨页表格/图片与页脚重叠被误删
                if box.y0 >= 0.84 and block.type not in (
                    "text",
                    "aside_text",
                    "footnote",
                    "header",
                    "footer",
                ):
                    continue
                overlap = True
                break
            if overlap:
                dropped += 1
                continue
            kept.append(block)
        page_layouts[page.page_index - 1] = kept
    return dropped


import threading as _threading

_ENGINE_CACHE: dict = {}
_ENGINE_LOCK = _threading.Lock()


def _get_layout_engine(options: ParseOptions):
    """版面引擎工厂：固定 PP-DocLayoutV3（唯一引擎），进程内单例缓存。

    模型权重约 133MB，每次解析重复加载既慢又占用显存；缓存后整个进程
    仅加载一次。并发安全：首次加载用双检锁，避免多任务同时加载模型
    导致 GPU 显存竞争（参考 MinerU ModelSingleton + 推理锁）。
    """
    cache_key = (options.layout_model_dir, options.layout_conf_threshold)
    if cache_key not in _ENGINE_CACHE:
        with _ENGINE_LOCK:
            if cache_key not in _ENGINE_CACHE:
                _ENGINE_CACHE[cache_key] = PPDocLayoutEngine(
                    options.layout_model_dir,
                    conf_threshold=options.layout_conf_threshold,
                )
    return _ENGINE_CACHE[cache_key]


def _apply_reading_order(page_layouts: list[list[LayoutBlock]]) -> list[list[LayoutBlock]]:
    """阅读顺序：PP-DocLayoutV3 输出已按模型内置 order_seq 排列，直接回填 order。"""
    ordered_layouts: list[list[LayoutBlock]] = []
    for blocks in page_layouts:
        ordered = list(blocks)  # 引擎输出已按阅读顺序
        for idx, block in enumerate(ordered, start=1):
            block.order = idx
        ordered_layouts.append(ordered)
    return ordered_layouts


def _build_layout_json(
    page_layouts: list[list[LayoutBlock]],
    pages: list[RenderPage],
    options: ParseOptions,
    failures: list[dict],
    ocr_failures: list[dict] | None = None,
    document_tree: dict | None = None,
    classification: str = "ocr",
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
        "schema_version": "1.2",
        "producer": "parsekit",
        "layout_engine": "ppdoclayoutv3",
        "classification": classification,
        "header_footer_mode": options.header_footer_mode,
        "page_count": len(pages),
        "pages": page_entries,
        "page_failures": failures,
        "ocr_failures": ocr_failures or [],
        "ocr": {
            "enabled": bool(options.ocr_enabled),
            "backend": "glm-ocr" if options.ocr_enabled else None,
            "failure_policy": options.ocr_failure_policy,
        },
        "rebuild": {
            "enabled": True,
            "document_tree": document_tree or {"type": "root", "children": []},
            "cross_page_tables_note": "U8：跨页表格合并暂缓，仅记录 table_cross_page 标记",
        },
    }


def parse_pdf(
    pdf_bytes: bytes,
    options: ParseOptions | None = None,
    progress: Callable[[str, int | None, int | None], None] | None = None,
) -> ParseResult:
    """执行完整解析管线，返回 Markdown + layout.json + 页面图片。"""
    opts = options or ParseOptions.from_settings()
    _validate_options(opts)
    started = time.monotonic()

    render_result = render_pdf(
        pdf_bytes,
        dpi=opts.dpi,
        partial_on_page_failure=opts.partial_on_page_failure,
        progress=progress,
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

    # 文本型 PDF 分类（MinerU 借鉴 P0）：纯文本文档跳过正文 GLM-OCR
    doc_kind = classify_pdf(pages) if opts.ocr_enabled else "ocr"

    engine = _get_layout_engine(opts)
    page_layouts = engine.analyze(pages, progress=progress)
    # DocLayout 引擎单页失败并入页面级 failures（U11）
    if hasattr(engine, "failures"):
        failures.extend(engine.failures or [])
    # 版面块按文本层已擦除区域过滤（避免页眉被 OCR 进正文，且不误删顶部标题）
    margin_dropped = _drop_erased_overlap_blocks(
        page_layouts, pages, erase_result.erased
    )

    # 视觉归属：表格底部注行合并进表格 bbox（MinerU 借鉴 P0）
    page_layouts, group_stats = group_table_footnotes(page_layouts)

    # 行内公式归并：正文行内的 formula 误检并入 text（防公式重复输出）
    page_layouts, inline_formula_removed = merge_inline_formula_into_text(
        page_layouts
    )

    ocr_failures: list[dict] = []
    text_layer_filled = 0
    if opts.ocr_enabled:
        if doc_kind == "text":
            # 文本型：text/title/footnote 用文本层填充（source=text），
            # 表格/公式/图片说明仍送 GLM-OCR
            page_layouts, text_layer_filled = fill_text_layer_blocks(
                pages, page_layouts
            )
        from app.services.ocr_backend.glmocr import get_ocr_backend

        backend = get_ocr_backend()
        page_layouts, ocr_failures = run_ocr_stage(
            pages,
            page_layouts,
            backend,
            page_concurrency=opts.page_concurrency,
            block_concurrency=opts.block_concurrency,
            progress=progress,
        )
        if ocr_failures and opts.ocr_failure_policy == "failed":
            from .errors import OcrStageError

            first = ocr_failures[0]
            raise OcrStageError(
                "GLM-OCR 块识别失败且策略为 failed（U13）："
                f"page={first.get('page_index')} type={first.get('block_type')} "
                f"error={first.get('error')}"
            )

    if progress:
        progress("rebuild")
    ordered_layouts = _apply_reading_order(page_layouts)
    all_ordered = [b for blocks in ordered_layouts for b in blocks]
    markdown = assemble_markdown(all_ordered)

    # Phase 4：U8 跨页表格标记（仅记录）+ 结构树重建（标题层级/图文关联）
    cross_page_tables = mark_cross_page_tables(ordered_layouts)
    document_tree = build_tree(all_ordered)

    layout_json = _build_layout_json(
        ordered_layouts,
        pages,
        opts,
        failures,
        ocr_failures,
        document_tree,
        classification=doc_kind,
    )
    elapsed = round(time.monotonic() - started, 3)
    stats = {
        "engine": "ppdoclayoutv3",
        "header_footer_mode": opts.header_footer_mode,
        "pages": len(pages),
        "blocks": len(all_ordered),
        "erased_blocks": len(erase_result.erased),
        "page_failures": len(failures),
        "margin_blocks_dropped": margin_dropped,
        "merged_table_footnotes": group_stats["merged_table_footnotes"],
        "inline_formula_removed": inline_formula_removed,
        "classification": doc_kind,
        "text_layer_filled": text_layer_filled,
        "skipped_ocr": text_layer_filled if doc_kind == "text" else 0,
        "ocr_blocks": sum(
            1
            for blocks in page_layouts
            for b in blocks
            if (b.structural or {}).get("ocr_source") == "glm-ocr"
        ),
        "ocr_failures": len(ocr_failures),
        "ocr_enabled": bool(opts.ocr_enabled),
        "cross_page_tables": cross_page_tables,
        "rebuild": {
            "title_count": document_tree.get("stats", {}).get("title_count", 0),
            "image_caption_links": document_tree.get("stats", {}).get("image_caption_links", 0),
            "table_caption_links": document_tree.get("stats", {}).get("table_caption_links", 0),
        },
        "elapsed_seconds": elapsed,
    }
    logger.info(
        "parsekit 解析完成",
        pages=len(pages),
        blocks=len(all_ordered),
        ocr_blocks=stats["ocr_blocks"],
        ocr_failures=len(ocr_failures),
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
        ocr_failures=ocr_failures,
    )
