"""L1 单元测试：Phase 4 后处理与版面重建（M20）。"""

from typing import ClassVar

from app.services.parsekit.rebuild import (
    build_tree,
    mark_cross_page_tables,
    render_tree,
)
from app.services.parsekit.types import BBox, LayoutBlock


def _block(block_type, page=1, x0=0.1, y0=0.1, x1=0.5, y1=0.2,
           content="", order=1, structural=None):
    return LayoutBlock(
        type=block_type,
        bbox=BBox(x0, y0, x1, y1),
        page_index=page,
        order=order,
        content=content,
        structural=structural or {},
    )


# ---------- L1M20-01 标题层级嵌套 ----------
async def test_build_tree_title_hierarchy():
    blocks = [
        _block("title", content="第一章", structural={"title_level": 1}, order=1),
        _block("title", content="1.1 小节", structural={"title_level": 2}, order=2),
        _block("text", content="正文A", order=3),
        _block("title", content="1.2 小节", structural={"title_level": 2}, order=4),
    ]
    tree = build_tree(blocks)
    children = tree["children"]
    assert children[0]["type"] == "title"
    assert children[0]["level"] == 1
    assert len(children[0]["children"]) == 2
    assert children[0]["children"][0]["content"] == "1.1 小节"
    assert children[0]["children"][0]["children"][0]["content"] == "正文A"
    assert children[0]["children"][1]["content"] == "1.2 小节"


# ---------- L1M20-02 图文关联 ----------
async def test_build_tree_image_caption_link():
    blocks = [
        _block("image", content="", order=1),
        _block("image_caption", content="图1 示意图", order=2),
        _block("text", content="说明", order=3),
    ]
    tree = build_tree(blocks)
    image = tree["children"][0]
    assert image["type"] == "image"
    assert image["children"][0]["type"] == "image_caption"
    assert image["children"][0]["content"] == "图1 示意图"
    assert tree["stats"]["image_caption_links"] == 1


# ---------- L1M20-03 表注关联 ----------
async def test_build_tree_table_caption_link():
    blocks = [
        _block("table", content="<table></table>", order=1),
        _block("table_caption", content="表1 成分表", order=2),
    ]
    tree = build_tree(blocks)
    table = tree["children"][0]
    assert table["children"][0]["type"] == "table_caption"
    assert tree["stats"]["table_caption_links"] == 1


# ---------- L1M20-04 结构树渲染 ----------
async def test_render_tree():
    tree = build_tree(
        [
            _block("title", content="第一章", structural={"title_level": 1}, order=1),
            _block("text", content="正文", order=2),
            _block("table", content="<table><tr><td>x</td></tr></table>", order=3),
            _block("formula", content="E=mc^2", order=4),
            _block("image", content="", order=5),
            _block("image_caption", content="图注", order=6),
        ]
    )
    md = render_tree(tree)
    assert "# 第一章" in md
    assert "正文" in md
    assert "<table>" in md
    assert "$$E=mc^2$$" in md
    assert "<!-- image:" in md
    assert "*图注*" in md


# ---------- L1M20-05 跨页表格标记（U8） ----------
async def test_mark_cross_page_tables():
    pages = [
        [
            _block("table", page=1, x0=0.1, y0=0.88, x1=0.9, y1=0.98, order=1),
            _block("text", page=1, x0=0.1, y0=0.3, x1=0.5, y1=0.4, order=2),
        ],
        [
            _block("table", page=2, x0=0.12, y0=0.02, x1=0.92, y1=0.12, order=1),
        ],
    ]
    marked = mark_cross_page_tables(pages)
    assert marked == 2
    assert pages[0][0].structural["table_cross_page"] is True
    assert pages[1][0].structural["table_cross_page"] is True


# ---------- L1M20-06 跨页不重叠不标记 ----------
async def test_mark_cross_page_tables_no_overlap():
    pages = [
        [
            _block("table", page=1, x0=0.1, y0=0.9, x1=0.3, y1=0.98, order=1),
        ],
        [
            _block("table", page=2, x0=0.6, y0=0.02, x1=0.9, y1=0.1, order=1),
        ],
    ]
    marked = mark_cross_page_tables(pages)
    assert marked == 0
    assert "table_cross_page" not in pages[0][0].structural
    assert "table_cross_page" not in pages[1][0].structural


# ---------- L1M20-07 空文档树 ----------
async def test_build_tree_empty_and_no_titles():
    tree = build_tree([])
    assert tree["type"] == "root"
    assert tree["children"] == []
    tree2 = build_tree([_block("text", content="无标题正文", order=1)])
    assert tree2["children"][0]["type"] == "text"
    assert tree2["stats"]["title_count"] == 0


# ---------- L1M20-08 layout.json 结构树与 U8 字段 ----------
async def test_layout_json_rebuild_fields(monkeypatch):
    import pymupdf

    import app.services.parsekit.pipeline as pipeline_mod
    from app.services.parsekit import ParseOptions, parse_pdf

    def _fake_layout_engine(options):
        from app.services.parsekit.types import LayoutBlock

        class _FakeEngine:
            name = "fake"
            failures: ClassVar[list] = []

            def analyze(self, pages, progress=None):
                result = []
                for page in pages:
                    blocks = [
                        LayoutBlock(
                            type="text",
                            bbox=tb.bbox.normalized(page.width, page.height),
                            page_index=page.page_index,
                            confidence=0.9,
                            content=tb.text,
                            source="text",
                        )
                        for tb in page.text_blocks
                    ]
                    result.append(blocks)
                return result

        return _FakeEngine()

    monkeypatch.setattr(pipeline_mod, "_get_layout_engine", _fake_layout_engine)

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "hello rebuild", fontsize=12)
    data = doc.tobytes()
    doc.close()
    result = parse_pdf(data, options=ParseOptions(dpi=100, ocr_enabled=False))
    layout = result.layout
    assert layout["schema_version"] == "1.2"
    assert "document_tree" in layout["rebuild"]
    assert layout["rebuild"]["enabled"] is True
    assert "cross_page_tables_note" in layout["rebuild"]
    assert result.stats["rebuild"]["title_count"] >= 0
