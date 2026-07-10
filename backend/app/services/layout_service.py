"""文档版面分析服务模块。

本模块封装基于 PaddlePaddle PP-DocLayoutV2 模型的版面检测能力，提供：

- 模型懒加载与预热
- 单图版面分析（输出表格 / 图片 / 文本 / 标题 / 页眉 / 页脚等区域）
- 批量版面分析
- 文本块抽取（按阅读顺序排列）

PP-DocLayoutV2 为 DETR 架构的版面检测模型，原始 label_list 含 25 个细粒度
类别。本服务将其归一化为 6 类可读类型：text / table / figure / title /
header / footer，便于下游 RAG 流水线统一消费。

所有 PaddlePaddle 阻塞式推理调用均通过 ``asyncio.to_thread`` 投递到线程池，
避免阻塞事件循环；推理过程通过互斥锁串行化，确保 predictor 实例的线程安全。

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

import numpy as np
import paddle.inference as paddle_infer
from PIL import Image

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------
# PP-DocLayoutV2 原始细粒度类别名 -> 归一化可读类型映射
# 依据 config.json 中的 label_list 顺序定义
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


class LayoutService:
    """PP-DocLayoutV2 版面分析服务封装。

    采用懒加载策略：构造时不加载模型，首次调用 ``analyze`` / ``warmup``
    时才创建 PaddlePaddle predictor，避免模块导入阶段占用显存/内存。

    线程安全说明：predictor 实例本身非线程安全，本服务通过 ``_infer_lock``
    串行化推理调用，因此可安全地在多个异步任务中并发使用。

    Attributes:
        model_dir: PP-DocLayoutV2 模型目录，包含 inference.pdmodel、
            inference.pdiparams 与 config.json。
        _predictor: PaddlePaddle predictor 实例，懒加载。
        _label_list: 模型原始类别名列表，从 config.json 读取。
        _loaded: 模型是否已加载标记。
    """

    def __init__(self, model_dir: str) -> None:
        """初始化版面分析服务，仅保存路径不加载模型。

        Args:
            model_dir: PP-DocLayoutV2 模型目录绝对路径。
        """
        self.model_dir: str = model_dir
        self._predictor: paddle_infer.Predictor | None = None
        self._label_list: list[str] = []
        self._input_names: list[str] = []
        self._output_names: list[str] = []
        self._loaded: bool = False
        # 串行化推理，保证 predictor 线程安全
        self._infer_lock: threading.Lock = threading.Lock()

    # ---------------------------------------------------------------
    # 模型加载
    # ---------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        """确保模型已加载，未加载则触发加载。

        多线程环境下通过 ``_loaded`` 标记的二次检查避免重复初始化。
        """
        if self._loaded:
            return
        self._load_model()

    def _load_model(self) -> None:
        """加载 PaddlePaddle 推理模型与配置。

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
        logger.info("开始加载版面分析模型", model_dir=self.model_dir)
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
            self._loaded = True
            logger.info(
                "版面分析模型加载完成",
                labels=len(self._label_list),
                inputs=self._input_names,
                outputs=self._output_names,
            )
        except Exception as err:
            logger.error("版面分析模型加载失败", error=str(err))
            raise BusinessException(
                code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                message="版面分析模型加载失败",
            ) from err

    # ---------------------------------------------------------------
    # 图像预处理 / 后处理
    # ---------------------------------------------------------------
    def _preprocess(
        self, image: Image.Image
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
        """将 PIL 图像预处理为模型输入张量。

        预处理流程依据 ``config.json`` 中的 Preprocess 配置：
        1. Resize 至 (800, 800)，keep_ratio=false
        2. NormalizeImage（mean=0, std=1，此处采用 DETR 标准 /255 归一化）
        3. Permute：HWC -> CHW

        Args:
            image: PIL 图像对象。

        Returns:
            tuple: (input_tensor, im_shape, scale_factor, orig_w, orig_h)
                - input_tensor: 形状 [1, 3, 800, 800] 的 float32 张量
                - im_shape: 形状 [1, 2] 的 float32 张量，值为 [800, 800]
                  （预处理后图像高宽，模型用以还原坐标）
                - scale_factor: 形状 [1, 2] 的 float32 张量，值为
                  [800/orig_h, 800/orig_w]（缩放比，模型内部据此将检测框
                  还原至原图坐标空间）
                - orig_w / orig_h: 原始图像宽高
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
        # scale_factor = [高度缩放比, 宽度缩放比]，
        # 模型内部据此将检测框还原至原图坐标空间
        scale_factor: np.ndarray = np.array(
            [[_INPUT_SIZE / orig_h, _INPUT_SIZE / orig_w]], dtype=np.float32
        )
        return arr, im_shape, scale_factor, orig_w, orig_h

    def _run_inference(
        self,
        input_tensor: np.ndarray,
        im_shape: np.ndarray,
        scale_factor: np.ndarray,
    ) -> np.ndarray:
        """执行模型推理并返回检测框张量。

        输入通过名称查找设置（``im_shape`` / ``image`` / ``scale_factor``），
        避免依赖输入顺序。通过 ``_infer_lock`` 串行化，保证 predictor 线程安全。

        Args:
            input_tensor: 形状 [1, 3, 800, 800] 的输入张量。
            im_shape: 形状 [1, 2] 的预处理图像高宽张量。
            scale_factor: 形状 [1, 2] 的缩放因子张量。

        Returns:
            np.ndarray: 检测结果张量，形状通常为 [N, 8]，每行格式为
            [class_id, score, x1, y1, x2, y2, *, *]（末两列为附加信息，
            后处理阶段忽略），坐标已位于原图坐标空间。
        """
        predictor: paddle_infer.Predictor = self._predictor  # type: ignore[assignment]

        with self._infer_lock:
            # 按名称逐个设置输入
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

            # 从多个输出中查找检测框张量：
            # 候选为 2D 且最后一维 >= 6 的输出（[N, 8]）
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

    def _postprocess(
        self, output: np.ndarray, orig_w: int, orig_h: int
    ) -> dict:
        """将模型原始输出转换为统一格式的区域列表。

        模型输出经 scale_factor 还原后已处于原图坐标空间，此处仅做
        置信度过滤、类别映射与边界裁剪。

        Args:
            output: 模型输出张量，每行 [class_id, score, x1, y1, x2, y2, *, *]。
            orig_w: 原始图像宽度。
            orig_h: 原始图像高度。

        Returns:
            dict: ``{"regions": [...], "page_size": {"width": int, "height": int}}``
        """
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

            # 置信度过滤
            if score < _CONF_THRESHOLD:
                continue

            # 坐标裁剪至原图边界
            x1 = max(0.0, min(float(orig_w), x1))
            y1 = max(0.0, min(float(orig_h), y1))
            x2 = max(0.0, min(float(orig_w), x2))
            y2 = max(0.0, min(float(orig_h), y2))

            # 跳过无效框（宽或高为 0）
            if x2 <= x1 or y2 <= y1:
                continue

            # 类别 ID -> 原始类别名 -> 归一化可读类型
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
            "版面分析完成",
            region_count=len(regions),
            page_width=orig_w,
            page_height=orig_h,
        )
        return {
            "regions": regions,
            "page_size": {"width": orig_w, "height": orig_h},
        }

    # ---------------------------------------------------------------
    # 对外异步接口
    # ---------------------------------------------------------------
    async def warmup(self) -> None:
        """预热模型：加载模型并执行一次空推理。

        在应用启动阶段调用，确保首次真实请求不承担模型加载耗时。
        """
        logger.info("开始预热版面分析模型")
        await asyncio.to_thread(self._ensure_loaded)
        # 使用一张纯白小图执行空推理，触达完整推理路径
        dummy: Image.Image = Image.new("RGB", (200, 200), color="white")
        try:
            await asyncio.to_thread(self._infer, dummy)
            logger.info("版面分析模型预热完成")
        except BusinessException:
            raise
        except Exception as err:
            logger.error("版面分析模型预热失败", error=str(err))
            raise BusinessException(
                code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                message="版面分析模型预热失败",
            ) from err

    def _infer(self, image: Image.Image) -> dict:
        """同步执行完整推理流程（供 ``asyncio.to_thread`` 调用）。

        Args:
            image: PIL 图像对象。

        Returns:
            dict: 后处理结果，同 ``analyze`` 返回值。
        """
        self._ensure_loaded()
        input_tensor, im_shape, scale_factor, orig_w, orig_h = self._preprocess(image)
        output: np.ndarray = self._run_inference(
            input_tensor, im_shape, scale_factor
        )
        return self._postprocess(output, orig_w, orig_h)

    async def analyze(self, image: bytes | Image.Image) -> dict:
        """对单张图像执行版面分析。

        Args:
            image: 图像字节数据或 PIL.Image 对象。

        Returns:
            dict: ``{"regions": [...], "page_size": {"width": int, "height": int}}``，
            其中每个 region 结构为
            ``{"type": "text|table|figure|title|header|footer",
               "bbox": [x1, y1, x2, y2], "confidence": float}``。

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

        try:
            return await asyncio.to_thread(self._infer, pil_image)
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

        通过 ``asyncio.gather`` 并发调度，底层推理受 ``_infer_lock`` 串行化
        保护，因此在保证线程安全的前提下尽可能并行执行预处理与后处理。

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

        Args:
            image: 图像字节数据。

        Returns:
            list[dict]: 按阅读顺序排序的文本块列表，每个元素结构同
            ``analyze`` 返回的 region。
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
