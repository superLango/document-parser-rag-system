"""视觉归属：表格注行（footnote）合并进表格 bbox（MinerU 借鉴，P0）。

背景：PP-DocLayoutV3 将表格底部通栏说明行（"注：a、b、c"）检测为独立的
footnote/text/paragraph_title 块（内部类型 footnote/text/title），表格 bbox
不包含该行；按块裁剪 OCR 时表格输入图缺最后一行。
本模块在 OCR 之前，按"阅读顺序邻接 + 几何紧贴"将注行合并进表格 bbox，
使 GLM-OCR 一次性识别为表格最后一行。

参考：MinerU `visual_magic_model_utils.py`（is_visual_neighbor /
is_block_outside_visual_gap）的归属思路，按本项目矩形版面框简化实现。
"""

from __future__ import annotations

from collections.abc import Iterable

from .types import BBox, LayoutBlock

# 判定参数（归一化坐标，页面高 842pt 时 0.02 ≈ 17pt）
MAX_VERTICAL_GAP = 0.02       # 注行与表格底部最大间隙
MIN_X_OVERLAP = 0.7           # 注行水平跨度与表格重叠占比下限
MAX_FOOTNOTE_HEIGHT = 0.06    # 注行高度上限（单行/两行）
TEXT_STRONG_X_OVERLAP = 0.9   # text/title 类型注行的水平重叠要求（更严格）
TEXT_MAX_HEIGHT = 0.04        # text/title 类型注行高度上限（更严格）
TEXT_MIN_WIDTH_RATIO = 0.85   # text/title 通栏宽度比（注行横跨表格宽度）
FOOTNOTE_MIN_WIDTH_RATIO = 0.6  # footnote 通栏宽度比（模型已分类，放宽）
MAX_SCAN_AHEAD = 3            # 表格后最多扫描的候选块数


def _x_overlap_ratio(a: BBox, b: BBox) -> float:
    """a 的水平跨度被 b 覆盖的比例。"""
    inter = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return inter / max(a.width, 1e-6)


def _vertical_gap(table: BBox, note: BBox) -> float:
    """注行顶部与表格底部的间隙（负值表示重叠）。"""
    return note.y0 - table.y1


def _is_table_note(
    table: LayoutBlock, note: LayoutBlock, gap: float
) -> bool:
    """判定 note 是否可视为 table 的底部注行。"""
    if table.page_index != note.page_index:
        return False
    x_overlap = _x_overlap_ratio(note.bbox, table.bbox)
    height = note.bbox.height
    width_ratio = note.bbox.width / max(table.bbox.width, 1e-6)
    # 表格在页面底部时不再向下合并（避免跨页/页脚误并）
    if table.bbox.y1 >= 0.9:
        return False
    # 垂直条件：紧贴（间隙小或重叠）
    if gap > MAX_VERTICAL_GAP:
        return False
    if note.type == "footnote":
        # 模型已分类为脚注：宽松几何条件
        return (
            x_overlap >= MIN_X_OVERLAP
            and height <= MAX_FOOTNOTE_HEIGHT
            and width_ratio >= FOOTNOTE_MIN_WIDTH_RATIO
        )
    if note.type in ("text", "title"):
        # text/title 需更强证据，避免正文段落/小节标题被误并：
        # 通栏（水平重叠≥0.9 + 宽度比≥0.85）+ 单行 + 紧贴表格底部
        return (
            x_overlap >= TEXT_STRONG_X_OVERLAP
            and width_ratio >= TEXT_MIN_WIDTH_RATIO
            and height <= TEXT_MAX_HEIGHT
            and gap >= -0.005  # 不允许深重叠（正文块可能包含表格底部）
        )
    return False


def group_table_footnotes(
    page_layouts: Iterable[list[LayoutBlock]],
) -> tuple[list[list[LayoutBlock]], dict]:
    """将表格底部注行合并进表格 bbox；返回（新布局, 统计）。

    - 保持原阅读顺序；合并后注行块被移除，其 bbox 并入表格 bbox；
    - 表格 structural 记录 merged_table_footnotes 供 layout.json 调试。
    """
    result: list[list[LayoutBlock]] = []
    merged_total = 0
    for page_blocks in page_layouts:
        blocks = list(page_blocks)
        i = 0
        while i < len(blocks):
            block = blocks[i]
            if block.type != "table":
                i += 1
                continue
            # 向后扫描候选注行（阅读顺序邻接）
            j = i + 1
            scanned = 0
            merged_this_table = 0
            text_merged = False  # text/title 只合并首行，防连锁误并
            while j < len(blocks) and scanned < MAX_SCAN_AHEAD:
                cand = blocks[j]
                # 遇到非候选类型（number/image/caption 等）停止扫描；
                # title（paragraph_title/doc_title 映射）需满足强几何条件才可合并
                if cand.type not in ("footnote", "text", "title"):
                    break
                if text_merged and cand.type != "footnote":
                    break  # 已合并 text/title 注行后，不再继续并文本
                gap = _vertical_gap(block.bbox, cand.bbox)
                if _is_table_note(block, cand, gap):
                    # 合并：表格 bbox 扩展，移除注行块
                    merged_bbox = BBox(
                        min(block.bbox.x0, cand.bbox.x0),
                        min(block.bbox.y0, cand.bbox.y0),
                        max(block.bbox.x1, cand.bbox.x1),
                        max(block.bbox.y1, cand.bbox.y1),
                    )
                    block.bbox = merged_bbox
                    cand.structural = {
                        **(cand.structural or {}),
                        "group_parent": "table",
                        "merged_into_table": True,
                    }
                    merged_total += 1
                    merged_this_table += 1
                    if cand.type != "footnote":
                        text_merged = True
                    blocks.pop(j)
                    # 继续扫描下一个候选（可能有多行脚注）
                    continue
                # 注行与表格有间隙但不满足条件：视为普通内容，停止
                if gap > 0:
                    break
                scanned += 1
                j += 1
            if merged_this_table:
                merged = block.structural or {}
                merged["merged_table_footnotes"] = merged_this_table
                block.structural = merged
            i += 1
        result.append(blocks)
    return result, {"merged_table_footnotes": merged_total}


def merge_inline_formula_into_text(
    page_layouts: list[list[LayoutBlock]],
) -> tuple[list[list[LayoutBlock]], int]:
    """将同一行内与 text/title 高度重叠的 formula 块并入 text（公共阶段）。

    适用所有文档类型：文本型（正文用文本层）与 OCR 型（正文走 GLM-OCR）
    都可能出现 V3 将正文内嵌公式片段误检为独立 formula 的情况；
    若 formula 独立输出会与正文内容重复，故并入 text 由正文统一呈现。
    返回（新布局, 移除的公式块数）。
    """
    removed = 0
    result: list[list[LayoutBlock]] = []
    for blocks in page_layouts:
        kept: list[LayoutBlock] = []
        text_blocks = [b for b in blocks if b.type in ("text", "title")]
        table_boxes = [b.bbox for b in blocks if b.type == "table"]
        for block in blocks:
            if block.type not in ("formula", "equation"):
                kept.append(block)
                continue
            merged = False
            # 场景 1：正文行内的公式片段误检（与 text 同行重叠）
            for tb in text_blocks:
                inter = max(
                    0.0,
                    min(block.bbox.y1, tb.bbox.y1)
                    - max(block.bbox.y0, tb.bbox.y0),
                )
                overlap = inter / max(block.bbox.height, 1e-6)
                x_inside = (
                    block.bbox.x0 >= tb.bbox.x0 - 0.01
                    and block.bbox.x1 <= tb.bbox.x1 + 0.01
                )
                if overlap >= 0.6 and x_inside:
                    tb.structural = {
                        **(tb.structural or {}),
                        "inline_formula_merged": True,
                    }
                    merged = True
                    break
            # 场景 2：表格单元格内的数据被误检为公式（表格 OCR 已含内容）
            if not merged:
                for tb in table_boxes:
                    if (
                        block.bbox.x0 >= tb.x0 - 0.01
                        and block.bbox.x1 <= tb.x1 + 0.01
                        and block.bbox.y0 >= tb.y0 - 0.01
                        and block.bbox.y1 <= tb.y1 + 0.01
                    ):
                        block.structural = {
                            **(block.structural or {}),
                            "merged_into_table": True,
                        }
                        merged = True
                        break
            if merged:
                removed += 1
            else:
                kept.append(block)  # 独立公式保留
        result.append(kept)
    return result, removed
