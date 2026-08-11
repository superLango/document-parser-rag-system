"""PP-DocLayoutV3 版面分析引擎（唯一版面引擎，2026-08 定版）。

模型：PaddlePaddle/PP-DocLayoutV3_safetensors
- 架构：RT-DETR 检测 + 阅读顺序 head；支持非平面文档、多点框
  （polygon_points）、端到端阅读顺序；
- 25 类版面元素（id2label 见 config.json），输出按阅读顺序排列；
- transformers 官方集成：AutoImageProcessor + AutoModelForObjectDetection，
  post_process_object_detection 返回 boxes/labels/scores/order_seq/polygon_points。

历史：V2/DocLayout-YOLO/Rule 引擎已移除（可插拔代码清理），本引擎为唯一实现。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from app.core.logging import get_logger

from .errors import LayoutModelUnavailable
from .types import BBox, LayoutBlock, RenderPage

logger = get_logger(__name__)

MODEL_REPO = "PaddlePaddle/PP-DocLayoutV3_safetensors"
EXPECTED_SHA256 = "5ea422c6cc5fe759a47e1357c35639b58173508e025a3131cbe4b6ac59e2b85e"


class PPDocLayoutEngine:
    """PP-DocLayoutV3 真实推理引擎（transformers 加载）。

    权重：models/pp_doclayoutv3/model.safetensors
    （官方 safetensors 版，SHA256 锁定，见 EXPECTED_SHA256）。
    """

    name = "ppdoclayoutv3"

    LABEL_MAP: ClassVar[dict[str, str | None]] = {
        "doc_title": "title",
        "paragraph_title": "title",
        "title": "title",
        "abstract": "text",
        "algorithm": "text",
        "content": "text",
        "text": "text",
        "number": "text",
        "aside_text": "aside_text",
        "reference": "footnote",  # 参考文献条目按脚注类处理
        "reference_content": "footnote",
        "footnote": "footnote",
        "vision_footnote": "footnote",
        "figure_title": "image_caption",
        "table_caption": "table_caption",
        "image": "image",
        "chart": "image",  # 图表并入图片类，交由 OCR 识别
        "table": "table",
        "formula": "formula",
        "formula_number": "formula",  # 编号并入公式块
        "header": None,  # 页眉页脚由 header_footer 阶段处理，丢弃
        "footer": None,
        "seal": None,  # 印章/装饰，丢弃
    }

    def __init__(
        self,
        model_dir: str | Path,
        device: str | None = None,
        conf_threshold: float = 0.4,
        verify_hash: bool = True,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.device = device or self._pick_device()
        self.conf_threshold = float(conf_threshold)
        self.verify_hash = bool(verify_hash)
        self._model: Any | None = None
        self._processor: Any | None = None
        self._id2label: dict[int, str] = {}
        self.failures: list[dict] = []
        self._infer_lock = threading.Lock()
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
                f"PP-DocLayoutV3 权重未部署：目录不存在 {self.model_dir}。"
                "请将权重放入 models/pp_doclayoutv3/ 后重试。"
            )
        weight = self.model_dir / "model.safetensors"
        if not weight.exists():
            raise LayoutModelUnavailable(
                f"PP-DocLayoutV3 权重未部署：缺少 {weight}。"
                f"请从 {MODEL_REPO} 下载。"
            )
        if self.verify_hash:
            self._verify_hash(weight)

    def _verify_hash(self, weight: Path) -> None:
        import hashlib

        h = hashlib.sha256()
        with weight.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual != EXPECTED_SHA256:
            raise LayoutModelUnavailable(
                f"PP-DocLayoutV3 权重校验失败：期望 {EXPECTED_SHA256[:16]}...，"
                f"实际 {actual[:16]}...。请重新下载官方权重。"
            )

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from transformers import (
                AutoImageProcessor,
                AutoModelForObjectDetection,
            )
        except ImportError as exc:
            raise LayoutModelUnavailable(
                "PP-DocLayoutV3 运行依赖缺失：transformers 未安装"
                f"（{exc}）。"
            ) from exc
        try:
            processor = AutoImageProcessor.from_pretrained(str(self.model_dir))
            model = AutoModelForObjectDetection.from_pretrained(
                str(self.model_dir),
                low_cpu_mem_usage=False,
                device_map=None,
            )
            self._processor = processor
            self._model = model
            model.eval()
            model.to(self.device)
            # 强制所有参数/buffer 到目标设备（transformers 5.x lazy 加载可能残留 CPU）
            for module in model.modules():
                module.to(self.device)
            import torch

            torch.cuda.synchronize() if self.device.startswith("cuda") else None
        except Exception as exc:
            raise LayoutModelUnavailable(
                f"PP-DocLayoutV3 权重加载失败：{exc}"
            ) from exc
        self._id2label = {
            int(k): v for k, v in model.config.id2label.items()
        }
        self._model = model
        logger.info(
            "PP-DocLayoutV3 已加载",
            model_dir=str(self.model_dir),
            device=self.device,
            classes=len(self._id2label),
        )
        return self._model

    def _map_label(self, label: str) -> str | None:
        return self.LABEL_MAP.get(label)

    def _infer_page(
        self, image_bytes: bytes, width: float, height: float
    ) -> list[LayoutBlock]:
        """单页推理；返回按阅读顺序（order_seq）排列的内部类型块。"""
        from io import BytesIO

        from PIL import Image

        model = self._load_model()
        processor = self._processor
        if model is None or processor is None:
            raise RuntimeError("PP-DocLayoutV3 模型未加载")
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        # 归一化基准必须用图像实际像素尺寸（pt 尺寸与像素尺寸不同，DPI=200）
        img_w, img_h = img.size
        inputs = processor(images=img, return_tensors="pt").to(self.device)
        with _no_grad():
            outputs = model(**inputs)
        # post_process_object_detection 的 target_sizes 期望 (高, 宽)；
        # 传 img.size（PIL 为 (宽, 高)）会交换宽高，必须传 img.size[::-1]。
        # 输出为原图像素坐标，且内部已按 order_seq 升序（阅读顺序）排列。
        # threshold 用于过滤低置信度框（官方默认 0.5；调低提升召回）
        results = processor.post_process_object_detection(
            outputs,
            threshold=self.conf_threshold,
            target_sizes=[img.size[::-1]],
        )[0]

        boxes = results["boxes"].detach().cpu()
        labels = results["labels"].detach().cpu()
        scores = results["scores"].detach().cpu()

        # 输出已按阅读顺序排列（post_process 内部按 order_seq 升序排序）
        n = len(boxes)
        blocks: list[LayoutBlock] = []
        for i in range(n):
            label = self._id2label.get(int(labels[i]), "text")
            block_type = self._map_label(label)
            if block_type is None:
                continue
            x0, y0, x1, y1 = [float(v) for v in boxes[i].tolist()]
            # 坐标是原图像素（target_sizes 还原），按图像实际像素归一化 [0,1]
            x0 = max(0.0, min(img_w, x0))
            y0 = max(0.0, min(img_h, y0))
            x1 = max(0.0, min(img_w, x1))
            y1 = max(0.0, min(img_h, y1))
            blocks.append(
                LayoutBlock(
                    type=block_type,
                    bbox=BBox(
                        max(0.0, x0 / img_w),
                        max(0.0, y0 / img_h),
                        min(1.0, x1 / img_w),
                        min(1.0, y1 / img_h),
                    ),
                    page_index=0,
                    confidence=float(scores[i]),
                    source=self.name,
                    structural={
                        "model_label": label,
                        "class_id": int(labels[i]),
                        "engine": self.name,
                    },
                )
            )
        return blocks

    def analyze(
        self,
        pages: list[RenderPage],
        progress: Callable[[str, int | None, int | None], None] | None = None,
    ) -> list[list[LayoutBlock]]:
        """逐页真实推理；单页失败记录到 self.failures 不中断（U11）。

        整篇持推理锁：多任务并发 forward 同一模型实例时，transformers 5.x
        lazy 权重加载会产生设备竞争（weight on cpu）；整篇串行推理保证稳定
        （参考 MinerU ModelSingleton 推理锁）。
        """
        self.failures = []
        result: list[list[LayoutBlock]] = []
        with self._infer_lock:
            for page in pages:
                if progress:
                    progress("layout", page.page_index, len(pages))
                try:
                    blocks = self._infer_page(
                        page.image_bytes, page.width, page.height
                    )
                except Exception as exc:  # noqa: BLE001 - 单页失败记录 partial（U11）
                    self.failures.append(
                        {
                            "page_index": page.page_index,
                            "stage": "layout",
                            "error": str(exc)[:300],
                        }
                    )
                    logger.warning(
                        "PP-DocLayoutV3 单页推理失败，标记 partial",
                        page=page.page_index,
                        error=str(exc)[:200],
                    )
                    blocks = []
                for block in blocks:
                    block.page_index = page.page_index
                result.append(blocks)
        return result


class _no_grad:
    """torch.no_grad 的轻量上下文（无 torch 时也不报错）。"""

    def __enter__(self):
        import torch

        self._ctx = torch.no_grad()
        return self._ctx.__enter__()

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)



def _model_input_size(processor) -> tuple[float, float]:
    """返回 PP-DocLayoutV3 预处理的目标尺寸（宽, 高）。

    transformers 实现的 image_processor.size 为 800x800（SizeDict）。
    """
    size = getattr(processor, "size", None)
    if isinstance(size, dict):
        h = int(size.get("height", 800))
        w = int(size.get("width", 800))
        return float(w), float(h)
    if isinstance(size, (list, tuple)) and len(size) == 2:
        return float(size[0]), float(size[1])
    return 800.0, 800.0
