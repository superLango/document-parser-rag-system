"""文本型 PDF 分类与文本层填充（MinerU 借鉴，P0）。

背景：纯文本 PDF（有文本层、无大图）无需 GLM-OCR 逐块识别正文，
直接取文本层内容即可，显著降低大模型调用成本。

- classify_pdf：按字符数与图片覆盖率纯规则分类（参考 MinerU pdf_classify.py）；
- fill_text_layer_blocks：文本型 PDF 时用文本层内容填充 text/title/footnote 块，
  跳过 GLM-OCR；表格/公式/图片等仍需识别的块不受影响。
"""

from __future__ import annotations

from collections.abc import Iterable

from .types import BBox, LayoutBlock, RenderPage

# 判定阈值（参考 MinerU pdf_classify.py 简化）
SAMPLE_PAGE_LIMIT = 10        # 最多采样页数
PAGE_CHARS_THRESHOLD = 50     # 单页文本型候选的最小字符数
TEXT_PAGE_IMAGE_COVERAGE = 0.5  # 文本型候选的图片覆盖率上限
SCAN_PAGE_IMAGE_COVERAGE = 0.8  # 扫描型候选的图片覆盖率下限
TEXT_MAJORITY_RATIO = 0.5     # 文档多数页为文本型则判定为 text

# 文本层填充的块类型
TEXT_LAYER_BLOCK_TYPES = frozenset({"text", "title", "footnote", "aside_text"})
# 仍需 GLM-OCR 的块类型（表格/公式/图片说明）
OCR_REQUIRED_TYPES = frozenset(
    {"table", "formula", "image_caption", "table_caption"}
)


def _page_chars(page: RenderPage) -> int:
    return sum(len((tb.text or "").strip()) for tb in page.text_blocks)


def _page_image_coverage(page: RenderPage) -> float:
    if page.width <= 0 or page.height <= 0:
        return 0.0
    page_area = page.width * page.height
    covered = sum(
        max(0.0, box.width * box.height) for box in page.image_boxes
    )
    return min(1.0, covered / page_area)


def _classify_page(page: RenderPage) -> str:
    """单页分类：text（文本层充足且无大图）| ocr（扫描/混合）。"""
    chars = _page_chars(page)
    coverage = _page_image_coverage(page)
    if chars >= PAGE_CHARS_THRESHOLD and coverage < TEXT_PAGE_IMAGE_COVERAGE:
        return "text"
    if coverage >= SCAN_PAGE_IMAGE_COVERAGE:
        return "ocr"
    # 中间情况：有文本但图片多 → 保守走 OCR；无文本 → OCR
    return "text" if chars >= PAGE_CHARS_THRESHOLD * 3 else "ocr"


def classify_pdf(pages: Iterable[RenderPage]) -> str:
    """整篇文档分类：多数采样页为文本型 → "text"，否则 "ocr"。

    纯文本 PDF 返回 "text"，解析时跳过正文 GLM-OCR。
    """
    pages = list(pages)
    if not pages:
        return "ocr"
    sampled = pages[:SAMPLE_PAGE_LIMIT]
    text_pages = sum(1 for p in sampled if _classify_page(p) == "text")
    ratio = text_pages / len(sampled)
    return "text" if ratio >= TEXT_MAJORITY_RATIO else "ocr"


def _normalized_text_block(tb, page: RenderPage) -> tuple[BBox, str]:
    return tb.bbox.normalized(page.width, page.height), tb.text


def fill_text_layer_blocks(
    pages: list[RenderPage],
    page_layouts: list[list[LayoutBlock]],
) -> tuple[list[list[LayoutBlock]], int]:
    """用文本层内容填充 text/title/footnote 版面块（跳过 GLM-OCR）。

    匹配规则：文本层块中心点落在版面块内（或与版面块中心距离近），
    多个文本层块按阅读顺序拼接。返回（新布局, 已填充块数）。
    """
    filled = 0
    for idx, (page, blocks) in enumerate(zip(pages, page_layouts)):
        # 行内公式归并已在 pipeline 公共阶段执行（merge_inline_formula_into_text），
        # 此处仅填充文本层；独立公式区域文本仍排除（防重复）。
        text_items = [
            _normalized_text_block(tb, page) for tb in page.text_blocks
        ]
        if not text_items:
            continue
        # 独立公式区域 bbox：其文本已由 GLM-OCR 识别为 $$...$$，
        # 不能填入正文 text 块（防重复）
        formula_boxes = [
            b.bbox for b in blocks if b.type in ("formula", "equation")
        ]
        for block in blocks:
            if block.type not in TEXT_LAYER_BLOCK_TYPES:
                continue
            if block.content:
                continue  # 已有内容（如合并进表格的注行）不覆盖
            parts: list[str] = []
            for tb_bbox, text in text_items:
                cx = (tb_bbox.x0 + tb_bbox.x1) / 2
                cy = (tb_bbox.y0 + tb_bbox.y1) / 2
                inside = (
                    block.bbox.x0 <= cx <= block.bbox.x1
                    and block.bbox.y0 <= cy <= block.bbox.y1
                )
                if not inside:
                    continue
                # 跳过落在公式区域内的文本（防重复）
                in_formula = any(
                    fb.x0 <= cx <= fb.x1 and fb.y0 <= cy <= fb.y1
                    for fb in formula_boxes
                )
                if in_formula:
                    continue
                parts.append(text)
            if parts:
                block.content = " ".join(parts)
                block.source = "text"  # run_ocr_stage 对 source=text 自动跳过
                block.structural = {
                    **(block.structural or {}),
                    "ocr_source": "text-layer",
                }
                filled += 1
    return page_layouts, filled
