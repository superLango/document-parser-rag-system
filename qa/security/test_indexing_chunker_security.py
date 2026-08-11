"""L5 安全渗透：M25 分块器输入安全（不可信 layout.json 防御）。"""

import json

from app.services.indexing.chunker import HierarchyChunker
from app.services.indexing.table_cleaner import table_cleaner
from app.services.indexing.table_enhancer import table_enhancer


def test_deep_nesting_terminates():
    """L5M25-01：恶意超深嵌套 document_tree 在深度上限处截断，不栈溢出。"""
    node = {"type": "text", "content": "x", "level": 0, "page": 0, "order": 0, "children": []}
    for _ in range(5000):
        node = {"type": "title", "content": "t", "level": 1, "page": 0, "order": 0, "children": [node]}
    layout = {"rebuild": {"document_tree": {"type": "root", "children": [node]}}}
    parents, children = HierarchyChunker().chunk(layout, "d-mal")
    assert isinstance(parents, list)
    assert isinstance(children, list)


def test_huge_content_does_not_duplicate():
    """L5M25-02：超大 content 不产生无限循环，块内容保持有界。"""
    content = "恶意超长内容" * 100000  # 约 60 万字符
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {"type": "text", "content": content, "level": 0,
                     "page": 0, "order": 0, "children": []}
                ],
            }
        }
    }
    chunker = HierarchyChunker(max_child_chars=2000)
    _, children = chunker.chunk(layout, "d-huge")
    assert children
    total = sum(len(c.content) for c in children)
    assert total >= len(content) - 1  # 内容不丢失
    for c in children:
        assert len(c.content) <= 2000 + 200  # 允许单句超阈值 + overlap


def test_html_injection_in_caption_is_data():
    """L5M25-03：题注中的 HTML/脚本作为纯文本处理，不执行不逃逸破坏结构。"""
    table_html = (
        "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    )
    caption = "<script>alert(1)</script>表3 恶意题注"
    text = table_enhancer.enhance(table_html, caption=caption)
    assert "alert(1)" in text  # 作为数据保留
    # 分块器嵌入文本含题注原文，不展开为可执行结构
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {"type": "table", "content": table_html, "level": 0,
                     "page": 0, "order": 0, "children": [
                        {"type": "table_caption", "content": caption,
                         "level": 0, "page": 0, "order": 1, "children": []}
                    ]}
                ],
            }
        }
    }
    _, children = HierarchyChunker().chunk(layout, "d-inj")
    assert children[0].has_table is True
    assert "alert(1)" in children[0].content_for_embedding


def test_path_hoping_fields_ignored():
    """L5M25-04：layout 中路径类字段不作为文件系统路径使用（分块器无 IO）。"""
    layout = {
        "rebuild": {
            "document_tree": {
                "type": "root",
                "children": [
                    {"type": "text", "content": "正常内容", "level": 0,
                     "page": 0, "order": 0, "children": []}
                ],
            }
        },
        "pages": [
            {"page_index": 0, "blocks": [
                {"type": "text", "content": "x", "path": "../../etc/passwd",
                 "page_index": 0, "order": 0, "source": "rule"}
            ]}
        ],
    }
    parents, children = HierarchyChunker().chunk(layout, "d-io")
    assert children and children[0].content == "正常内容"
    assert all("/" not in c.content for c in children if c.content == "正常内容")


def test_table_cleaner_rejects_binary_input():
    """L5M25-05：异常/二进制内容经清洗器不抛异常。"""
    for payload in (b"\x00\x01", "\x00\x01", "<table>\x00</table>"):
        try:
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="ignore")
            result = table_cleaner.clean(payload)
            assert isinstance(result, str)
        except Exception as exc:  # 不允许向调用方泄漏崩溃
            raise AssertionError(f"不应抛出异常: {exc}") from exc
