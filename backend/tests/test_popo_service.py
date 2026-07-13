"""MinerU-Popo 后处理服务测试模块。

测试 PopoService 的核心功能：
- ``_normalize_layout``：版面格式转换与 bbox 归一化
- ``_save_as_temp_pdf``：PDF/图片转临时 PDF
- ``post_process``：异步入口（mock 推理调用）
- 错误处理：推理失败返回 None

所有测试通过 mock 避免加载真实 17GB 模型，确保无 GPU 环境可运行。
"""

import json
import os
import sys
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.services.popo_service import PopoService, _POPO_ENGINE_DIR, _TYPE_MAP


# ---------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------
def _make_pdf_bytes() -> bytes:
    """生成最小合法 PDF 字节流。"""
    # 用 fitz 生成一个真实 PDF 以确保 fitz 能识别
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Hello PDF")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _make_image_bytes(
    width: int = 100, height: int = 80, color: str = "white"
) -> bytes:
    """生成 PNG 格式的测试图像字节流。"""
    img = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_layout(
    text_count: int = 2,
    include_header_footer: bool = True,
    include_table_figure: bool = True,
) -> list[dict]:
    """构造 merged_layout 测试数据。

    bbox 使用像素坐标（page_size=1000x1000 时归一化为 [0,1] 区间）。
    """
    layout: list[dict] = []
    if include_header_footer:
        layout.append(
            {
                "type": "header",
                "bbox": [0, 0, 1000, 50],
                "text": "Header text",
            }
        )
    layout.append(
        {
            "type": "title",
            "bbox": [100, 100, 900, 200],
            "text": "Document Title",
        }
    )
    for i in range(text_count):
        layout.append(
            {
                "type": "text",
                "bbox": [100, 200 + i * 100, 900, 280 + i * 100],
                "text": f"Paragraph {i + 1} content here.",
            }
        )
    if include_table_figure:
        layout.append(
            {
                "type": "table",
                "bbox": [100, 500, 900, 700],
                "html": "<table><tr><td>A</td></tr></table>",
            }
        )
        layout.append(
            {
                "type": "figure",
                "bbox": [100, 750, 900, 950],
                "text": "Figure caption",
            }
        )
    if include_header_footer:
        layout.append(
            {
                "type": "footer",
                "bbox": [0, 980, 1000, 1000],
                "text": "Footer text",
            }
        )
    return layout


# ---------------------------------------------------------------
# _normalize_layout 测试
# ---------------------------------------------------------------
class TestNormalizeLayout:
    """``PopoService._normalize_layout`` 测试。"""

    def test_returns_dict_with_page_key(self):
        """测试返回 dict 且包含页码 "1" 键。"""
        service = PopoService()
        layout = _make_layout(text_count=1, include_header_footer=False)
        result = service._normalize_layout(
            layout, page_size={"width": 1000, "height": 1000}
        )
        assert "1" in result
        assert isinstance(result["1"], list)

    def test_header_footer_skipped(self):
        """测试 header/footer 区域被跳过。"""
        service = PopoService()
        layout = _make_layout(include_header_footer=True)
        result = service._normalize_layout(
            layout, page_size={"width": 1000, "height": 1000}
        )
        # 所有保留块都不应是 None 类型
        for block in result["1"]:
            assert block["type"] in {"text", "title", "table", "image"}

    def test_type_mapping_text_title(self):
        """测试 text -> text, title -> title 的类型映射。"""
        service = PopoService()
        layout = [
            {"type": "text", "bbox": [0, 0, 100, 100], "text": "hello"},
            {"type": "title", "bbox": [0, 0, 100, 100], "text": "title"},
        ]
        result = service._normalize_layout(
            layout, page_size={"width": 100, "height": 100}
        )
        types = [b["type"] for b in result["1"]]
        assert "text" in types
        assert "title" in types

    def test_figure_mapped_to_image(self):
        """测试 figure -> image 的类型映射。"""
        service = PopoService()
        layout = [
            {"type": "figure", "bbox": [0, 0, 100, 100], "text": "img"},
        ]
        result = service._normalize_layout(
            layout, page_size={"width": 100, "height": 100}
        )
        assert result["1"][0]["type"] == "image"

    def test_table_kept(self):
        """测试 table 类型保留。"""
        service = PopoService()
        layout = [
            {"type": "table", "bbox": [0, 0, 100, 100], "html": "<table></table>"},
        ]
        result = service._normalize_layout(
            layout, page_size={"width": 100, "height": 100}
        )
        assert result["1"][0]["type"] == "table"
        assert result["1"][0]["content"] == "<table></table>"

    def test_bbox_normalized_to_unit_interval(self):
        """测试 bbox 被归一化到 [0,1] 区间。"""
        service = PopoService()
        layout = [
            {
                "type": "text",
                "bbox": [100, 200, 800, 900],
                "text": "normalized bbox",
            }
        ]
        result = service._normalize_layout(
            layout, page_size={"width": 1000, "height": 1000}
        )
        bbox = result["1"][0]["bbox"]
        assert bbox == [0.1, 0.2, 0.8, 0.9]
        # 所有值在 [0, 1] 区间
        for v in bbox:
            assert 0.0 <= v <= 1.0

    def test_bbox_clamped_to_unit_interval(self):
        """测试 bbox 越界被裁剪到 [0,1]。"""
        service = PopoService()
        layout = [
            {
                "type": "text",
                "bbox": [-100, -100, 2000, 2000],
                "text": "out of bounds",
            }
        ]
        result = service._normalize_layout(
            layout, page_size={"width": 1000, "height": 1000}
        )
        bbox = result["1"][0]["bbox"]
        assert bbox == [0.0, 0.0, 1.0, 1.0]

    def test_invalid_bbox_skipped(self):
        """测试 x2<=x1 或 y2<=y1 的无效 bbox 被跳过。"""
        service = PopoService()
        layout = [
            {"type": "text", "bbox": [100, 100, 100, 200], "text": "zero width"},
            {"type": "text", "bbox": [100, 100, 200, 100], "text": "zero height"},
            {"type": "text", "bbox": [200, 200, 100, 100], "text": "inverted"},
        ]
        result = service._normalize_layout(
            layout, page_size={"width": 1000, "height": 1000}
        )
        assert result == {}

    def test_empty_content_skipped(self):
        """测试无文本内容的块被跳过。"""
        service = PopoService()
        layout = [
            {"type": "text", "bbox": [0, 0, 100, 100], "text": ""},
            {"type": "text", "bbox": [0, 0, 100, 100], "text": "   "},
            {"type": "text", "bbox": [0, 0, 100, 100]},  # 无 text 字段
        ]
        result = service._normalize_layout(
            layout, page_size={"width": 100, "height": 100}
        )
        assert result == {}

    def test_empty_layout_returns_empty_dict(self):
        """测试空 layout 输入返回空 dict。"""
        service = PopoService()
        result = service._normalize_layout(
            [], page_size={"width": 100, "height": 100}
        )
        assert result == {}

    def test_content_truncated_to_5000_chars(self):
        """测试 content 超过 5000 字符时被截断。"""
        service = PopoService()
        long_text = "a" * 6000
        layout = [
            {"type": "text", "bbox": [0, 0, 100, 100], "text": long_text}
        ]
        result = service._normalize_layout(
            layout, page_size={"width": 100, "height": 100}
        )
        assert len(result["1"][0]["content"]) == 5000


# ---------------------------------------------------------------
# _save_as_temp_pdf 测试
# ---------------------------------------------------------------
class TestSaveAsTempPdf:
    """``PopoService._save_as_temp_pdf`` 测试。"""

    def test_pdf_bytes_saved_directly(self):
        """测试 PDF 字节流直接保存为临时 PDF 文件。"""
        service = PopoService()
        pdf_bytes = _make_pdf_bytes()
        path = service._save_as_temp_pdf(pdf_bytes)

        try:
            assert os.path.exists(path)
            assert path.endswith(".pdf")
            # 文件内容应与输入一致
            with open(path, "rb") as f:
                assert f.read() == pdf_bytes
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_image_bytes_converted_to_pdf(self):
        """测试 PNG 图像字节流被转换为单页 PDF。"""
        service = PopoService()
        img_bytes = _make_image_bytes(width=120, height=80)
        path = service._save_as_temp_pdf(img_bytes)

        try:
            assert os.path.exists(path)
            assert path.endswith(".pdf")
            # 验证生成的 PDF 可被 fitz 打开且为单页
            import fitz

            doc = fitz.open(path)
            assert doc.page_count == 1
            doc.close()
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_invalid_bytes_falls_back_to_image_branch(self):
        """测试无效字节流触发图片分支并抛出异常。"""
        service = PopoService()
        # 非 PDF 也非合法图像：fitz 解析失败 -> 进入图片分支 -> PIL 也失败
        with pytest.raises(Exception):
            service._save_as_temp_pdf(b"not a valid pdf or image")


# ---------------------------------------------------------------
# _parse_popo_result 测试
# ---------------------------------------------------------------
class TestParsePopoResult:
    """``PopoService._parse_popo_result`` 测试。"""

    def test_empty_input_returns_empty_fields(self):
        """测试空输入返回空字段但结构完整。"""
        service = PopoService()
        result = service._parse_popo_result([])
        assert result["title_hierarchy"] == []
        assert result["text_continuations"] == []
        assert result["image_associations"] == []
        assert result["table_continuations"] == []
        assert result["enriched_text"] == ""

    def test_title_hierarchy_extracted(self):
        """测试标题层级被正确抽取。"""
        service = PopoService()
        doc_blocks = [
            {"id": 1, "content": "Chapter 1", "level": 0, "contd": -1, "image": -1, "table_merge": -1},
            {"id": 2, "content": "Section 1.1", "level": 1, "contd": -1, "image": -1, "table_merge": -1},
            {"id": 3, "content": "body text", "level": -1, "contd": -1, "image": -1, "table_merge": -1},
        ]
        result = service._parse_popo_result(doc_blocks)
        assert len(result["title_hierarchy"]) == 2
        assert result["title_hierarchy"][0] == {
            "block_id": 1,
            "level": 0,
            "content": "Chapter 1",
        }

    def test_text_continuations_extracted(self):
        """测试跨页文本合并关系被抽取。"""
        service = PopoService()
        doc_blocks = [
            {"id": 1, "content": "para1...", "contd": 2, "level": -1, "image": -1, "table_merge": -1},
            {"id": 2, "content": "...para2", "contd": -1, "level": -1, "image": -1, "table_merge": -1},
        ]
        result = service._parse_popo_result(doc_blocks)
        assert result["text_continuations"] == [{"src_id": 1, "tgt_id": 2}]

    def test_image_associations_extracted(self):
        """测试图文关联被抽取。"""
        service = PopoService()
        doc_blocks = [
            {"id": 5, "content": "figure", "image": 6, "contd": -1, "level": -1, "table_merge": -1},
            {"id": 6, "content": "caption", "image": -1, "contd": -1, "level": -1, "table_merge": -1},
        ]
        result = service._parse_popo_result(doc_blocks)
        assert result["image_associations"] == [{"image_id": 5, "caption_id": 6}]

    def test_table_continuations_extracted(self):
        """测试跨页表格合并被抽取。"""
        service = PopoService()
        doc_blocks = [
            {"id": 10, "content": "<table>", "table_merge": 11, "contd": -1, "level": -1, "image": -1},
            {"id": 11, "content": "<table>", "table_merge": 10, "contd": -1, "level": -1, "image": -1},
        ]
        result = service._parse_popo_result(doc_blocks)
        assert {"src_id": 10, "tgt_id": 11} in result["table_continuations"]
        assert {"src_id": 11, "tgt_id": 10} in result["table_continuations"]

    def test_enriched_text_concatenated(self):
        """测试 enriched_text 按 doc_blocks 顺序拼接。"""
        service = PopoService()
        doc_blocks = [
            {"id": 1, "content": "AAA", "contd": -1, "level": -1, "image": -1, "table_merge": -1},
            {"id": 2, "content": "BBB", "contd": -1, "level": -1, "image": -1, "table_merge": -1},
        ]
        result = service._parse_popo_result(doc_blocks)
        assert result["enriched_text"] == "AAA\nBBB"


# ---------------------------------------------------------------
# post_process 异步测试
# ---------------------------------------------------------------
class TestPostProcess:
    """``PopoService.post_process`` 异步测试。"""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_valid_blocks(self):
        """测试无有效布局块时返回 None。"""
        service = PopoService()
        # 仅包含 header（被跳过）-> 无有效块
        layout = [
            {"type": "header", "bbox": [0, 0, 100, 10], "text": "header"},
        ]
        result = await service.post_process(
            b"fake",
            layout,
            page_size={"width": 100, "height": 100},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_post_process_with_mocked_inference(self):
        """测试 mock popo_main 后 post_process 返回解析结构。"""
        service = PopoService()
        layout = _make_layout(include_header_footer=False)
        pdf_bytes = _make_pdf_bytes()

        # 准备 fake doc_blocks（inference.main 会写入此内容）
        fake_doc_blocks = [
            {
                "id": 1,
                "type": "title",
                "content": "Document Title",
                "bbox": [0.1, 0.1, 0.9, 0.2],
                "page": 1,
                "contd": -1,
                "level": 0,
                "image": -1,
                "table_merge": -1,
            },
            {
                "id": 2,
                "type": "text",
                "content": "Paragraph 1 content here.",
                "bbox": [0.1, 0.2, 0.9, 0.28],
                "page": 1,
                "contd": 3,
                "level": -1,
                "image": -1,
                "table_merge": -1,
            },
            {
                "id": 3,
                "type": "text",
                "content": "Paragraph 2 content here.",
                "bbox": [0.1, 0.3, 0.9, 0.38],
                "page": 1,
                "contd": -1,
                "level": -1,
                "image": -1,
                "table_merge": -1,
            },
        ]

        def _fake_main(input_label, ocr_res, output_dir, raw_output_dir=None):
            """模拟 inference.main：将 doc_blocks 写入 output_dir。"""
            stem = os.path.splitext(os.path.basename(input_label))[0]
            with open(
                os.path.join(output_dir, f"{stem}.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(fake_doc_blocks, f)

        # mock sys.path 中已存在 popo_engine，使 from inference import main 可解析
        # 用 patch 替换 inference.main
        with patch.dict(sys.modules, {"inference": MagicMock(main=_fake_main)}):
            result = await service.post_process(
                pdf_bytes,
                layout,
                page_size={"width": 1000, "height": 1000},
            )

        assert result is not None
        assert "title_hierarchy" in result
        assert "text_continuations" in result
        assert "image_associations" in result
        assert "table_continuations" in result
        assert "enriched_text" in result
        # 标题层级：id=1, level=0
        assert len(result["title_hierarchy"]) == 1
        assert result["title_hierarchy"][0]["block_id"] == 1
        # 文本续接：id=2 -> id=3
        assert {"src_id": 2, "tgt_id": 3} in result["text_continuations"]
        # enriched_text 应包含所有 content
        assert "Document Title" in result["enriched_text"]
        assert "Paragraph 1" in result["enriched_text"]

    @pytest.mark.asyncio
    async def test_post_process_returns_none_on_inference_failure(self):
        """测试推理异常时返回 None（不抛出）。"""
        service = PopoService()
        layout = [
            {"type": "text", "bbox": [0, 0, 100, 100], "text": "hello"}
        ]
        pdf_bytes = _make_pdf_bytes()

        def _raising_main(input_label, ocr_res, output_dir, raw_output_dir=None):
            raise RuntimeError("model load failed")

        with patch.dict(sys.modules, {"inference": MagicMock(main=_raising_main)}):
            result = await service.post_process(
                pdf_bytes,
                layout,
                page_size={"width": 100, "height": 100},
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_post_process_returns_none_when_no_output_json(self):
        """测试推理未产生输出文件时返回 None。"""
        service = PopoService()
        layout = [
            {"type": "text", "bbox": [0, 0, 100, 100], "text": "hello"}
        ]
        pdf_bytes = _make_pdf_bytes()

        def _empty_main(input_label, ocr_res, output_dir, raw_output_dir=None):
            """不写任何文件。"""
            return None

        with patch.dict(sys.modules, {"inference": MagicMock(main=_empty_main)}):
            result = await service.post_process(
                pdf_bytes,
                layout,
                page_size={"width": 100, "height": 100},
            )
        assert result is None


# ---------------------------------------------------------------
# _ensure_env 测试
# ---------------------------------------------------------------
class TestEnsureEnv:
    """``PopoService._ensure_env`` 测试。"""

    def test_sets_environment_variables(self, monkeypatch):
        """测试设置 POPO_MODEL_PATH 和 POPO_INFERENCE_BACKEND 环境变量。"""
        monkeypatch.delenv("POPO_MODEL_PATH", raising=False)
        monkeypatch.delenv("POPO_INFERENCE_BACKEND", raising=False)

        service = PopoService()
        service._ensure_env()

        assert os.environ.get("POPO_INFERENCE_BACKEND") == "transformers"
        assert os.environ.get("POPO_MODEL_PATH")  # 非空

    def test_idempotent(self):
        """测试多次调用 _ensure_env 不会重复执行初始化逻辑。"""
        service = PopoService()
        service._ensure_env()
        first_path = service._model_path
        first_init = service._initialized

        service._ensure_env()
        assert service._initialized is first_init
        assert service._model_path == first_path

    def test_popo_engine_dir_added_to_sys_path(self):
        """测试 popo_engine 目录被添加到 sys.path。"""
        service = PopoService()
        service._ensure_env()
        assert _POPO_ENGINE_DIR in sys.path


# ---------------------------------------------------------------
# 类型映射常量测试
# ---------------------------------------------------------------
class TestTypeMap:
    """``_TYPE_MAP`` 常量测试。"""

    def test_text_maps_to_text(self):
        assert _TYPE_MAP["text"] == "text"

    def test_title_maps_to_title(self):
        assert _TYPE_MAP["title"] == "title"

    def test_table_maps_to_table(self):
        assert _TYPE_MAP["table"] == "table"

    def test_figure_maps_to_image(self):
        assert _TYPE_MAP["figure"] == "image"

    def test_header_is_skipped(self):
        assert _TYPE_MAP["header"] is None

    def test_footer_is_skipped(self):
        assert _TYPE_MAP["footer"] is None
