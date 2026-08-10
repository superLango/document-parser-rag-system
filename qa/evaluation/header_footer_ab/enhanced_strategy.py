"""方案 B（样本增强）页眉页脚擦除——U3 评测败者归档。

评测结果：综合得分 0.1892 < 方案 A 0.2758，已从主线移除。
本文件仅供 A/B 复测归档使用，不参与运行时导入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class EnhancedEraseOptions:
    top_ratio: float = 0.16
    bottom_ratio: float = 0.84
    repeat_min_pages: int = 2
    use_font_ratio: bool = True
    font_ratio: float = 0.9
    max_erased_ratio: float = 0.3
    keep_cover_page: bool = True
    page_number_patterns: tuple[str, ...] = (
        r"(?i)page\s*\d+(\s*of\s*\d+)?",
        r"第\s*[0-9一二三四五六七八九十百]+\s*页",
        r"[（(]?\d+\s*[/／]\s*\d+\s*[）)]?",
    )


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_page_number(text: str, patterns) -> bool:
    return any(re.search(p, text) for p in patterns)


def _in_margin(nb, options: EnhancedEraseOptions) -> bool:
    return nb.y1 <= options.top_ratio or nb.y0 >= options.bottom_ratio


def apply_enhanced_erase(pages, options: EnhancedEraseOptions | None = None):
    """方案 B：页边距 + 跨页重复 + 页码 + 字号证据 + 防过度删除。"""
    opts = options or EnhancedEraseOptions()
    hits: dict[str, list[tuple[int, float, float]]] = {}
    for page in pages:
        if opts.keep_cover_page and page.page_index == 1:
            continue
        for block in page.text_blocks:
            nb = block.bbox.normalized(page.width, page.height)
            if not _in_margin(nb, opts):
                continue
            key = _norm(block.text)
            if key:
                hits.setdefault(key, []).append(
                    (page.page_index, (nb.y0 + nb.y1) / 2, (nb.x0 + nb.x1) / 2)
                )
    repeated = {
        key: positions
        for key, positions in hits.items()
        if len({p for p, _, _ in positions}) >= opts.repeat_min_pages
    }

    total_erased = []
    for page in pages:
        kept = []
        erased = []
        margin_count = 0
        for block in page.text_blocks:
            nb = block.bbox.normalized(page.width, page.height)
            reasons = []
            if _in_margin(nb, opts):
                margin_count += 1
                if _is_page_number(block.text, opts.page_number_patterns):
                    reasons.append("page_number")
                if _norm(block.text) in repeated:
                    reasons.append("repeated")
                if opts.use_font_ratio and block.font_size > 0:
                    body_sizes = [
                        b.font_size
                        for b in page.text_blocks
                        if not _in_margin(
                            b.bbox.normalized(page.width, page.height), opts
                        )
                        and b.font_size > 0
                    ]
                    if body_sizes and block.font_size <= max(body_sizes) * opts.font_ratio:
                        reasons.append("small_font")
            if not reasons:
                kept.append(block)
                continue
            block.erased = True
            erased.append(
                {
                    "page_index": page.page_index,
                    "text": block.text,
                    "reason": "+".join(reasons),
                }
            )
        if margin_count >= 3 and len(erased) / max(margin_count, 1) > opts.max_erased_ratio:
            strong = [
                e for e in erased if "page_number" in e["reason"] or "repeated" in e["reason"]
            ]
            if len(strong) / max(margin_count, 1) <= opts.max_erased_ratio:
                final = strong
            else:
                final = [e for e in erased if "page_number" in e["reason"]]
            final_texts = {_norm(e["text"]) for e in final}
            erased = final
            kept = [
                b
                for b in page.text_blocks
                if _norm(b.text) not in final_texts
            ]
        total_erased.extend(erased)
    return total_erased
