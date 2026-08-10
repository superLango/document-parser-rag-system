"""阅读顺序排序（PDF-Extract-Kit 思路：按行/列分簇后排序）。"""

from __future__ import annotations

from .types import BBox, LayoutBlock


def _vertical_overlap(a: BBox, b: BBox, tolerance: float = 0.02) -> bool:
    """归一化坐标下两框是否存在显著纵向重叠（同簇）。"""
    inter = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    min_h = max(min(a.height, b.height), 1e-6)
    return inter / min_h >= 0.3 or abs((a.y0 + a.y1) / 2 - (b.y0 + b.y1) / 2) <= tolerance


def sort_reading_order(blocks: list[LayoutBlock]) -> list[LayoutBlock]:
    """按（页、纵向分簇、横向）输出阅读顺序并回填 order。"""
    sorted_blocks = sorted(
        blocks, key=lambda b: (b.page_index, b.bbox.y0, b.bbox.x0)
    )
    clusters: list[list[LayoutBlock]] = []
    for block in sorted_blocks:
        placed = False
        for cluster in reversed(clusters):
            if not cluster or cluster[0].page_index != block.page_index:
                continue
            if _vertical_overlap(cluster[0].bbox, block.bbox):
                cluster.append(block)
                placed = True
                break
        if not placed:
            clusters.append([block])

    ordered: list[LayoutBlock] = []
    for cluster in clusters:
        cluster.sort(key=lambda b: (b.bbox.x0, b.bbox.y0))
        ordered.extend(cluster)
    for idx, block in enumerate(ordered, start=1):
        block.order = idx
    return ordered
