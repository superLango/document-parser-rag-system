"""页眉页脚擦除（U3：A/B 对比已择优，胜出方案 A 内置规则）。

方案 B（样本增强）评测结果：0.1892 < 方案 A 0.2758，已按约定移除，
实现归档于 qa/evaluation/header_footer_ab/enhanced_strategy.py 供复测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.logging import get_logger

from .types import BBox, ErasedBlock, EraseResult, RenderPage, TextBlock

logger = get_logger(__name__)

DEFAULT_PAGE_NUMBER_PATTERNS = (
    r"(?i)page\s*\d+(\s*of\s*\d+)?",
    r"第\s*[0-9一二三四五六七八九十百]+\s*页",
    r"[（(]?\d+\s*[/／]\s*\d+\s*[）)]?",
    r"(?i)page\s*-\s*\d+",
)


@dataclass(slots=True)
class EraseOptions:
    """擦除参数（方案 A 内置规则）。"""

    top_ratio: float = 0.16
    bottom_ratio: float = 0.84
    repeat_min_pages: int = 2
    position_tolerance: float = 0.04
    keep_cover_page: bool = True
    page_number_patterns: tuple[str, ...] = DEFAULT_PAGE_NUMBER_PATTERNS


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_page_number(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text) for p in patterns)


def _margin_zone(bbox: BBox, options: EraseOptions) -> str:
    if bbox.y1 <= options.top_ratio:
        return "top"
    if bbox.y0 >= options.bottom_ratio:
        return "bottom"
    return ""


def _collect_repeated_margin_texts(
    pages: list[RenderPage], options: EraseOptions
) -> dict[str, list[tuple[int, float, float]]]:
    """跨页重复的页边距文本：{规范文本: [(page_index, y_center, x_center), ...]}。"""
    hits: dict[str, list[tuple[int, float, float]]] = {}
    for page in pages:
        if options.keep_cover_page and page.page_index == 1:
            continue
        for block in page.text_blocks:
            nb = block.bbox.normalized(page.width, page.height)
            if not _margin_zone(nb, options):
                continue
            key = _norm(block.text)
            if not key:
                continue
            hits.setdefault(key, []).append(
                (page.page_index, (nb.y0 + nb.y1) / 2, (nb.x0 + nb.x1) / 2)
            )
    return {
        key: positions
        for key, positions in hits.items()
        if len({p for p, _, _ in positions}) >= options.repeat_min_pages
    }


def _erase_page(
    page: RenderPage,
    options: EraseOptions,
    repeated: dict[str, list[tuple[int, float, float]]],
) -> tuple[list[TextBlock], list[ErasedBlock]]:
    kept: list[TextBlock] = []
    erased: list[ErasedBlock] = []
    for block in page.text_blocks:
        nb = block.bbox.normalized(page.width, page.height)
        zone = _margin_zone(nb, options)
        if not zone:
            kept.append(block)
            continue
        reasons: list[str] = []
        # 页码证据（顶部/底部页边距内，正文长句含“第 X 页”属罕见场景）
        if _is_page_number(block.text, options.page_number_patterns):
            reasons.append("page_number")
        # 顶部重复文本视为页眉；底部仅接受页码证据，避免表格底行被误删
        if zone == "top" and _norm(block.text) in repeated:
            reasons.append("repeated")
        if not reasons:
            kept.append(block)
            continue
        block.erased = True
        erased.append(
            ErasedBlock(
                page_index=page.page_index,
                bbox=nb,
                text=block.text,
                reason="+".join(reasons),
                strategy="rule",
            )
        )
    return kept, erased


def apply_header_footer_erase(
    pages: list[RenderPage],
    mode: str = "rule",
    options: EraseOptions | None = None,
) -> EraseResult:
    """执行页眉页脚擦除（方案 A 内置规则，U3 胜出方案）。"""
    if mode != "rule":
        raise ValueError(
            f"未知页眉页脚擦除方案：{mode}；方案 B 已按 U3 评测移除，仅支持 rule"
        )
    opts = options or EraseOptions()
    repeated = _collect_repeated_margin_texts(pages, opts)
    kept_pages: list[list[TextBlock]] = []
    all_erased: list[ErasedBlock] = []
    for page in pages:
        kept, erased = _erase_page(page, opts, repeated)
        kept_pages.append(kept)
        all_erased.extend(erased)
    stats = {
        "mode": "rule",
        "erased_blocks": len(all_erased),
        "repeated_margin_texts": len(repeated),
        "pages": len(pages),
    }
    logger.info(
        "页眉页脚擦除完成（方案 A）",
        erased=len(all_erased),
        repeated=len(repeated),
    )
    return EraseResult(pages=kept_pages, erased=all_erased, stats=stats)
