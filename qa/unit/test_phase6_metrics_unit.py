"""L1 单元测试：Phase 6 评测指标（M22）。"""

from qa.evaluation.metrics import (
    iou,
    match_layout_blocks,
    page_correct,
    table_restore_ok,
    text_coverage,
    text_similarity,
    type_group,
)


# ---------- L1M22-01 文本相似度 ----------
async def test_text_similarity():
    assert text_similarity("abc", "abc") == 1.0
    assert text_similarity("abc", "xyz") == 0.0
    assert text_similarity("", "") == 1.0
    assert text_similarity("a  b", "a b") == 1.0  # 多余空白归一化
    assert 0.0 < text_similarity("abcd", "abce") < 1.0


# ---------- L1M22-02 字符覆盖率 ----------
async def test_text_coverage():
    assert text_coverage("江苏合盛 内部文件", "江苏合盛 内部文件 第 1 页") == 1.0
    assert text_coverage("abcd", "ab") == 0.5
    assert text_coverage("abcd", "") == 0.0
    assert text_coverage("", "x") == 1.0


# ---------- L1M22-03 表格还原判定 ----------
async def test_table_restore_ok():
    assert table_restore_ok("<table><tr><td>A1</td></tr></table>", "A1")
    # 单元格连写（GLM-OCR 常见）也应判定还原
    assert table_restore_ok("<table><tr><td>A1</td><td>B1</td></tr></table>", "A1\tB1")
    assert not table_restore_ok("纯文本表格", "A1")
    assert not table_restore_ok("<table></table>", "完全不同的内容 XYZ")


# ---------- L1M22-04 IoU ----------
async def test_iou():
    assert iou([0, 0, 1, 1], [0, 0, 1, 1]) == 1.0
    assert iou([0, 0, 1, 1], [1, 1, 2, 2]) == 0.0
    assert iou([0, 0, 1, 1], [0.5, 0, 1.5, 1]) > 0.3
    assert iou([0, 0, 0, 0], [0, 0, 1, 1]) == 0.0


# ---------- L1M22-05 版面匹配（iou 模式） ----------
async def test_match_layout_iou():
    gt = [
        {"page": 1, "type": "title", "bbox": [0.1, 0.1, 0.5, 0.2]},
        {"page": 1, "type": "text", "bbox": [0.1, 0.3, 0.5, 0.4]},
    ]
    pred = [
        {"page": 1, "type": "title", "bbox": [0.11, 0.11, 0.51, 0.21]},
        {"page": 1, "type": "text", "bbox": [0.1, 0.3, 0.5, 0.4]},
        {"page": 1, "type": "table", "bbox": [0.7, 0.7, 0.9, 0.9]},
    ]
    m = match_layout_blocks(gt, pred, match_mode="iou", iou_threshold=0.5)
    assert m["tp"] == 2
    assert m["fp"] == 1
    assert m["fn"] == 0
    assert m["recall"] == 1.0
    assert m["precision"] == 0.6666666666666666


# ---------- L1M22-06 版面匹配（center + 类型分组） ----------
async def test_match_layout_center_and_group():
    gt = [{"page": 1, "type": "table_caption", "bbox": [0.1, 0.1, 0.5, 0.15]}]
    pred = [{"page": 1, "type": "table", "bbox": [0.12, 0.1, 0.52, 0.16]}]
    assert match_layout_blocks(gt, pred, match_mode="center")["tp"] == 1
    assert type_group("table_caption") == type_group("table")
    assert type_group("image_caption") == type_group("image")
    assert type_group("footnote") == type_group("text")
    assert type_group("title") == "title"


# ---------- L1M22-07 分母为零 ----------
async def test_empty_ground_truth():
    m = match_layout_blocks([], [{"page": 1, "type": "text", "bbox": [0, 0, 1, 1]}])
    assert m["recall"] is None
    assert m["precision"] is None


# ---------- L1M22-08 页面正确判定 ----------
async def test_page_correct():
    assert page_correct(0.9) is True
    assert page_correct(0.8, threshold=0.85) is False
