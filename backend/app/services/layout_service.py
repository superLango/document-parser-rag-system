"""文档版面分析服务模块。

本模块封装双引擎版面检测能力，提供：

- MinerU pipeline 作为主引擎：表格结构识别、公式检测、多栏阅读顺序更优
- PP-DocLayoutV2 作为后备引擎：DETR 架构版面检测，轻量稳定
- 模型懒加载与预热
- 单图版面分析（输出表格 / 图片 / 文本 / 标题 / 页眉 / 页脚等区域）
- 批量版面分析
- 文本块抽取（按阅读顺序排列）

两套引擎输出统一归一化为 6 类可读类型：text / table / figure / title /
header / footer，便于下游 RAG 流水线统一消费。MinerU 额外携带 OCR 文本、
表格 HTML、公式 LaTeX 等富信息，以可选字段附加在 region 中。

所有阻塞式推理调用均通过 ``asyncio.to_thread`` 投递到线程池，避免阻塞
事件循环。

使用示例：
    from app.services.layout_service import layout_service

    # 预热模型
    await layout_service.warmup()

    # 单图分析
    result = await layout_service.analyze(image_bytes)
    # result = {"regions": [{"type": "text", "bbox": [...], "confidence": 0.9}],
    #           "page_size": {"width": 1240, "height": 1754}}

    # 抽取文本块（按阅读顺序）
    blocks = await layout_service.extract_text_blocks(image_bytes)
"""

import asyncio
import json
import os
import threading
from io import BytesIO
from typing import Any, Callable

import numpy as np
import paddle.inference as paddle_infer
from PIL import Image

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------
# 版面检测标签 -> 归一化可读类型映射
# PP-DocLayoutV2 原始 25 类 + MinerU pipeline 扩展标签（ocr_text / seal）
# 均归一化到 6 类：text / table / figure / title / header / footer
# ---------------------------------------------------------------
LABEL_TYPE_MAP: dict[str, str] = {
    "abstract": "text",
    "algorithm": "text",
    "aside_text": "text",
    "chart": "figure",
    "content": "text",
    "display_formula": "text",
    "doc_title": "title",
    "figure_title": "title",
    "footer": "footer",
    "footer_image": "figure",
    "footnote": "text",
    "formula_number": "text",
    "header": "header",
    "header_image": "figure",
    "image": "figure",
    "inline_formula": "text",
    "number": "text",
    "ocr_text": "text",
    "paragraph_title": "title",
    "reference": "text",
    "reference_content": "text",
    "seal": "figure",
    "table": "table",
    "text": "text",
    "vertical_text": "text",
    "vision_footnote": "text",
}

# 模型输入固定边长（来自 config.json Preprocess.Resize.target_size=[800,800]）
_INPUT_SIZE: int = 800
# 置信度过滤阈值（来自 config.json draw_threshold）
_CONF_THRESHOLD: float = 0.5

# MinerU pipeline 批量分析的函数引用类型
_MineruBatchAnalyze = Callable[..., list[list[dict[str, Any]]]]


class LayoutService:
    """双引擎版面分析服务封装（MinerU 为主，PP-DocLayoutV2 为后备）。

    采用懒加载策略：构造时不加载模型，首次调用 ``analyze`` / ``warmup``
    时才初始化相应引擎。

    引擎选择逻辑：
        1. 构造时尝试导入 MinerU pipeline（``batch_image_analyze``）。
        2. 若导入成功 → MinerU 为主引擎，PP-DocLayoutV2 不加载。
        3. 若导入失败 → PP-DocLayoutV2 作为唯一引擎。
        4. 运行时若 MinerU 推理异常 → 临时回退 PP-DocLayoutV2。

    线程安全说明：PP-DocLayoutV2 predictor 实例非线程安全，通过 ``_infer_lock``
    串行化；MinerU 内部 ``ModelSingleton`` 自带线程安全锁。

    Attributes:
        model_dir: PP-DocLayoutV2 模型目录。
        _mineru_available: MinerU pipeline 是否可用。
        _mineru_loaded: MinerU 模型是否已加载（首次推理后置 True）。
        _predictor: PaddlePaddle predictor（后备引擎，懒加载）。
    """

    def __init__(self, model_dir: str) -> None:
        """初始化版面分析服务，尝试加载 MinerU，失败则使用 PP-DocLayoutV2。

        Args:
            model_dir: PP-DocLayoutV2 模型目录绝对路径。
        """
        self.model_dir: str = model_dir

        # ---- MinerU 主引擎 ----
        self._mineru_available: bool = False
        self._mineru_loaded: bool = False
        self._mineru_batch_analyze: _MineruBatchAnalyze | None = None
        self._load_mineru()

        # ---- PP-DocLayoutV2 后备引擎 ----
        self._predictor: paddle_infer.Predictor | None = None
        self._label_list: list[str] = []
        self._input_names: list[str] = []
        self._output_names: list[str] = []
        self._paddle_loaded: bool = False
        # 串行化 PP-DocLayoutV2 推理，保证 predictor 线程安全
        self._infer_lock: threading.Lock = threading.Lock()

    # ---------------------------------------------------------------
    # MinerU 主引擎加载
    # ---------------------------------------------------------------
    def _load_mineru(self) -> None:
        """尝试导入 MinerU pipeline 的 ``batch_image_analyze``。

        MinerU 3.x 的 pipeline 后端在内部通过 ``ModelSingleton`` 懒加载
        layout / 公式 / 表格 / OCR 等模型，首次调用时自动从
        HuggingFace / ModelScope 下载权重。

        若导入失败（未安装 mineru 或缺少 pipeline 依赖），仅记录警告，
        不抛异常，后续回退 PP-DocLayoutV2。
        """
        try:
            from mineru.backend.pipeline.pipeline_analyze import (
                batch_image_analyze,
            )

            self._mineru_batch_analyze = batch_image_analyze
            self._mineru_available = True
            logger.info(
                "MinerU pipeline 可用，将作为主版面分析引擎",
                engine="mineru",
            )
        except ImportError as err:
            self._mineru_available = False
            logger.warning(
                "MinerU 不可用，将使用 PP-DocLayoutV2 作为后备引擎",
                error=str(err),
                engine="paddle",
            )
        except Exception as err:
            self._mineru_available = False
            logger.warning(
                "MinerU 加载异常，回退 PP-DocLayoutV2",
                error=str(err),
                engine="paddle",
            )

    # ---------------------------------------------------------------
    # PP-DocLayoutV2 后备引擎加载
    # ---------------------------------------------------------------
    def _ensure_paddle_loaded(self) -> None:
        """确保 PP-DocLayoutV2 模型已加载，未加载则触发加载。"""
        if self._paddle_loaded:
            return
        self._load_paddle_layout()

    def _load_paddle_layout(self) -> None:
        """加载 PaddlePaddle 推理模型与配置（后备引擎）。

        读取 ``inference.pdmodel`` / ``inference.pdiparams`` 创建 predictor，
        并从 ``config.json`` 读取 ``label_list`` 用于类别 ID 反查。

        Raises:
            BusinessException: 模型文件缺失或加载失败时抛出。
        """
        model_file: str = os.path.join(self.model_dir, "inference.pdmodel")
        params_file: str = os.path.join(self.model_dir, "inference.pdiparams")
        config_file: str = os.path.join(self.model_dir, "config.json")

        # 校验模型文件存在性
        if not os.path.exists(model_file) or not os.path.exists(params_file):
            logger.error("版面分析模型文件缺失", model_dir=self.model_dir)
            raise BusinessException(
                code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                message=f"版面分析模型文件缺失: {self.model_dir}",
            )

        # 读取 config.json 中的 label_list
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg: dict = json.load(f)
            self._label_list = cfg.get("label_list", [])
        except (OSError, json.JSONDecodeError) as err:
            logger.error("读取版面模型 config.json 失败", error=str(err))
            raise BusinessException(
                code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                message="版面分析模型配置文件读取失败",
            ) from err

        # 创建推理配置与 predictor（默认 CPU + oneDNN）
        logger.info("开始加载 PP-DocLayoutV2 后备模型", model_dir=self.model_dir)
        try:
            config = paddle_infer.Config(model_file, params_file)
            config.disable_gpu()
            config.disable_glog_info()
            # 启用 oneDNN（原 MKL-DNN）以加速 CPU 推理
            if hasattr(config, "enable_onednn"):
                config.enable_onednn()
            elif hasattr(config, "enable_mkldnn"):
                config.enable_mkldnn()
            self._predictor = paddle_infer.create_predictor(config)
            self._input_names = self._predictor.get_input_names()
            self._output_names = self._predictor.get_output_names()
            self._paddle_loaded = True
            logger.info(
                "PP-DocLayoutV2 后备模型加载完成",
                labels=len(self._label_list),
                inputs=self._input_names,
                outputs=self._output_names,
            )
        except Exception as err:
            logger.error("PP-DocLayoutV2 模型加载失败", error=str(err))
            raise BusinessException(
                code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                message="版面分析模型加载失败",
            ) from err

    # ---------------------------------------------------------------
    # PP-DocLayoutV2 图像预处理 / 后处理
    # ---------------------------------------------------------------
    def _preprocess(
        self, image: Image.Image
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
        """将 PIL 图像预处理为 PP-DocLayoutV2 输入张量。

        预处理流程依据 ``config.json`` 中的 Preprocess 配置：
        1. Resize 至 (800, 800)，keep_ratio=false
        2. NormalizeImage（mean=0, std=1，DETR 标准 /255 归一化）
        3. Permute：HWC -> CHW
        """
        img: Image.Image = image.convert("RGB")
        orig_w, orig_h = img.size

        # Resize（interp=2 对应双线性插值）
        img = img.resize((_INPUT_SIZE, _INPUT_SIZE), Image.BILINEAR)
        arr: np.ndarray = np.asarray(img, dtype=np.float32)  # HWC, 0-255

        # NormalizeImage：mean=0, std=1，DETR 标准做法除以 255
        arr = arr / 255.0

        # Permute：HWC -> CHW，并增加 batch 维
        arr = arr.transpose(2, 0, 1)[np.newaxis, ...]  # [1, 3, H, W]

        # im_shape = 预处理后图像的 [高, 宽]
        im_shape: np.ndarray = np.array(
            [[_INPUT_SIZE, _INPUT_SIZE]], dtype=np.float32
        )
        # scale_factor = [高度缩放比, 宽度缩放比]
        scale_factor: np.ndarray = np.array(
            [[_INPUT_SIZE / orig_h, _INPUT_SIZE / orig_w]], dtype=np.float32
        )
        return arr, im_shape, scale_factor, orig_w, orig_h

    def _run_paddle_inference(
        self,
        input_tensor: np.ndarray,
        im_shape: np.ndarray,
        scale_factor: np.ndarray,
    ) -> np.ndarray:
        """执行 PP-DocLayoutV2 推理并返回检测框张量。

        通过 ``_infer_lock`` 串行化，保证 predictor 线程安全。
        """
        predictor: paddle_infer.Predictor = self._predictor  # type: ignore[assignment]

        with self._infer_lock:
            feeds: dict[str, np.ndarray] = {
                "image": input_tensor,
                "im_shape": im_shape,
                "scale_factor": scale_factor,
            }
            for name, data in feeds.items():
                if name not in self._input_names:
                    continue
                handle = predictor.get_input_handle(name)
                handle.reshape(list(data.shape))
                handle.copy_from_cpu(data)

            predictor.run()

            output: np.ndarray = np.empty((0, 8), dtype=np.float32)
            for name in self._output_names:
                out_handle = predictor.get_output_handle(name)
                tmp: np.ndarray = out_handle.copy_to_cpu()
                tmp = np.squeeze(tmp)
                if tmp.ndim == 2 and tmp.shape[-1] >= 6:
                    output = tmp
                    break
            # 兜底：取第一个输出
            if output.shape[0] == 0 and self._output_names:
                out_handle = predictor.get_output_handle(self._output_names[0])
                output = np.squeeze(out_handle.copy_to_cpu())

        return output

    def _postprocess_paddle(
        self, output: np.ndarray, orig_w: int, orig_h: int
    ) -> dict:
        """将 PP-DocLayoutV2 原始输出转换为统一格式的区域列表。"""
        regions: list[dict] = []

        if output.ndim == 1:
            output = output.reshape(1, -1)

        for row in output:
            if row.shape[0] < 6:
                continue
            label_id: int = int(row[0])
            score: float = float(row[1])
            x1: float = float(row[2])
            y1: float = float(row[3])
            x2: float = float(row[4])
            y2: float = float(row[5])

            if score < _CONF_THRESHOLD:
                continue

            # 坐标裁剪至原图边界
            x1 = max(0.0, min(float(orig_w), x1))
            y1 = max(0.0, min(float(orig_h), y1))
            x2 = max(0.0, min(float(orig_w), x2))
            y2 = max(0.0, min(float(orig_h), y2))

            if x2 <= x1 or y2 <= y1:
                continue

            label_name: str = (
                self._label_list[label_id]
                if 0 <= label_id < len(self._label_list)
                else "unknown"
            )
            rtype: str = LABEL_TYPE_MAP.get(label_name, "text")

            regions.append(
                {
                    "type": rtype,
                    "bbox": [x1, y1, x2, y2],
                    "confidence": score,
                }
            )

        logger.info(
            "PP-DocLayoutV2 版面分析完成",
            region_count=len(regions),
            page_width=orig_w,
            page_height=orig_h,
        )
        return {
            "regions": regions,
            "page_size": {"width": orig_w, "height": orig_h},
        }

    # ---------------------------------------------------------------
    # MinerU 推理与后处理
    # ---------------------------------------------------------------
    def _infer_mineru(self, pil_image: Image.Image) -> dict:
        """使用 MinerU pipeline 执行版面分析（同步，供 ``asyncio.to_thread``）。

        MinerU 的 ``batch_image_analyze`` 接收 ``List[Tuple[PIL.Image, bool, str]]``，
       返回 ``list[list[dict]]``（按页分组）。每个 layout result dict 含：
        ``label`` / ``bbox`` / ``score``，部分还携带 ``text`` / ``latex`` / ``html``。

        本方法将其归一化为统一输出格式 ``{"regions": [...], "page_size": {...}}``，
        并将 MinerU 的富信息（OCR 文本、表格 HTML、公式 LaTeX）以可选字段附加。

        Args:
            pil_image: PIL 图像对象。

        Returns:
            dict: 同 ``analyze`` 返回值。
        """
        assert self._mineru_batch_analyze is not None

        # MinerU 首次调用会触发模型下载与初始化
        if not self._mineru_loaded:
            logger.info("MinerU 首次推理，正在加载模型（可能需要下载权重）...")

        # 构造单页输入：(PIL.Image, ocr_enable=True, lang="ch")
        images_with_info: list[tuple[Image.Image, bool, str]] = [
            (pil_image, True, "ch"),
        ]

        results: list[list[dict]] = self._mineru_batch_analyze(
            images_with_info,
            formula_enable=True,
            table_enable=True,
        )

        if not self._mineru_loaded:
            self._mineru_loaded = True
            logger.info("MinerU 模型加载完成")

        # 取第一页（单图分析）
        page_results: list[dict] = results[0] if results else []

        orig_w, orig_h = pil_image.size
        regions: list[dict] = self._convert_mineru_results(page_results, orig_w, orig_h)

        logger.info(
            "MinerU 版面分析完成",
            region_count=len(regions),
            page_width=orig_w,
            page_height=orig_h,
        )
        return {
            "regions": regions,
            "page_size": {"width": orig_w, "height": orig_h},
        }

    @staticmethod
    def _convert_mineru_results(
        page_results: list[dict],
        orig_w: int,
        orig_h: int,
    ) -> list[dict]:
        """将 MinerU layout 结果列表转换为统一 region 格式。

        MinerU 结果字段：``label`` / ``bbox`` [x0,y0,x1,y1] / ``score``，
        部分携带 ``text``（OCR 文本）、``latex``（公式）、``html``（表格 HTML）。

        Args:
            page_results: MinerU 单页 layout result 列表。
            orig_w: 原始图像宽度。
            orig_h: 原始图像高度。

        Returns:
            list[dict]: 归一化后的 region 列表。
        """
        regions: list[dict] = []

        for item in page_results:
            label: str = item.get("label", "unknown")
            score: float = float(item.get("score", 0.0))
            bbox = item.get("bbox")

            if not bbox or len(bbox) < 4:
                continue

            x1: float = float(bbox[0])
            y1: float = float(bbox[1])
            x2: float = float(bbox[2])
            y2: float = float(bbox[3])

            # 坐标裁剪至原图边界
            x1 = max(0.0, min(float(orig_w), x1))
            y1 = max(0.0, min(float(orig_h), y1))
            x2 = max(0.0, min(float(orig_w), x2))
            y2 = max(0.0, min(float(orig_h), y2))

            if x2 <= x1 or y2 <= y1:
                continue

            rtype: str = LABEL_TYPE_MAP.get(label, "text")

            region: dict[str, Any] = {
                "type": rtype,
                "bbox": [x1, y1, x2, y2],
                "confidence": score,
            }

            # 附加 MinerU 富信息（不破坏现有接口，下游按需取用）
            text_val = item.get("text")
            if isinstance(text_val, str) and text_val.strip():
                region["text"] = text_val
            elif isinstance(text_val, list) and text_val:
                # seal 类型返回文本列表
                region["text"] = " ".join(text_val)

            latex = item.get("latex")
            if isinstance(latex, str) and latex.strip():
                region["latex"] = latex

            html = item.get("html")
            if isinstance(html, str) and html.strip():
                region["html"] = html

            regions.append(region)

        return regions

    # ---------------------------------------------------------------
    # PP-DocLayoutV2 推理（后备路径）
    # ---------------------------------------------------------------
    def _infer_paddle(self, image: Image.Image) -> dict:
        """同步执行 PP-DocLayoutV2 完整推理流程（后备引擎）。"""
        self._ensure_paddle_loaded()
        input_tensor, im_shape, scale_factor, orig_w, orig_h = self._preprocess(image)
        output: np.ndarray = self._run_paddle_inference(
            input_tensor, im_shape, scale_factor
        )
        return self._postprocess_paddle(output, orig_w, orig_h)

    # ---------------------------------------------------------------
    # 对外异步接口
    # ---------------------------------------------------------------
    async def warmup(self) -> None:
        """预热模型：加载主引擎并执行一次空推理。

        MinerU 可用时预热 MinerU pipeline；否则预热 PP-DocLayoutV2。
        若主引擎预热失败，自动尝试后备引擎。
        """
        if self._mineru_available:
            logger.info("开始预热 MinerU pipeline")
            dummy: Image.Image = Image.new("RGB", (200, 200), color="white")
            try:
                await asyncio.to_thread(self._infer_mineru, dummy)
                logger.info("MinerU pipeline 预热完成")
                return
            except Exception as err:
                logger.warning(
                    "MinerU 预热失败，回退 PP-DocLayoutV2",
                    error=str(err),
                )
                # 标记 MinerU 不可用，后续直接用 PP-DocLayoutV2
                self._mineru_available = False

        # 预热 PP-DocLayoutV2
        logger.info("开始预热 PP-DocLayoutV2 模型")
        await asyncio.to_thread(self._ensure_paddle_loaded)
        dummy = Image.new("RGB", (200, 200), color="white")
        try:
            await asyncio.to_thread(self._infer_paddle, dummy)
            logger.info("PP-DocLayoutV2 模型预热完成")
        except BusinessException:
            raise
        except Exception as err:
            logger.error("PP-DocLayoutV2 模型预热失败", error=str(err))
            raise BusinessException(
                code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                message="版面分析模型预热失败",
            ) from err

    async def analyze(self, image: bytes | Image.Image) -> dict:
        """对单张图像执行版面分析。

        MinerU 可用时优先使用（表格结构 / 公式 / 多栏阅读顺序更优）；
        MinerU 运行异常时自动回退 PP-DocLayoutV2。

        Args:
            image: 图像字节数据或 PIL.Image 对象。

        Returns:
            dict: ``{"regions": [...], "page_size": {"width": int, "height": int}}``，
            其中每个 region 结构为
            ``{"type": "text|table|figure|title|header|footer",
               "bbox": [x1, y1, x2, y2], "confidence": float}``。
            MinerU 引擎下 region 可能额外携带 ``text`` / ``latex`` / ``html``。

        Raises:
            BusinessException: 图像解码失败或推理异常时抛出。
        """
        # 统一转换为 PIL.Image
        if isinstance(image, bytes):
            try:
                pil_image: Image.Image = Image.open(BytesIO(image))
            except Exception as err:
                logger.error("图像解码失败", error=str(err))
                raise BusinessException(
                    code=ErrorCode.BUSINESS_UNSUPPORTED_FILE_TYPE,
                    message="图像解码失败，请检查图像格式",
                ) from err
        elif isinstance(image, Image.Image):
            pil_image = image
        else:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="image 参数必须为 bytes 或 PIL.Image.Image",
            )

        # MinerU 主引擎
        if self._mineru_available:
            try:
                return await asyncio.to_thread(self._infer_mineru, pil_image)
            except Exception as err:
                logger.warning(
                    "MinerU 分析异常，回退 PP-DocLayoutV2",
                    error=str(err),
                )
                # 确保后备引擎可用
                await asyncio.to_thread(self._ensure_paddle_loaded)

        # PP-DocLayoutV2 后备
        try:
            return await asyncio.to_thread(self._infer_paddle, pil_image)
        except BusinessException:
            raise
        except Exception as err:
            logger.error("版面分析推理失败", error=str(err))
            raise BusinessException(
                code=ErrorCode.SYSTEM_INTERNAL_ERROR,
                message="版面分析推理失败",
            ) from err

    async def analyze_batch(self, images: list[bytes]) -> list[dict]:
        """对多张图像执行批量版面分析。

        通过 ``asyncio.gather`` 并发调度。

        Args:
            images: 图像字节数据列表。

        Returns:
            list[dict]: 与输入顺序一致的分析结果列表。
        """
        if not images:
            return []
        logger.info("开始批量版面分析", batch_size=len(images))
        return await asyncio.gather(*(self.analyze(img) for img in images))

    async def extract_text_blocks(self, image: bytes) -> list[dict]:
        """抽取图像中的文本块并按阅读顺序排序。

        调用 ``analyze`` 后过滤出 ``type == "text"`` 的区域，按
        "先上后下、先左后右" 的阅读顺序排列。

        MinerU 引擎下，文本块可能携带 ``text`` 字段（OCR 识别文本），
        下游可直接使用，无需再调 OCR。

        Args:
            image: 图像字节数据。

        Returns:
            list[dict]: 按阅读顺序排序的文本块列表。
        """
        result: dict = await self.analyze(image)
        text_blocks: list[dict] = [
            region for region in result["regions"] if region["type"] == "text"
        ]
        # 阅读顺序：以 y1 为主键升序、x1 为次键升序
        text_blocks.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
        logger.info("文本块抽取完成", block_count=len(text_blocks))
        return text_blocks


# 模块级单例：模型路径 = {PADDLE_OCR_MODEL_DIR}/PP-DocLayoutV2
layout_service: LayoutService = LayoutService(
    model_dir=os.path.join(settings.PADDLE_OCR_MODEL_DIR, "PP-DocLayoutV2")
)
