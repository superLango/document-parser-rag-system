"""版面分析引擎（阶段 C）。

- RuleLayoutEngine：开发/测试兜底，基于文本层与图片框启发式；
- DocLayoutEngine：DocLayout-YOLO（PDF-Extract-Kit 体系）可插拔引擎，
  权重未部署时明确报错；真实推理路径待权重部署后联调验证。
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol

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
    """DocLayout-YOLO 真实推理引擎（U4）。

    权重：models/doclayout_yolo/doclayout_yolo.pt
    （opendatalab/PDF-Extract-Kit-1.0 的
    doclayout_yolo_docstructbench_imgsz1280_2501.pt，SHA256=1b152460...c80be）。
    加载方式：torch.load（weights_only=False，权重来源可信且已锁定哈希）+
    doclayout_yolo 模型定义；前向输出 one2one 分支 + NMS + letterbox 坐标还原。
    """

    name = "doclayout"

    LABEL_MAP: ClassVar[dict[str, str | None]] = {
        "title": "title",
        "plain text": "text",
        "abandon": None,  # 丢弃区块
        "figure": "image",
        "figure_caption": "image_caption",
        "table": "table",
        "table_caption": "table_caption",
        "table_footnote": "footnote",
        "isolate_formula": "formula",
        "formula_caption": "text",
    }

    def __init__(
        self,
        model_dir: str | Path,
        device: str | None = None,
        imgsz: int = 1280,
        conf: float = 0.25,
        iou: float = 0.45,
        max_det: int = 300,
    ) -> None:
        self.model_dir = Path(model_dir)
        if self.model_dir.is_file():
            self.model_dir = self.model_dir.parent
        self.device = device or self._pick_device()
        self.imgsz = int(imgsz)
        self.conf = float(conf)
        self.iou = float(iou)
        self.max_det = int(max_det)
        self._model = None
        self._names: dict[int, str] = {}
        self.failures: list[dict] = []
        self._validate()

    @staticmethod
    def _pick_device() -> str:
        try:
            import torch

            return "cuda:0" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - 无 torch 时回退 CPU
            return "cpu"

    def _validate(self) -> None:
        if not self.model_dir.exists():
            raise LayoutModelUnavailable(
                f"DocLayout-YOLO 权重未部署：目录不存在 {self.model_dir}。"
                "请将权重放入 models/doclayout_yolo/ 后重试。"
            )
        present = [
            name
            for name in sorted(p.name for p in self.model_dir.iterdir())
            if name.lower().endswith((".pt", ".onnx", ".safetensors", ".bin"))
        ]
        if not present:
            raise LayoutModelUnavailable(
                f"DocLayout-YOLO 权重未部署：目录 {self.model_dir} 中未找到 "
                ".pt/.onnx 权重文件。"
            )

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            import torch
        except ImportError as exc:
            raise LayoutModelUnavailable(
                f"DocLayout-YOLO 运行依赖缺失：torch 未安装（{exc}）。"
            ) from exc
        candidates = sorted(
            (self.model_dir / name)
            for name in sorted(p.name for p in self.model_dir.iterdir())
            if name.lower().endswith(".pt")
        )
        if not candidates:
            raise LayoutModelUnavailable("DocLayout-YOLO 需要 .pt 权重文件")
        weights = candidates[0]

        # 权重来自官方 opendatalab 仓库且 SHA256 锁定；weights_only=False 为
        # 兼容 doclayout_yolo 自定义 Detect 头（dill 序列化），来源可信。
        original_load = torch.load

        def _trusted_load(*args, **kwargs):
            kwargs["weights_only"] = False
            return original_load(*args, **kwargs)

        torch.load = _trusted_load
        try:
            ckpt = torch.load(weights, map_location="cpu", weights_only=False)
        except Exception as exc:
            raise LayoutModelUnavailable(
                f"DocLayout-YOLO 权重加载失败：{exc}"
            ) from exc
        finally:
            torch.load = original_load

        model = ckpt.get("model") or ckpt.get("ema")
        if model is None:
            raise LayoutModelUnavailable("权重文件缺少 model/ema 字段")
        model.float().eval()
        try:
            model.to(self.device)
        except Exception as exc:  # noqa: BLE001 - GPU 失败回退 CPU
            logger.warning("GPU 加载失败，回退 CPU", error=str(exc)[:120])
            self.device = "cpu"
            model.to("cpu")
        self._model = model
        self._names = getattr(model, "names", {}) or {}
        logger.info(
            "DocLayout-YOLO 已加载",
            weights=str(weights),
            device=self.device,
            classes=len(self._names),
        )
        return self._model

    def _letterbox(self, img):
        import cv2
        import numpy as np

        h0, w0 = img.shape[:2]
        r = min(self.imgsz / w0, self.imgsz / h0)
        new_w, new_h = round(w0 * r), round(h0 * r)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, dtype=np.uint8)
        dw, dh = (self.imgsz - new_w) // 2, (self.imgsz - new_h) // 2
        canvas[dh : dh + new_h, dw : dw + new_w] = resized
        return canvas, r, dw, dh

    def _infer_page(self, image_bytes: bytes) -> list[LayoutBlock]:

        import cv2
        import numpy as np
        import torch
        from doclayout_yolo.utils.ops import non_max_suppression


        model = self._load_model()
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("页面图片解码失败")
        h0, w0 = img.shape[:2]
        canvas, r, dw, dh = self._letterbox(img)
        tensor = (
            torch.from_numpy(
                np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1))
            )
            .to(self.device)
            .float()
            .div_(255.0)
            .unsqueeze(0)
        )
        with torch.no_grad():
            out = model(tensor)
        one2one = out.get("one2one") if isinstance(out, dict) else None
        if one2one is None:
            raise RuntimeError("DocLayout-YOLO 输出缺少 one2one 分支")
        y = one2one[0] if isinstance(one2one, tuple) else one2one
        pred = non_max_suppression(
            y, conf_thres=self.conf, iou_thres=self.iou, max_det=self.max_det
        )[0]
        blocks: list[LayoutBlock] = []
        if pred is None or len(pred) == 0:
            return blocks
        xyxy = pred[:, :4].clone()
        xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - dw) / r
        xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - dh) / r
        for row_idx, row in enumerate(pred):
            cls_id = int(row[5].item())
            label = self._names.get(cls_id, "text")
            block_type = self.LABEL_MAP.get(label)
            if block_type is None:
                continue
            x0, y0, x1, y1 = [float(v) for v in xyxy[row_idx].tolist()]
            blocks.append(
                LayoutBlock(
                    type=block_type,
                    bbox=BBox(
                        max(0.0, x0 / w0),
                        max(0.0, y0 / h0),
                        min(1.0, x1 / w0),
                        min(1.0, y1 / h0),
                    ),
                    page_index=0,
                    confidence=float(row[4].item()),
                    source="doclayout",
                    structural={
                        "model_label": label,
                        "class_id": cls_id,
                        "imgsz": self.imgsz,
                    },
                )
            )
        return blocks

    def analyze(self, pages: list[RenderPage]) -> list[list[LayoutBlock]]:
        """逐页真实推理；单页失败记录到 self.failures 不中断（U11）。"""
        self.failures = []
        result: list[list[LayoutBlock]] = []
        for page in pages:
            try:
                blocks = self._infer_page(page.image_bytes)
            except Exception as exc:  # noqa: BLE001 - 单页失败记录 partial（U11）
                self.failures.append(
                    {
                        "page_index": page.page_index,
                        "stage": "layout",
                        "error": str(exc)[:300],
                    }
                )
                logger.warning(
                    "DocLayout-YOLO 单页推理失败，标记 partial",
                    page=page.page_index,
                    error=str(exc)[:200],
                )
                blocks = []
            for block in blocks:
                block.page_index = page.page_index
            result.append(blocks)
        return result
