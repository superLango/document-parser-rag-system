"""Phase 6 评测指标（U12 指标集）。

指标：
- text_similarity：OCR 与参考文本的字符级相似度（SequenceMatcher ratio）
- table_restore_ok：表格结构还原判定（HTML <table> + 内容相似度）
- match_layout_blocks：版面框检出/误检（IoU≥阈值匹配）
- page_correct：按相似度阈值判定页面是否正确
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize_text(text: str) -> str:
    """去除空白差异，统一用于比较。"""
    return re.sub(r"\s+", " ", text or "").strip()


def text_similarity(reference: str, prediction: str) -> float:
    """参考与预测文本的相似度（0..1）。"""
    ref = normalize_text(reference)
    pred = normalize_text(prediction)
    if not ref and not pred:
        return 1.0
    if not ref or not pred:
        return 0.0
    return SequenceMatcher(None, ref, pred).ratio()


def text_coverage(reference: str, prediction: str) -> float:
    """参考文本在预测文本中的字符覆盖率（LCS 长度 / 参考长度）。"""
    ref = normalize_text(reference)
    pred = normalize_text(prediction)
    if not ref:
        return 1.0
    if not pred:
        return 0.0
    sm = SequenceMatcher(None, ref, pred, autojunk=False)
    matched = sum(block.size for block in sm.get_matching_blocks())
    return matched / len(ref)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def table_restore_ok(
    ocr_content: str,
    reference: str,
    *,
    structure_threshold: float = 0.5,
    content_threshold: float = 0.5,
) -> bool:
    """表格还原判定：结构（HTML table）+ 内容相似度双达标。"""
    content = ocr_content or ""
    if not content.lower().startswith("<table"):
        return False
    # 单元格文本比较：去除全部空白后按字符序列比较（GLM-OCR 常把单元格连写）
    ref_flat = re.sub(r"\s+", "", strip_html(reference))
    pred_flat = re.sub(r"\s+", "", strip_html(content))
    sim = text_similarity(ref_flat, pred_flat)
    return sim >= content_threshold


def iou(box_a: list[float], box_b: list[float]) -> float:
    """归一化/点坐标 bbox 的 IoU。"""
    x0 = max(box_a[0], box_b[0])
    y0 = max(box_a[1], box_b[1])
    x1 = min(box_a[2], box_b[2])
    y1 = min(box_a[3], box_b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def type_group(block_type: str) -> str:
    """版面块类型分组（缓解模型与 GT 类型体系差异）。"""
    t = block_type or ""
    if t in ("title",):
        return "title"
    if t in ("table", "table_caption", "table_footnote"):
        return "table"
    if t in ("image", "image_caption", "figure", "figure_caption", "seal"):
        return "image"
    if t in ("formula", "equation", "isolate_formula"):
        return "formula"
    return "text"


def _center_in_box(center: tuple[float, float], bbox: list[float]) -> bool:
    return bbox[0] <= center[0] <= bbox[2] and bbox[1] <= center[1] <= bbox[3]


def _center_distance(center_a: tuple[float, float], center_b: tuple[float, float]) -> float:
    return max(abs(center_a[0] - center_b[0]), abs(center_a[1] - center_b[1]))


def _box_center(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def match_layout_blocks(
    ground_truth: list[dict],
    predictions: list[dict],
    *,
    iou_threshold: float = 0.5,
    consider_type: bool = True,
    match_mode: str = "iou",
    center_tolerance: float = 0.12,
) -> dict:
    """版面框匹配：返回 recall/precision/tp/fp/fn。

    match_mode：
    - "iou"：IoU ≥ iou_threshold 匹配（严格）；
    - "center"：GT/预测中心互相包含或 Chebyshev 距离 ≤ center_tolerance（宽松检出语义）。
    ground_truth/predictions 元素：{"page": int, "type": str, "bbox": [x0,y0,x1,y1]}
    """
    if not ground_truth:
        return {
            "recall": None,
            "precision": None,
            "tp": 0,
            "fp": 0,
            "fn": 0,
        }

    def _score(pred, gt) -> float:
        if match_mode == "center":
            pc = _box_center(pred["bbox"])
            gc = _box_center(gt["bbox"])
            if _center_in_box(pc, gt["bbox"]) or _center_in_box(gc, pred["bbox"]):
                return 1.0
            dist = _center_distance(pc, gc)
            if dist > center_tolerance:
                return -1.0
            return 1.0 - dist / center_tolerance
        return iou(gt["bbox"], pred["bbox"])

    threshold = 0.0 if match_mode == "center" else iou_threshold
    matched_gt: set[int] = set()
    tp = 0
    for pred in predictions:
        best_idx = -1
        best_score = threshold
        for idx, gt in enumerate(ground_truth):
            if idx in matched_gt:
                continue
            if gt.get("page") != pred.get("page"):
                continue
            if consider_type and type_group(gt.get("type", "")) != type_group(pred.get("type", "")):
                continue
            score = _score(pred, gt)
            if score >= best_score:
                best_score = score
                best_idx = idx
        if best_idx >= 0:
            matched_gt.add(best_idx)
            tp += 1
    fp = len(predictions) - tp
    fn = len(ground_truth) - tp
    return {
        "recall": tp / len(ground_truth) if ground_truth else None,
        "precision": tp / len(predictions) if predictions else None,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def page_correct(similarity: float, threshold: float = 0.85) -> bool:
    """页面正确率判定。"""
    return similarity >= threshold


def safe_rate(value: float | None) -> float:
    """None（分母为零）记 0，保证可汇总。"""
    return value if value is not None else 0.0
