from typing import ClassVar

"""L1 单元测试：parsekit 渲染/擦除/版面/顺序/拼装/编排（M18）。"""


import pymupdf
import pytest

from app.services.parsekit.errors import (
    InvalidParseOptions,
    LayoutModelUnavailable,
    PdfRenderError,
)
from app.services.parsekit.header_footer import (
    apply_header_footer_erase,
)
from app.services.parsekit.layout_ppdoc import PPDocLayoutEngine
from app.services.parsekit.pipeline import ParseOptions, parse_pdf
from app.services.parsekit.reading_order import sort_reading_order
from app.services.parsekit.render import render_pdf
from app.services.parsekit.types import BBox, LayoutBlock, RenderPage, TextBlock


def make_pdf(pages):
    """pages: list[list[dict]]；每块 {text, x, y, size, font}。"""
    doc = pymupdf.open()
    for blocks in pages:
        page = doc.new_page(width=595, height=842)
        for b in blocks:
            page.insert_text(
                (b.get("x", 72), b.get("y", 72)),
                b["text"],
                fontsize=b.get("size", 12),
                fontname=b.get("font", "helv"),
            )
    data = doc.tobytes()
    doc.close()
    return data


def render_page(page_index, blocks, width=595.0, height=842.0):
    tbs = []
    for item in blocks:
        tbs.append(
            TextBlock(
                text=item["text"],
                bbox=BBox(*item["bbox"]),
                font_size=item.get("size", 12),
                page_index=page_index,
            )
        )
    return RenderPage(
        page_index=page_index,
        width=width,
        height=height,
        image_bytes=b"\x89PNG\r\n\x1a\n",
        text_blocks=tbs,
    )


# ---------- L1M18-01 渲染 ----------
async def test_render_valid_pdf():
    data = make_pdf(
        [
            [{"text": "Page One Body", "x": 72, "y": 120, "size": 12}],
            [{"text": "Page Two Body", "x": 72, "y": 120, "size": 12}],
        ]
    )
    result = render_pdf(data, dpi=150)
    assert len(result.pages) == 2
    assert result.failures == []
    assert result.pages[0].image_bytes.startswith(b"\x89PNG")
    assert any("Page One Body" in b.text for b in result.pages[0].text_blocks)


# ---------- L1M18-02 渲染损坏/空/加密 ----------
async def test_render_invalid_pdf():
    with pytest.raises(PdfRenderError):
        render_pdf(b"not a pdf at all", dpi=150)
    with pytest.raises(PdfRenderError):
        render_pdf(b"", dpi=150)
    with pytest.raises(PdfRenderError):
        render_pdf(b"%PDF fake broken", dpi=150)


async def test_render_encrypted_pdf(tmp_path):
    src = make_pdf([[{"text": "secret", "x": 72, "y": 72}]])
    target = tmp_path / "enc.pdf"
    doc = pymupdf.open(stream=src, filetype="pdf")
    doc.save(
        str(target),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="u1234567",
        owner_pw="o1234567",
    )
    doc.close()
    with pytest.raises(PdfRenderError) as exc:
        render_pdf(target.read_bytes(), dpi=150)
    assert "加密" in str(exc.value)


# ---------- L1M18-03 单页失败 partial ----------
async def test_render_page_failure_partial(monkeypatch):
    data = make_pdf(
        [
            [{"text": "p1", "x": 72, "y": 72}],
            [{"text": "p2", "x": 72, "y": 72}],
        ]
    )
    import app.services.parsekit.render as render_mod

    real = render_mod._render_page

    def boom(doc, index, dpi):
        if index == 1:
            raise RuntimeError("injected page failure")
        return real(doc, index, dpi)

    monkeypatch.setattr(render_mod, "_render_page", boom)
    result = render_pdf(data, dpi=150, partial_on_page_failure=True)
    assert len(result.pages) == 1
    assert len(result.failures) == 1
    assert result.failures[0]["page_index"] == 2

    with pytest.raises(PdfRenderError):
        render_pdf(data, dpi=150, partial_on_page_failure=False)


# ---------- L1M18-04 方案 A 规则擦除 ----------
async def test_header_footer_rule_strategy():
    pages = []
    for idx in range(1, 4):
        blocks = [
            {
                "text": "Company Header Line",
                "bbox": (80, 40, 500, 60),  # 归一化 y ~ 0.05
                "size": 10,
            },
            {
                "text": f"Page {idx} of 3",
                "bbox": (250, 800, 350, 820),  # y ~ 0.95
                "size": 10,
            },
            {
                "text": f"正文第{idx}段",
                "bbox": (80, 250, 400, 270),  # 中部
                "size": 12,
            },
        ]
        pages.append(render_page(idx, blocks))
    # 首页额外放一个不重复的Cover Element
    pages[0].text_blocks.append(
        TextBlock(
            text="变形技术部文件",
            bbox=BBox(80, 95, 250, 120),
            font_size=18,
            page_index=1,
        )
    )
    result = apply_header_footer_erase(pages, mode="rule")
    erased_texts = [e.text for e in result.erased]
    assert "Company Header Line" in erased_texts
    assert any("Page" in t for t in erased_texts)
    kept = [b for blocks in result.pages for b in blocks]
    assert all("正文" not in b.text or b not in erased_texts for b in kept)
    # 封面不重复元素应保留
    assert any(b.text == "变形技术部文件" for b in kept)


# ---------- L1M18-05 U3 评测后仅保留方案 A ----------
async def test_enhanced_mode_rejected_after_ab():
    pages = [
        render_page(
            1,
            [
                {"text": "Repeated Small Header", "bbox": (80, 30, 500, 45), "size": 8},
                {"text": "Page 1 of 3", "bbox": (250, 800, 350, 818), "size": 8},
                {"text": "body", "bbox": (80, 300, 400, 318), "size": 12},
            ],
        )
    ]
    with pytest.raises(ValueError):
        apply_header_footer_erase(pages, mode="enhanced")
    # 方案 A 仍可正常擦除页码
    result = apply_header_footer_erase(pages, mode="rule")
    assert any("Page 1 of 3" in e.text for e in result.erased)


async def test_pipeline_keeps_large_table_containing_repeated_top_text(monkeypatch):
    """重复表头被判为页眉时，不应连带删除覆盖正文区域的大表格。"""
    import app.services.parsekit.pipeline as pipeline_mod

    class _TableEngine:
        failures: ClassVar[list] = []

        def analyze(self, pages, progress=None):
            return [
                [
                    LayoutBlock(
                        type="table",
                        bbox=BBox(0.05, 0.08, 0.95, 0.92),
                        page_index=page.page_index,
                        confidence=0.96,
                        source="ppdoclayoutv3",
                    ),
                    LayoutBlock(
                        type="footnote",
                        bbox=BBox(0.12, 0.94, 0.86, 0.97),
                        page_index=page.page_index,
                        confidence=0.76,
                        source="ppdoclayoutv3",
                    ),
                ]
                for page in pages
            ]

    monkeypatch.setattr(
        pipeline_mod, "_get_layout_engine", lambda options: _TableEngine()
    )
    data = make_pdf(
        [
            [
                {"text": "TEST CERTIFICATION (EN 10204)", "x": 245, "y": 100},
                {"text": f"page body {page}", "x": 80, "y": 300},
            ]
            for page in range(1, 4)
        ]
    )

    result = parse_pdf(
        data,
        options=ParseOptions(dpi=100, ocr_enabled=False),
    )

    for page in result.layout["pages"]:
        assert [block["type"] for block in page["blocks"]] == [
            "table",
            "footnote",
        ]
    assert result.stats["margin_blocks_dropped"] == 0


# ---------- L1M18-06 阅读顺序（两栏） ----------
async def test_reading_order_two_columns():
    blocks = [
        LayoutBlock(type="text", bbox=BBox(0.60, 0.10, 0.95, 0.16), page_index=1),
        LayoutBlock(type="text", bbox=BBox(0.10, 0.10, 0.45, 0.16), page_index=1),
        LayoutBlock(type="text", bbox=BBox(0.60, 0.30, 0.95, 0.36), page_index=1),
        LayoutBlock(type="text", bbox=BBox(0.10, 0.30, 0.45, 0.36), page_index=1),
    ]
    ordered = sort_reading_order(blocks)
    xs = [b.bbox.x0 for b in ordered]
    assert xs == pytest.approx([0.10, 0.60, 0.10, 0.60])
    assert [b.order for b in ordered] == [1, 2, 3, 4]


# ---------- L1M18-07 Markdown 拼装 ----------
async def test_assemble_markdown():
    from app.services.parsekit.assemble import assemble_markdown

    blocks = [
        LayoutBlock(
            type="title",
            bbox=BBox(0.1, 0.1, 0.5, 0.14),
            page_index=1,
            content="第一章",
            structural={"title_level": 2},
        ),
        LayoutBlock(
            type="text", bbox=BBox(0.1, 0.2, 0.5, 0.24), page_index=1, content="正文内容"
        ),
        LayoutBlock(
            type="table", bbox=BBox(0.1, 0.3, 0.5, 0.4), page_index=1, content=""
        ),
        LayoutBlock(
            type="formula", bbox=BBox(0.1, 0.5, 0.5, 0.55), page_index=2, content=""
        ),
        LayoutBlock(type="image", bbox=BBox(0.1, 0.6, 0.5, 0.8), page_index=2),
    ]
    md = assemble_markdown(blocks)
    assert "## 第一章" in md
    assert "正文内容" in md
    assert "<!-- table: page 1 -->" in md
    assert "<!-- formula: page 2 -->" in md
    assert "<!-- image: page 2 -->" in md
    assert "<!-- page: 2 -->" in md


# ---------- L1M18-09 PP-DocLayoutV3 权重缺失报错 ----------
async def test_ppdoclayoutv3_engine_missing_weights(tmp_path):
    with pytest.raises(LayoutModelUnavailable) as exc:
        PPDocLayoutEngine(tmp_path / "not_exist")
    assert "权重未部署" in str(exc.value)


# ---------- L1M18-10 layout.json U9 预留字段 ----------
def _fake_layout_engine(options):
    """测试注入：基于文本层的轻量引擎（不加载模型），source=text。"""

    class _FakeEngine:
        name = "fake"
        failures: ClassVar[list] = []

        def analyze(self, pages, progress=None):
            result = []
            for page in pages:
                if progress:
                    progress("layout", page.page_index, len(pages))
                blocks = []
                max_font = max((b.font_size for b in page.text_blocks), default=0.0)
                for tb in page.text_blocks:
                    nb = tb.bbox.normalized(page.width, page.height)
                    is_title = (
                        tb.font_size >= max(max_font * 0.85, 14.0)
                        and len(tb.text.strip()) <= 60
                    )
                    blocks.append(
                        LayoutBlock(
                            type="title" if is_title else "text",
                            bbox=nb,
                            page_index=page.page_index,
                            confidence=0.9,
                            content=tb.text,
                            source="text",
                        )
                    )
                for img in page.image_boxes:
                    nb = img.normalized(page.width, page.height)
                    blocks.append(
                        LayoutBlock(
                            type="image",
                            bbox=nb,
                            page_index=page.page_index,
                            confidence=0.9,
                            source="text",
                        )
                    )
                result.append(blocks)
            return result

    return _FakeEngine()


async def test_layout_json_u9_contract(monkeypatch):
    import app.services.parsekit.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_get_layout_engine", _fake_layout_engine)
    data = make_pdf([[{"text": "Heading One", "x": 200, "y": 100, "size": 24}]])
    result = parse_pdf(data, options=ParseOptions(dpi=100))
    layout = result.layout
    assert layout["schema_version"] == "1.2"
    assert layout["page_count"] == 1
    page = layout["pages"][0]
    assert page["path"] == "pages/page-0001.png"
    assert "title" in page
    assert page["type"] == "page"
    assert "structural" in page
    for block in page["blocks"]:
        assert "path" in block
        assert "title" in block
        assert "structural" in block
    assert "Heading One" in result.markdown


# ---------- L1M18-11 管线端到端（内存 PDF） ----------
async def test_pipeline_end_to_end(monkeypatch):
    import app.services.parsekit.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_get_layout_engine", _fake_layout_engine)
    data = make_pdf(
        [
            [{"text": "Cover Element", "x": 200, "y": 120, "size": 18}],
            [
                {"text": "Company Secret", "x": 80, "y": 35, "size": 9},
                {"text": "Body Page Two", "x": 80, "y": 300, "size": 12},
            ],
            [
                {"text": "Company Secret", "x": 80, "y": 35, "size": 9},
                {"text": "Body Page Three", "x": 80, "y": 300, "size": 12},
            ],
        ]
    )
    result = parse_pdf(data, options=ParseOptions(dpi=100))
    assert result.stats["pages"] == 3
    assert len(result.pages) == 3
    assert result.stats["erased_blocks"] >= 2
    assert "Body Page Two" in result.markdown
    assert "Body Page Three" in result.markdown
    assert "Company Secret" not in result.markdown
    assert result.layout["page_failures"] == []


# ---------- L1M18-14 页级进度回调 ----------
async def test_parse_pdf_progress_reports_pages(monkeypatch):
    import app.services.parsekit.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_get_layout_engine", _fake_layout_engine)
    data = make_pdf(
        [
            [{"text": "Page One Body", "x": 72, "y": 120, "size": 12}],
            [{"text": "Page Two Body", "x": 72, "y": 120, "size": 12}],
            [{"text": "Page Three Body", "x": 72, "y": 120, "size": 12}],
        ]
    )
    events: list[tuple[str, int | None, int | None]] = []
    parse_pdf(
        data,
        options=ParseOptions(dpi=100, ocr_enabled=False),
        progress=lambda stage, page=None, total=None: events.append(
            (stage, page, total)
        ),
    )
    render_events = [e for e in events if e[0] == "rendering"]
    layout_events = [e for e in events if e[0] == "layout"]
    assert len(render_events) == 3
    assert len(layout_events) == 3
    assert all(total == 3 for _, _, total in render_events + layout_events)
    assert [p for _, p, _ in render_events] == [1, 2, 3]
    assert [p for _, p, _ in layout_events] == [1, 2, 3]
    assert events[-1][0] == "rebuild"


# ---------- L1M18-12 参数校验 ----------
async def test_parse_options_validation():
    for opts in (
        ParseOptions(dpi=10),
        ParseOptions(layout_conf_threshold=0.0),
        ParseOptions(header_footer_mode="unknown"),
        ParseOptions(dpi=800),
    ):
        with pytest.raises(InvalidParseOptions):
            parse_pdf(b"%PDF test", options=opts)


# ---------- L1M18-13 对象键净化（单元层） ----------
async def test_object_key_sanitized():
    from app.services.storage import document_object_key

    key = document_object_key(
        __import__("uuid").UUID(int=1), "task-1", "../../evil.pdf"
    )
    assert ".." not in key
    assert key.endswith("evil.pdf")


# ---------- L1M18-14 版面块类型常量 ----------
async def test_block_types_constant():
    from app.services.parsekit.types import BLOCK_TYPES

    for t in ("title", "text", "table", "formula", "image", "header", "footer"):
        assert t in BLOCK_TYPES


# ---------- 引擎单例并发安全（2026-08 修复：双检锁 + 推理锁） ----------
def test_engine_singleton_concurrent(monkeypatch):
    """并发首次获取引擎只创建一个实例（双检锁），不重复加载模型。"""
    import threading

    import app.services.parsekit.pipeline as pipeline_mod
    from app.services.parsekit.layout_ppdoc import PPDocLayoutEngine
    from app.services.parsekit.pipeline import ParseOptions, _ENGINE_CACHE, _ENGINE_LOCK

    created = []
    real_init = PPDocLayoutEngine.__init__

    def counting_init(self, model_dir, **kw):
        created.append(model_dir)
        # 不真正加载模型：只设置必要属性
        from pathlib import Path

        self.model_dir = Path(model_dir)
        self.device = "cpu"
        self.conf_threshold = float(kw.get("conf_threshold", 0.4))
        self.verify_hash = False
        self._model = None
        self._processor = None
        self._id2label = {}
        self.failures = []
        import threading as _th

        self._infer_lock = _th.Lock()

    monkeypatch.setattr(PPDocLayoutEngine, "__init__", counting_init)
    _ENGINE_CACHE.clear()
    opts = ParseOptions(layout_model_dir="/tmp/fake_v3", layout_conf_threshold=0.4)
    results = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        results.append(pipeline_mod._get_layout_engine(opts))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(created) == 1, f"并发首次获取应只创建 1 个引擎，实际 {len(created)}"
    assert all(r is results[0] for r in results), "所有线程应拿到同一实例"
    _ENGINE_CACHE.clear()
