"""OCR 识别服务模块。

本模块封装 PaddleOCR-VL 视觉语言模型，提供图像文字识别与版面分析能力，
作为文档解析与 RAG 系统的 Phase 2 文本抽取入口。

模型加载策略（双后端，按任务要求 #2 / #5 实现）：

1. **优先 transformers 路径**：使用 ``AutoModelForCausalLM`` / ``AutoProcessor``
   以 ``trust_remote_code=True`` 加载本地 ``PaddleOCR-VL`` 模型（任务要求 #2）。
2. **回退 PaddleOCRVL pipeline 路径**：当本地 transformers 版本与自定义模型代码
   不兼容时，自动回退到 ``paddleocr.PaddleOCRVL`` 高层 API（任务要求 #5）。
   该 pipeline 内部同时驱动 ``PP-DocLayoutV2`` 版面检测与 ``PaddleOCR-VL-0.9B``
   文字识别，是官方推荐且更稳定的推理方式。

经实测，当前 venv 中的 transformers 5.12.1 与模型自定义的 ``RotaryEmbedding``
实现存在 API 不兼容（``ROPE_INIT_FUNCTIONS`` 缺少 ``default`` 键、模型类未实现
``compute_default_rope_parameters``），因此实际运行时会自动回退到 pipeline 后端。

所有阻塞式模型调用均通过 ``asyncio.to_thread`` 交由线程池执行，避免阻塞事件循环；
模型与布局检测器均采用懒加载，模块导入时不产生 GPU 副作用。

使用示例：
    from app.services.ocr_service import ocr_service

    text = await ocr_service.recognize(image_bytes)
    layout = await ocr_service.recognize_with_layout(image_bytes)
    await ocr_service.warmup()
"""

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

# 任务类型 → 提示词映射（transformers 后端按元素识别时使用）
# 与 PaddleOCR-VL 官方 README 提供的提示词保持一致
_TASK_PROMPTS: dict[str, str] = {
    "ocr": "OCR:",
    "table": "Table Recognition:",
    "formula": "Formula Recognition:",
    "chart": "Chart Recognition:",
}

# PP-DocLayoutV2 细粒度标签 → 四类布局类型的归并映射
# 任务要求布局项 type 仅取 text / table / figure / title 之一
_LABEL_TYPE_MAP: dict[str, str] = {
    # 标题类
    "doc_title": "title",
    "paragraph_title": "title",
    "figure_title": "title",
    # 表格类
    "table": "table",
    # 图像/图表类
    "image": "figure",
    "chart": "figure",
    "seal": "figure",
    "header_image": "figure",
    "footer_image": "figure",
    # 其余标签（text / aside_text / content / vertical_text / reference /
    # reference_content / footnote / header / footer / abstract / algorithm /
    # number / formula_number / vision_footnote / display_formula /
    # inline_formula）均归为 text
}


def _label_to_type(label: str) -> str:
    """将 PP-DocLayoutV2 的细粒度标签归并为四类布局类型。

    Args:
        label: PP-DocLayoutV2 输出的标签名，例如 "text" / "table" / "doc_title"。

    Returns:
        str: 归并后的类型，取值为 "text" / "table" / "figure" / "title"。
    """
    return _LABEL_TYPE_MAP.get(label, "text")


def _prompt_for_label(label: str) -> str:
    """根据布局标签选择对应的 VL 识别提示词（transformers 后端使用）。

    Args:
        label: PP-DocLayoutV2 输出的标签名。

    Returns:
        str: 对应的识别提示词，如 "OCR:" / "Table Recognition:"。
    """
    item_type = _label_to_type(label)
    if item_type == "table":
        return _TASK_PROMPTS["table"]
    if item_type == "figure" and label == "chart":
        return _TASK_PROMPTS["chart"]
    # text / title / 其余均使用通用 OCR 提示词
    return _TASK_PROMPTS["ocr"]


def _block_field(block: Any, name: str, default: Any = None) -> Any:
    """兼容地从版面块对象中取字段。

    PaddleOCRVL pipeline 返回的版面块为 ``PaddleOCRVLBlock`` 对象（属性访问），
    但不同 paddlex 版本可能返回 dict。此处同时兼容两种形式。

    Args:
        block: 版面块对象。
        name: 字段名，例如 "label" / "bbox" / "content"。
        default: 字段缺失时的默认值。

    Returns:
        Any: 字段值；缺失时返回 ``default``。
    """
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


class OCRService:
    """OCR 识别服务封装。

    采用懒加载机制延迟模型加载：在首次实际调用 ``warmup`` / ``recognize``
    等方法时才初始化模型权重与推理后端，确保模块导入时不占用 GPU 资源。

    后端选择逻辑见模块文档字符串：优先 transformers，失败回退 PaddleOCRVL pipeline。
    运行时可通过 ``self._backend`` 区分当前生效的后端。

    Attributes:
        model_path: PaddleOCR-VL 模型目录路径。
        _model: transformers 后端的模型实例（懒加载）。
        _processor: transformers 后端的 processor 实例（懒加载）。
        _pipeline: PaddleOCRVL pipeline 实例（懒加载，回退后端使用）。
        _layout_detector: 独立的 PP-DocLayoutV2 布局检测器（仅 transformers 后端使用）。
        _backend: 当前生效的后端标识，"transformers" 或 "paddleocr-vl"。
        _loaded: 模型是否已完成加载。
    """

    def __init__(self, model_path: str | None = None) -> None:
        """初始化 OCR 服务，仅保存配置不加载模型。

        Args:
            model_path: PaddleOCR-VL 模型目录路径。未提供时回退到
                ``settings.PADDLE_OCR_MODEL_DIR``。
        """
        self.model_path: str = model_path or settings.PADDLE_OCR_MODEL_DIR
        # transformers 后端组件
        self._model: Any = None
        self._processor: Any = None
        # pipeline 后端组件
        self._pipeline: Any = None
        # transformers 后端专用布局检测器
        self._layout_detector: Any = None
        # 当前生效的后端
        self._backend: str | None = None
        self._loaded: bool = False
        # 序列化模型推理，避免多请求并发调用同一 GPU 模型导致状态损坏
        self._inference_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """懒加载 PaddleOCR-VL 模型。

        优先尝试 transformers 路径（任务要求 #2），失败则回退到 PaddleOCRVL
        pipeline（任务要求 #5）。加载完成后记录生效后端。
        """
        if self._loaded:
            return
        try:
            self._load_via_transformers()
            self._backend = "transformers"
            logger.info(
                "OCR 模型加载完成（transformers 后端）",
                model_path=self.model_path,
            )
        except Exception as exc:
            # transformers 与自定义模型代码存在兼容性问题，回退到 pipeline
            logger.warning(
                "transformers 加载 PaddleOCR-VL 失败，回退到 PaddleOCRVL pipeline",
                model_path=self.model_path,
                error=str(exc),
            )
            self._load_via_pipeline()
            self._backend = "paddleocr-vl"
            logger.info(
                "OCR 模型加载完成（paddleocr-vl 后端）",
                model_path=self.model_path,
            )
        self._loaded = True

    def _load_via_transformers(self) -> None:
        """通过 transformers 加载 PaddleOCR-VL 模型与 processor。

        采用 ``trust_remote_code=True`` 加载本地自定义模型类
        ``PaddleOCRVLForConditionalGeneration``，dtype 使用模型配置原生
        ``bfloat16``（config.json 中 ``torch_dtype`` 字段），device 为 cuda。

        Raises:
            Exception: transformers 版本与自定义模型代码不兼容时抛出，
                由上层捕获后回退到 pipeline 后端。
        """
        # 兼容性补丁：transformers 5.x 移除了 ROPE_INIT_FUNCTIONS 中的 "default"
        # 键，但自定义 RotaryEmbedding 仍引用该键，此处按需补注册
        self._patch_rope_default()

        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        logger.info("通过 transformers 加载 PaddleOCR-VL", model_path=self.model_path)
        self._processor = AutoProcessor.from_pretrained(
            self.model_path, trust_remote_code=True
        )
        self._model = (
            AutoModelForCausalLM.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                dtype=torch.bfloat16,
                device="cuda",
            )
            .eval()
        )

    @staticmethod
    def _patch_rope_default() -> None:
        """为 transformers 5.x 注册缺失的 "default" RoPE 初始化函数。

        自定义 ``modeling_paddleocr_vl.py`` 中的 ``RotaryEmbedding`` 会直接查表
        ``ROPE_INIT_FUNCTIONS[self.rope_type]``，而 transformers 5.12.1 已移除
        ``default`` 键。此处按官方语义补一个无缩放的默认实现以消除 KeyError。
        """
        from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS

        if "default" in ROPE_INIT_FUNCTIONS:
            return
        import torch

        def _default_rope_parameters(  # type: ignore[no-untyped-def]
            config=None, device=None, seq_len=None, layer_type=None
        ) -> tuple["torch.Tensor", float]:
            base = getattr(config, "rope_theta", 10000.0) or 10000.0
            head_dim = getattr(config, "head_dim", None) or (
                config.hidden_size // config.num_attention_heads
            )
            partial_rotary_factor = (
                getattr(config, "partial_rotary_factor", 1.0) or 1.0
            )
            dim = int(head_dim * partial_rotary_factor)
            arange = torch.arange(0, dim, 2, device=device, dtype=torch.float32)
            inv_freq = 1.0 / (base ** (arange / dim))
            return inv_freq, 1.0

        ROPE_INIT_FUNCTIONS["default"] = _default_rope_parameters

    def _load_via_pipeline(self) -> None:
        """通过 PaddleOCRVL pipeline 加载模型（回退后端）。

        同时配置本地 ``PP-DocLayoutV2`` 版面检测器与 ``PaddleOCR-VL`` 识别模型，
        关闭方向校正、去畸变、图表与印章识别等非必要子模块以提升推理速度。
        """
        from paddleocr import PaddleOCRVL

        layout_dir = str(Path(self.model_path) / "PP-DocLayoutV2")
        logger.info(
            "通过 PaddleOCRVL pipeline 加载",
            model_path=self.model_path,
            layout_dir=layout_dir,
        )
        self._pipeline = PaddleOCRVL(
            pipeline_version="v1",
            layout_detection_model_dir=layout_dir,
            vl_rec_model_dir=self.model_path,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_chart_recognition=False,
            use_seal_recognition=False,
        )

    def _load_layout_detector(self) -> None:
        """懒加载独立的 PP-DocLayoutV2 布局检测器（仅 transformers 后端使用）。

        pipeline 后端的版面检测已内置于 PaddleOCRVL，无需单独加载。
        """
        if self._layout_detector is not None:
            return
        from paddleocr import LayoutDetection

        layout_dir = str(Path(self.model_path) / "PP-DocLayoutV2")
        self._layout_detector = LayoutDetection(
            model_name="PP-DocLayoutV2", model_dir=layout_dir
        )
        logger.info("布局检测模型加载完成", layout_dir=layout_dir)

    # ------------------------------------------------------------------
    # 图像工具
    # ------------------------------------------------------------------
    @staticmethod
    def _to_pil(image: bytes | Image.Image) -> Image.Image:
        """将输入统一转换为 RGB PIL 图像。

        Args:
            image: 字节流或 PIL 图像。

        Returns:
            Image.Image: RGB 模式的 PIL 图像。

        Raises:
            BusinessException: 字节流无法解析为图像时抛出。
        """
        try:
            if isinstance(image, Image.Image):
                return image.convert("RGB")
            return Image.open(BytesIO(image)).convert("RGB")
        except Exception as exc:
            raise BusinessException(
                message=f"无法解析输入图像: {exc}",
                code=ErrorCode.BUSINESS_UNSUPPORTED_FILE_TYPE,
            ) from exc

    # ------------------------------------------------------------------
    # transformers 后端推理
    # ------------------------------------------------------------------
    def _infer_transformers(self, image: Image.Image, prompt: str = "OCR:") -> str:
        """使用 transformers 模型对单张图像执行元素级识别。

        按 PaddleOCR-VL 官方用法构造 chat 消息，调用 ``apply_chat_template``
        与 ``model.generate`` 完成推理并解码文本。

        Args:
            image: RGB PIL 图像。
            prompt: 识别提示词，默认 "OCR:"，可选表格/公式/图表识别提示词。

        Returns:
            str: 识别得到的文本。
        """
        import torch

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        inputs = self._processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to("cuda")
        with torch.inference_mode():
            output_ids = self._model.generate(
                **inputs, max_new_tokens=1024, do_sample=False
            )
        return self._processor.batch_decode(output_ids, skip_special_tokens=True)[0]

    def _recognize_with_layout_transformers(self, image: Image.Image) -> dict:
        """transformers 后端的版面感知识别。

        流程：PP-DocLayoutV2 检测版面区域 → 按区域裁剪 → 逐区域调用 VL 模型
        识别（依据区域类型选择 OCR / 表格 / 图表提示词）。

        Args:
            image: RGB PIL 图像。

        Returns:
            dict: ``{"text": str, "layout": list[dict], "pages": int}``。
        """
        self._load_layout_detector()
        # LayoutDetection 仅接受 ndarray 或文件路径
        boxes_result = self._layout_detector.predict(np.array(image))
        boxes = boxes_result[0]["boxes"] if boxes_result else []

        layout_items: list[dict] = []
        text_parts: list[str] = []
        for box in boxes:
            coordinate = box.get("coordinate", [0, 0, 0, 0])
            x1, y1 = max(0, int(coordinate[0])), max(0, int(coordinate[1]))
            x2, y2 = (
                min(image.width, int(coordinate[2])),
                min(image.height, int(coordinate[3])),
            )
            if x2 <= x1 or y2 <= y1:
                continue
            crop = image.crop((x1, y1, x2, y2))
            label = box.get("label", "text")
            text = self._infer_transformers(crop, _prompt_for_label(label))
            layout_items.append(
                {
                    "type": _label_to_type(label),
                    "bbox": [x1, y1, x2, y2],
                    "text": text,
                }
            )
            text_parts.append(text)
        return {
            "text": "\n\n".join(text_parts),
            "layout": layout_items,
            "pages": 1,
        }

    # ------------------------------------------------------------------
    # pipeline 后端推理
    # ------------------------------------------------------------------
    def _run_pipeline(self, image: Image.Image) -> Any:
        """运行 PaddleOCRVL pipeline 对单张图像做版面+识别。

        Args:
            image: RGB PIL 图像。

        Returns:
            PaddleOCRVLResult: pipeline 输出结果对象。
        """
        # pipeline 接受 numpy ndarray
        results = list(self._pipeline.predict(np.array(image)))
        return results[0] if results else None

    def _infer_pipeline_text(self, image: Image.Image) -> str:
        """pipeline 后端：提取纯文本结果。

        Args:
            image: RGB PIL 图像。

        Returns:
            str: 识别得到的完整文本（markdown 形式）。
        """
        result = self._run_pipeline(image)
        if result is None:
            return ""
        markdown = result.markdown or {}
        return (markdown.get("markdown_texts") or "").strip()

    def _recognize_with_layout_pipeline(self, image: Image.Image) -> dict:
        """pipeline 后端的版面感知识别。

        直接复用 PaddleOCRVL 输出的 ``parsing_res_list``（每块含标签、bbox、
        已识别文本）与 ``markdown_texts``（全文），无需重复推理。

        Args:
            image: RGB PIL 图像。

        Returns:
            dict: ``{"text": str, "layout": list[dict], "pages": int}``。
        """
        result = self._run_pipeline(image)
        if result is None:
            return {"text": "", "layout": [], "pages": 0}
        parsing_list = result.get("parsing_res_list", []) or []
        layout_items: list[dict] = []
        for block in parsing_list:
            # parsing_res_list 中的元素为 PaddleOCRVLBlock 对象，
            # 字段以属性形式访问（label / bbox / content）
            label = _block_field(block, "label", "text")
            layout_items.append(
                {
                    "type": _label_to_type(label),
                    "bbox": list(_block_field(block, "bbox", []) or []),
                    "text": _block_field(block, "content", "") or "",
                }
            )
        markdown = result.markdown or {}
        full_text = (markdown.get("markdown_texts") or "").strip()
        page_count = result.get("page_count") or 1
        return {
            "text": full_text,
            "layout": layout_items,
            "pages": int(page_count),
        }

    # ------------------------------------------------------------------
    # 对外异步 API
    # ------------------------------------------------------------------
    async def warmup(self) -> None:
        """预热模型：加载模型并执行一次空推理以初始化 GPU。

        在服务启动时调用，避免首次真实请求承受加载延迟。
        """
        try:
            await asyncio.to_thread(self._load_model)
            # 构造一张占位图像触发一次完整推理，使 CUDA kernel 完成编译
            dummy = Image.new("RGB", (320, 100), "white")
            async with self._inference_lock:
                if self._backend == "transformers":
                    await asyncio.to_thread(
                        self._infer_transformers, dummy, _TASK_PROMPTS["ocr"]
                    )
                else:
                    await asyncio.to_thread(self._run_pipeline, dummy)
            logger.info("OCR 预热完成", backend=self._backend)
        except BusinessException:
            raise
        except Exception as exc:
            logger.error("OCR 预热失败", error=str(exc))
            raise BusinessException(
                message=f"OCR 预热失败: {exc}",
                code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
            ) from exc

    async def recognize(self, image: bytes | Image.Image) -> str:
        """识别单张图像中的文字。

        Args:
            image: 图像字节流或 PIL 图像。

        Returns:
            str: 识别得到的文本。
        """
        try:
            pil_image = self._to_pil(image)
            await asyncio.to_thread(self._load_model)
            async with self._inference_lock:
                if self._backend == "transformers":
                    text = await asyncio.to_thread(
                        self._infer_transformers, pil_image, _TASK_PROMPTS["ocr"]
                    )
                else:
                    text = await asyncio.to_thread(
                        self._infer_pipeline_text, pil_image
                    )
            logger.info("OCR 识别完成", length=len(text))
            return text
        except BusinessException:
            raise
        except Exception as exc:
            logger.error("OCR 识别失败", error=str(exc))
            raise BusinessException(
                message=f"OCR 识别失败: {exc}",
                code=ErrorCode.BUSINESS_TASK_FAILED,
            ) from exc

    async def recognize_batch(self, images: list[bytes]) -> list[str]:
        """批量识别多张图像中的文字。

        为控制 GPU 显存占用，采用顺序方式逐张推理而非并发。

        Args:
            images: 图像字节流列表。

        Returns:
            list[str]: 每张图像对应的识别文本，顺序与输入一致。
        """
        if not images:
            return []
        results: list[str] = []
        for img in images:
            results.append(await self.recognize(img))
        return results

    async def recognize_with_layout(self, image: bytes | Image.Image) -> dict:
        """识别图像文字并返回版面结构。

        Args:
            image: 图像字节流或 PIL 图像。

        Returns:
            dict: 版面识别结果，结构为::

                {
                    "text": "整页完整文本",
                    "layout": [
                        {
                            "type": "text/table/figure/title",
                            "bbox": [x1, y1, x2, y2],
                            "text": "该区域的识别文本"
                        },
                        ...
                    ],
                    "pages": 1
                }
        """
        try:
            pil_image = self._to_pil(image)
            await asyncio.to_thread(self._load_model)
            async with self._inference_lock:
                if self._backend == "transformers":
                    result = await asyncio.to_thread(
                        self._recognize_with_layout_transformers, pil_image
                    )
                else:
                    result = await asyncio.to_thread(
                        self._recognize_with_layout_pipeline, pil_image
                    )
            logger.info(
                "OCR 版面识别完成",
                blocks=len(result.get("layout", [])),
                pages=result.get("pages", 0),
            )
            return result
        except BusinessException:
            raise
        except Exception as exc:
            logger.error("OCR 版面识别失败", error=str(exc))
            raise BusinessException(
                message=f"OCR 版面识别失败: {exc}",
                code=ErrorCode.BUSINESS_TASK_FAILED,
            ) from exc


# 模块级单例，懒加载，导入时不加载模型
ocr_service = OCRService(model_path=settings.PADDLE_OCR_MODEL_DIR)
