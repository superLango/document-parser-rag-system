"""L1 单元测试：文本型 PDF 分类与文本层填充（MinerU 借鉴 P0）。"""

import pymupdf

from app.services.parsekit.pdf_classify import (
    classify_pdf,
    fill_text_layer_blocks,
)
from app.services.parsekit.render import render_pdf
from app.services.parsekit.types import BBox, LayoutBlock


def _png_bytes():
    """生成最小有效 PNG。"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _make_pdf(text_lines=None, image=False):
    """生成合成 PDF：text_lines 为文本行列表；image=True 插入大图。"""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    if image:
        page.insert_image(pymupdf.Rect(50, 100, 545, 800), stream=_png_bytes())
    for i, line in enumerate(text_lines or []):
        page.insert_text((72, 80 + i * 24), line, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


# ---------- 分类 ----------

def test_classify_pure_text_pdf():
    """纯文本 PDF（多行文字、无大图）→ text。"""
    data = _make_pdf([f"line {i} content here" for i in range(20)])
    pages = render_pdf(data, dpi=100).pages
    assert classify_pdf(pages) == "text"


def test_classify_scanned_pdf():
    """扫描型 PDF（无文本、大图覆盖）→ ocr。"""
    data = _make_pdf([], image=True)
    pages = render_pdf(data, dpi=100).pages
    assert classify_pdf(pages) == "ocr"


def test_classify_mixed_pdf():
    """混合型（文本+大图）→ 图片覆盖率超阈值时 ocr。"""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "some text content here", fontsize=12)
    # 半页大图
    page.insert_image(pymupdf.Rect(50, 200, 545, 800), stream=_png_bytes())
    data = doc.tobytes()
    pages = render_pdf(data, dpi=100).pages
    assert classify_pdf(pages) == "ocr"


def test_classify_empty_pages():
    """无页面 → ocr（安全默认）。"""
    assert classify_pdf([]) == "ocr"


# ---------- 文本层填充 ----------

def _page_with_text_layout():
    from app.services.parsekit.types import RenderPage, TextBlock

    page = RenderPage(
        page_index=1,
        width=595.0,
        height=842.0,
        image_bytes=_png_bytes(),
        text_blocks=[
            TextBlock(text="line zero content", bbox=BBox(60, 80, 500, 100)),
            TextBlock(text="line one content", bbox=BBox(60, 104, 500, 124)),
        ],
    )
    blocks = [
        LayoutBlock(
            type="text",
            bbox=BBox(0.1, 0.08, 0.9, 0.12),
            page_index=1,
            source="ppdoclayoutv3",
        ),
        LayoutBlock(
            type="title",
            bbox=BBox(0.1, 0.12, 0.9, 0.16),
            page_index=1,
            source="ppdoclayoutv3",
        ),
    ]
    return [page], blocks


def test_fill_text_layer_content():
    """文本层块内容填充到版面块，source 变为 text。"""
    pages, blocks = _page_with_text_layout()
    out, filled = fill_text_layer_blocks(pages, [blocks])
    assert filled == 2
    assert out[0][0].content
    assert out[0][0].source == "text"
    assert out[0][0].structural["ocr_source"] == "text-layer"


def test_fill_skips_table_blocks():
    """表格块不填充文本层（仍需 GLM-OCR）。"""
    from app.services.parsekit.types import RenderPage, TextBlock

    pages = [
        RenderPage(
            page_index=1,
            width=595.0,
            height=842.0,
            image_bytes=_png_bytes(),
            text_blocks=[
                TextBlock(text="line zero", bbox=BBox(60, 80, 500, 100))
            ],
        )
    ]
    blocks = [
        LayoutBlock(
            type="table",
            bbox=BBox(0.1, 0.05, 0.9, 0.2),
            page_index=1,
            source="ppdoclayoutv3",
        )
    ]
    out, filled = fill_text_layer_blocks(pages, [blocks])
    assert filled == 0
    assert out[0][0].content == ""
    assert out[0][0].source == "ppdoclayoutv3"


def test_fill_preserves_existing_content():
    """已有内容的块（如表格合并注行）不被覆盖。"""
    from app.services.parsekit.types import RenderPage, TextBlock

    pages = [
        RenderPage(
            page_index=1,
            width=595.0,
            height=842.0,
            image_bytes=_png_bytes(),
            text_blocks=[
                TextBlock(text="line zero", bbox=BBox(60, 80, 500, 100))
            ],
        )
    ]
    blocks = [
        LayoutBlock(
            type="text",
            bbox=BBox(0.1, 0.05, 0.9, 0.2),
            page_index=1,
            content="已有内容",
            source="ppdoclayoutv3",
        )
    ]
    out, filled = fill_text_layer_blocks(pages, [blocks])
    assert filled == 0
    assert out[0][0].content == "已有内容"


# ---------- pipeline 集成 ----------

def test_pipeline_text_pdf_skips_ocr(monkeypatch):
    """纯文本 PDF 全链路：classification=text、GLM-OCR 零调用。"""
    import app.services.ocr_backend.glmocr as glmocr_mod
    from app.services.parsekit import ParseOptions, parse_pdf

    calls = {"n": 0}

    class _Backend:
        def ocr_block_sync(self, *a, **kw):
            calls["n"] += 1
            return "should not be called"

    monkeypatch.setattr(glmocr_mod, "get_ocr_backend", lambda: _Backend())
    data = _make_pdf([f"plain line {i} for testing" for i in range(15)])
    r = parse_pdf(data, options=ParseOptions(dpi=100, ocr_enabled=True))
    assert r.stats["classification"] == "text"
    assert r.stats["text_layer_filled"] > 0
    assert r.stats["ocr_blocks"] == 0
    assert calls["n"] == 0, "纯文本 PDF 不应调用 GLM-OCR"
    assert "plain line 0" in r.markdown


# ---------- 行内公式归并（防重复） ----------

def test_inline_formula_merged_into_text():
    """与 text 同行的 formula 块被移除，text 保留文本层输出。"""
    from app.services.parsekit.visual_grouping import merge_inline_formula_into_text

    text = LayoutBlock(
        type="text",
        bbox=BBox(0.1, 0.5, 0.9, 0.52),
        page_index=1,
        source="ppdoclayoutv3",
    )
    inline_formula = LayoutBlock(
        type="formula",
        bbox=BBox(0.3, 0.5, 0.45, 0.52),  # 与 text 同一行
        page_index=1,
        source="ppdoclayoutv3",
    )
    kept, removed = merge_inline_formula_into_text([[text, inline_formula]])
    assert removed == 1
    assert len(kept[0]) == 1
    assert kept[0][0].type == "text"
    assert kept[0][0].structural["inline_formula_merged"] is True


def test_independent_formula_kept():
    """独立公式（不与 text 重叠）保留，仍走 GLM-OCR。"""
    from app.services.parsekit.visual_grouping import merge_inline_formula_into_text

    text = LayoutBlock(
        type="text",
        bbox=BBox(0.1, 0.5, 0.9, 0.52),
        page_index=1,
        source="ppdoclayoutv3",
    )
    formula = LayoutBlock(
        type="formula",
        bbox=BBox(0.1, 0.6, 0.4, 0.66),  # 独立一行
        page_index=1,
        source="ppdoclayoutv3",
    )
    kept, removed = merge_inline_formula_into_text([[text, formula]])
    assert removed == 0
    assert len(kept[0]) == 2
    assert kept[0][1].type == "formula"


def test_fill_text_layer_excludes_formula_region():
    """文本层填充排除独立公式区域（防重复）；归并由公共阶段处理。"""
    from app.services.parsekit.pdf_classify import fill_text_layer_blocks
    from app.services.parsekit.types import RenderPage, TextBlock

    page = RenderPage(
        page_index=1,
        width=595.0,
        height=842.0,
        image_bytes=_png_bytes(),
        text_blocks=[
            TextBlock(text="正文段落", bbox=BBox(60, 80, 500, 100)),
            TextBlock(text="公式原文", bbox=BBox(60, 120, 200, 140)),
        ],
    )
    blocks = [
        LayoutBlock(
            type="text",
            bbox=BBox(0.1, 0.09, 0.9, 0.12),
            page_index=1,
            source="ppdoclayoutv3",
        ),
        LayoutBlock(
            type="formula",
            bbox=BBox(0.1, 0.14, 0.4, 0.17),  # 独立公式
            page_index=1,
            source="ppdoclayoutv3",
        ),
    ]
    layouts, filled = fill_text_layer_blocks([page], [blocks])
    assert filled == 1
    # 正文块填充；公式区文本不进入正文块
    assert "正文段落" in layouts[0][0].content
    assert "公式原文" not in layouts[0][0].content
