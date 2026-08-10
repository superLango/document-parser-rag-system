"""版面分析引擎（阶段 C）。

- RuleLayoutEngine：开发/测试兜底，基于文本层与图片框启发式；
- DocLayoutEngine：DocLayout-YOLO（PDF-Extract-Kit 体系）可插拔引擎，
  权重未部署时明确报错；真实推理路径待权重部署后联调验证。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.core.logging import get_logger

from .errors import LayoutModelUnavailable
from .types import BBox, LayoutBlock, RenderPage, TextBlock

logger = get_logger(__name__)

EXPECTED_MODEL_FILES = (
    "model.onnx",
    "best.onnx",
    "doclayout_yolo.onnx",
    "config.json",
    "model.safetensors",
    "pytorch_model.bin",
)


class LayoutEngine(Protocol):
    name: str

    def analyze(self, pages: list[RenderPage]) -> list[list[LayoutBlock]]: ...


def _infer_title_level(font_size: float, max_font: float) -> int:
    """按字号相对关系推断标题层级（1=最大，最小 1）。"""
    if max_font <= 0:
        return 1
    ratio = font_size / max_font
    if ratio >= 0.9:
        return 1
    if ratio >= 0.78:
        return 2
    if ratio >= 0.66:
        return 3
    return 4


class RuleLayoutEngine:
    """规则兜底引擎：文本层 + 图片框启发式。"""

    name = "rule"

    def __init__(
        self,
        title_font_threshold: float = 14.0,
        image_min_area: float = 800.0,
    ) -> None:
        self.title_font_threshold = float(title_font_threshold)
        self.image_min_area = float(image_min_area)

    def _classify_text(
        self, block: TextBlock, page: RenderPage, max_font: float
    ) -> LayoutBlock:
        nb = block.bbox.normalized(page.width, page.height)
        content = block.text.strip()
        # 标题判定：达到正文最大字号的 85% 以上，或独立大字号（>=18）；
        # 短文本限定避免长段落误判（规则引擎兜底，真实模型在 Phase 3 校准）。
        is_title = (
            block.font_size >= max(max_font * 0.85, self.title_font_threshold)
            or block.font_size >= 18.0
        ) and len(content) <= 60
        if is_title:
            return LayoutBlock(
                type="title",
                bbox=nb,
                page_index=page.page_index,
                confidence=0.8,
                content=content,
                source="text",
                structural={
                    "title_level": _infer_title_level(
                        block.font_size, max_font
                    ),
                    "font_size": round(block.font_size, 2),
                    "font_name": block.font_name,
                },
            )
        return LayoutBlock(
            type="text",
            bbox=nb,
            page_index=page.page_index,
            confidence=0.8,
            content=content,
            source="text",
            structural={"font_size": round(block.font_size, 2)},
        )

    def analyze(self, pages: list[RenderPage]) -> list[list[LayoutBlock]]:
        result: list[list[LayoutBlock]] = []
        for page in pages:
            page_blocks: list[LayoutBlock] = []
            max_font = max(
                (b.font_size for b in page.text_blocks), default=0.0
            )
            for text_block in page.text_blocks:
                page_blocks.append(
                    self._classify_text(text_block, page, max_font)
                )
            page_area = max(page.width * page.height, 1.0)
            for img_box in page.image_boxes:
                nb = img_box.normalized(page.width, page.height)
                if nb.area * page_area < self.image_min_area:
                    continue
                # 与文本高度重叠的图片视为装饰/印章，不单独成块
                if any(
                    tb.bbox.overlap_ratio(img_box) > 0.55
                    for tb in page.text_blocks
                ):
                    continue
                page_blocks.append(
                    LayoutBlock(
                        type="image",
                        bbox=nb,
                        page_index=page.page_index,
                        confidence=0.9,
                        source="image",
                        structural={
                            "width_px": round(nb.width * page.width, 1),
                            "height_px": round(nb.height * page.height, 1),
                        },
                    )
                )
            result.append(page_blocks)
        return result


class DocLayoutEngine:
    """DocLayout-YOLO 适配引擎（PDF-Extract-Kit 体系，U4）。

    当前环境未部署权重：构造时校验权重目录，缺失即报错。
    onnxruntime 推理适配代码已提供，但需部署权重后联调验证。
    """

    name = "doclayout"

    def __init__(self, model_dir: str | Path) -> None:
        self.model_dir = Path(model_dir)
        self._validate()

    def _validate(self) -> None:
        if not self.model_dir.exists():
            raise LayoutModelUnavailable(
                f"DocLayout-YOLO 权重未部署：目录不存在 {self.model_dir}。"
                "请设置 PARSEKIT_LAYOUT_MODEL_DIR 指向权重目录后重试。"
            )
        present = [
            name
            for name in EXPECTED_MODEL_FILES
            if (self.model_dir / name).exists()
        ]
        if not present:
            raise LayoutModelUnavailable(
                f"DocLayout-YOLO 权重未部署：目录 {self.model_dir} 中未找到"
                f"预期文件 {EXPECTED_MODEL_FILES}。"
            )

    def analyze(self, pages: list[RenderPage]) -> list[list[LayoutBlock]]:
        """调用 DocLayout-YOLO 推理（适配代码，部署权重后联调验证）。"""
        try:
            import io

            import numpy as np
            import onnxruntime as ort
            from PIL import Image
        except ImportError as exc:
            raise LayoutModelUnavailable(
                f"DocLayout-YOLO 运行依赖缺失：{exc}。"
                "请安装 onnxruntime、numpy、Pillow。"
            ) from exc

        model_path = self.model_dir / "model.onnx"
        if not model_path.exists():
            candidates = [
                self.model_dir / name
                for name in EXPECTED_MODEL_FILES
                if (self.model_dir / name).exists()
            ]
            if not candidates:
                raise LayoutModelUnavailable("DocLayout-YOLO ONNX 权重缺失")
            model_path = candidates[0]

        session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        input_name = session.get_inputs()[0].name
        input_shape = session.get_inputs()[0].shape
        target_size = int(input_shape[-1] or 640)

        result: list[list[LayoutBlock]] = []
        for page in pages:
            img = Image.open(io.BytesIO(page.image_bytes)).convert("RGB")
            resized = img.resize((target_size, target_size))
            arr = np.asarray(resized, dtype=np.float32) / 255.0
            arr = np.transpose(arr, (2, 0, 1))[None, ...]
            outputs = session.run(None, {input_name: arr})
            blocks = self._parse_outputs(outputs, page, target_size)
            result.append(blocks)
        logger.info(
            "DocLayout-YOLO 推理完成（适配路径，待真实权重联调）",
            pages=len(pages),
        )
        return result

    def _parse_outputs(self, outputs, page: RenderPage, size: int) -> list[LayoutBlock]:
        """解析 YOLO 输出为版面块（真实权重联调时校准）。"""
        raise LayoutModelUnavailable(
            "DocLayout-YOLO 推理输出解析尚未在真实权重上验证，"
            "请完成权重部署联调后再启用 PARSEKIT_LAYOUT_ENGINE=doclayout。"
        )
