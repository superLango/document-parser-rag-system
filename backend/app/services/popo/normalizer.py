"""GLM-OCR 输出归一化适配器。

将 ``merged.json``（GLM-OCR 输出）+ ``source.pdf`` 转换为 MinerU-Popo
要求的统一输入格式：``{page_str: [block, ...]}``。

每个 block 包含：
- ``type``：Popo 标准类型（title/text/table/image/image_caption 等）
- ``content``：文本内容或 HTML 表格
- ``bbox``：归一化边界框 ``[x1, y1, x2, y2]``，值域 [0, 1]

bbox 归一化使用 PDF 页面像素尺寸（通过 PyMuPDF 读取）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# GLM-OCR native_label → Popo type 映射
_LABEL_TYPE_MAP: dict[str, str] = {
    "doc_title": "title",
    "paragraph_title": "title",
    "figure_title": "image_caption",
    "table": "table",
    "text": "text",
    "seal": "image",
    "vision_footnote": "text",
}

# Popo 允许的 block 类型（inference 内部 filter 会按这些类型筛选）
_ALLOWED_TYPES: set[str] = {
    "title", "text", "list_item", "equation", "image", "table",
    "image_caption", "table_caption", "image_footnote", "table_footnote",
    "page_title", "page_number", "page_footnote", "header", "aside_text",
    "footer",
}


class GlmOcrNormalizer:
    """GLM-OCR → Popo 归一化器。"""

    @staticmethod
    def normalize(merged_json_path: str | Path, pdf_path: str | Path) -> dict[str, list[dict]]:
        """将 merged.json + PDF 归一化为 Popo 输入格式。

        Args:
            merged_json_path: ``merged.json`` 文件路径。
            pdf_path: ``source.pdf`` 文件路径（用于读取页面尺寸）。

        Returns:
            ``{page_str: [{type, content, bbox}, ...]}`` 字典。
            bbox 为 ``[x1, y1, x2, y2]`` 归一化到 [0, 1]。

        Raises:
            FileNotFoundError: 文件不存在。
            ValueError: 页数不匹配或数据格式错误。
        """
        merged_json_path = Path(merged_json_path)
        pdf_path = Path(pdf_path)
        if not merged_json_path.exists():
            raise FileNotFoundError(f"merged.json 不存在: {merged_json_path}")
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

        with merged_json_path.open("r", encoding="utf-8") as f:
            pages_data: list[list[dict]] = json.load(f)

        # 读取 PDF 每页尺寸
        page_sizes = GlmOcrNormalizer._get_page_sizes(pdf_path)
        if len(page_sizes) != len(pages_data):
            logger.warning(
                "PDF 页数(%d)与 merged.json 页数(%d)不匹配，按 merged.json 为准",
                len(page_sizes), len(pages_data),
            )

        result: dict[str, list[dict]] = {}
        total_blocks = 0

        for page_idx, page_blocks in enumerate(pages_data, start=1):
            page_str = str(page_idx)
            width, height = page_sizes[page_idx - 1] if page_idx <= len(page_sizes) else (1000.0, 1000.0)
            blocks: list[dict] = []

            for block in page_blocks:
                native_label = block.get("native_label", "") or block.get("label", "")
                popo_type = _LABEL_TYPE_MAP.get(native_label, "text")
                content = block.get("content", "") or ""
                bbox_2d = block.get("bbox_2d", [0, 0, 0, 0])

                # 归一化 bbox 到 [0, 1]
                bbox = GlmOcrNormalizer._normalize_bbox(bbox_2d, width, height)

                # 表格内容校验：确保是 HTML 格式
                if popo_type == "table" and not content.strip().lower().startswith("<table"):
                    content = f"<table>{content}</table>"

                blocks.append({
                    "type": popo_type,
                    "content": content,
                    "bbox": bbox,
                })
                total_blocks += 1

            result[page_str] = blocks

        logger.info(
            "GLM-OCR 归一化完成",
            extra={
                "pages": len(result),
                "total_blocks": total_blocks,
                "pdf": str(pdf_path),
            },
        )
        return result

    @staticmethod
    def _get_page_sizes(pdf_path: Path) -> list[tuple[float, float]]:
        """读取 PDF 每页的宽高（像素）。

        Args:
            pdf_path: PDF 文件路径。

        Returns:
            [(width, height), ...] 列表。
        """
        sizes: list[tuple[float, float]] = []
        doc = fitz.open(str(pdf_path))
        try:
            for page in doc:
                rect = page.rect
                sizes.append((rect.width, rect.height))
        finally:
            doc.close()
        return sizes

    @staticmethod
    def _normalize_bbox(bbox_2d: list, width: float, height: float) -> list[float]:
        """将像素坐标归一化到 [0, 1]。

        Args:
            bbox_2d: ``[x1, y1, x2, y2]`` 像素坐标。
            width: 页面宽度（像素）。
            height: 页面高度（像素）。

        Returns:
            ``[x1, y1, x2, y2]`` 归一化坐标，值域 [0, 1]。
        """
        if not bbox_2d or len(bbox_2d) < 4:
            return [0.0, 0.0, 0.0, 0.0]

        x1, y1, x2, y2 = bbox_2d[:4]
        w = max(width, 1.0)
        h = max(height, 1.0)

        return [
            max(0.0, min(1.0, float(x1) / w)),
            max(0.0, min(1.0, float(y1) / h)),
            max(0.0, min(1.0, float(x2) / w)),
            max(0.0, min(1.0, float(y2) / h)),
        ]


# 模块级单例
glm_ocr_normalizer = GlmOcrNormalizer()
