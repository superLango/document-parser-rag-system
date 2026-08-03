"""OCR 主服务：完整 OCR 流程封装。

参照测试脚本 ``/tmp/test_glmocr_parallel_layout.py`` 实现端到端流程：

    PDF/图片 → 图像预处理 → PP-DocLayoutV3 版面分析
    → asyncio.gather 全并行 OCR（不设并发上限，vLLM max-num-seqs 控制排队）
    → ResultFormatter 格式化 → 保存 result.md + merged.json

核心设计：
    - 版面分析：PPDocLayoutDetector.process() 批量推理（GPU 串行批次）
    - OCR 识别：所有区域 asyncio.gather 全并行，不设 Semaphore
      — vLLM 的 --max-num-seqs 控制实际并发，超过的请求自动排队等待
    - 不使用 Pipeline 三线程流水线，直接操控组件实现最大化并行
"""

from __future__ import annotations

import asyncio
import io
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from app.core.logging import get_logger
from app.services.ocr.ocr_config import ocr_config
from app.services.ocr.file_manager import file_manager

logger = get_logger(__name__)

# PDF 渲染长边最大像素限制
_MAX_WH = 3500


class OcrService:
    """OCR 主服务单例。

    封装完整的 OCR 流程，提供统一的 ``parse_document`` 入口。
    组件懒加载，首次调用时初始化版面检测器与 OCR 客户端。
    """

    def __init__(self) -> None:
        self._sdk_config = None
        self._layout_detector = None
        self._ocr_client = None
        self._page_loader = None
        self._result_formatter = None
        self._started = False

    # ------------------------------------------------------------------
    # 生命周期管理
    # ------------------------------------------------------------------

    def _ensure_started(self) -> None:
        """懒加载 SDK 组件（首次调用时初始化）。"""
        if self._started:
            return

        # 设置环境变量供 SDK load_config() 读取
        ocr_config.apply_env()

        from app.services.ocr.ocr_util.ocr_util_config import load_config as load_sdk_config
        from app.services.ocr.ocr_util.dataloader import PageLoader
        from app.services.ocr.ocr_util.layout import PPDocLayoutDetector
        from app.services.ocr.ocr_util.ocr_client import OCRClient
        from app.services.ocr.ocr_util.postprocess import ResultFormatter

        self._sdk_config = load_sdk_config()
        self._layout_detector = PPDocLayoutDetector(self._sdk_config.pipeline.layout)
        self._ocr_client = OCRClient(self._sdk_config.pipeline.ocr_api)
        self._page_loader = PageLoader(self._sdk_config.pipeline.page_loader)
        self._result_formatter = ResultFormatter(
            self._sdk_config.pipeline.result_formatter
        )

        # 启动组件
        self._layout_detector.start()
        self._ocr_client.start()
        self._started = True
        logger.info(
            "OCR 服务组件已启动",
            layout_model=ocr_config.layout_model_dir,
            vllm_endpoint=ocr_config.vllm_endpoint,
            model=ocr_config.vllm_model,
        )

    async def warmup(self) -> None:
        """预热 OCR 组件（供 arq_worker on_startup 调用）。"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._ensure_started)
        logger.info("OCR 服务预热完成")

    def shutdown(self) -> None:
        """释放模型与连接池。"""
        if self._layout_detector is not None:
            self._layout_detector.stop()
            self._layout_detector = None
        if self._ocr_client is not None:
            self._ocr_client.stop()
            self._ocr_client = None
        self._started = False
        logger.info("OCR 服务已关闭")

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def is_layout_model_available(self) -> bool:
        """检查版面分析模型是否可用（已加载且无错误）。"""
        try:
            self._ensure_started()
            return self._layout_detector is not None
        except Exception as exc:
            logger.warning("版面分析模型不可用", error=str(exc)[:200])
            return False

    async def parse_document(
        self,
        file_bytes: bytes,
        task_id: str,
        filename: str = "source",
        kb_id=None,
        use_layout: bool = True,
    ) -> Dict[str, Any]:
        """完整 OCR 流程：PDF/图片 → 预处理 → [版面分析] → OCR → 格式化 → 保存。

        Args:
            file_bytes: 文件字节流（PDF 或图片）。
            task_id: 任务唯一标识，用于创建输出目录。
            filename: 原始文件名（用于推断扩展名）。
            kb_id: 知识库 ID（uuid.UUID 或 None）。None 时输出到全局目录
                ``data/ocr_data/{task_id}/``（向后兼容）；非 None 时输出到
                ``data/ocr_data/{kb_id}/{task_id}/``（KB 物理隔离）。
            use_layout: 是否启用版面分析（PP-DocLayoutV3）。False 时直接整页 OCR，
                不做区域检测，速度更快但无 bbox 信息。

        Returns:
            包含 text, layout, markdown, json, pages, output_dir 的字典。
        """
        total_start = time.time()
        self._ensure_started()

        # 1. 保存源文件
        file_manager.save_source_file(task_id, file_bytes, filename, kb_id)

        # 2. PDF/图片 → Image 列表
        images = self._load_images(file_bytes)
        total_pages = len(images)
        logger.info(
            "OCR 任务开始",
            task_id=task_id,
            pages=total_pages,
            filename=filename,
        )

        # 3. 图像预处理（串行）
        t0 = time.time()
        processed_images = self._preprocess_images(images)
        preprocess_elapsed = time.time() - t0
        logger.info("图像预处理完成", elapsed=f"{preprocess_elapsed:.1f}s")

        # 4. 版面分析（根据 use_layout 决定是否启用）
        t0 = time.time()
        if use_layout:
            layout_results = self._detect_layout(processed_images)
            total_regions = sum(len(r) for r in layout_results)
            logger.info(
                "版面分析完成",
                elapsed=f"{time.time() - t0:.1f}s",
                regions=total_regions,
            )
        else:
            # 不启用版面分析：每页作为一个整页文本区域
            layout_results = []
            for img in processed_images:
                w, h = img.size
                layout_results.append([{
                    "bbox_2d": [0, 0, w, h],
                    "task_type": "text",
                    "score": 1.0,
                }])
            total_regions = len(processed_images)
            logger.info(
                "跳过版面分析（整页OCR模式）",
                pages=total_regions,
            )

        # 5. 全并行 OCR
        t0 = time.time()
        ocr_results = await self._parallel_ocr_regions(
            processed_images, layout_results
        )
        ocr_elapsed = time.time() - t0
        logger.info(
            "全并行OCR完成",
            elapsed=f"{ocr_elapsed:.1f}s",
            regions=len(ocr_results),
        )

        # 6. 结果格式化
        json_str, markdown_str = self._format_results(
            ocr_results, total_pages
        )

        # 7. 构建 layout 数据（不启用版面分析时为空列表）
        ocr_layout = self._build_layout_data(ocr_results, total_pages) if use_layout else []

        # 8. 保存结果
        md_path, json_path = file_manager.save_result(
            task_id, markdown_str, json_str, kb_id
        )

        total_elapsed = time.time() - total_start
        logger.info(
            "OCR 任务完成",
            task_id=task_id,
            total_elapsed=f"{total_elapsed:.1f}s",
            pages=total_pages,
            regions=total_regions,
            md_size=len(markdown_str),
        )

        return {
            "text": markdown_str,
            "layout": ocr_layout,
            "markdown": markdown_str,
            "json": json_str,
            "pages": total_pages,
            "output_dir": str(file_manager.get_task_dir(task_id, kb_id)),
        }

    # ------------------------------------------------------------------
    # 内部流程方法
    # ------------------------------------------------------------------

    def _load_images(self, file_bytes: bytes) -> List[Image.Image]:
        """将文件字节流加载为 PIL Image 列表。

        PDF 使用 PyMuPDF 逐页渲染；图片直接 Image.open。
        """
        if file_bytes[:5] == b"%PDF-":
            return self._pdf_to_images(file_bytes, ocr_config.pdf_dpi)
        # 单张图片
        img = Image.open(io.BytesIO(file_bytes))
        return [img.convert("RGB")]

    def _pdf_to_images(
        self, pdf_bytes: bytes, dpi: int = 200
    ) -> List[Image.Image]:
        """PDF → 图片列表（PyMuPDF 渲染）。

        Args:
            pdf_bytes: PDF 文件字节流。
            dpi: 渲染 DPI。

        Returns:
            PIL Image 列表（RGB）。
        """
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images: List[Image.Image] = []
        for page in doc:
            scale = dpi / 72.0
            # 长边限制，避免超大图
            long_side_pt = max(page.rect.width, page.rect.height)
            if long_side_pt * scale > _MAX_WH:
                scale = _MAX_WH / long_side_pt
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)
        doc.close()
        return images

    def _preprocess_images(
        self, images: List[Image.Image]
    ) -> List[Image.Image]:
        """图像预处理：方向校正 → 倾斜校正 → 条件增强（串行）。

        Args:
            images: 原始 PIL Image 列表。

        Returns:
            处理后的 PIL Image 列表。
        """
        from app.services.ocr.preprocess import (
            geometry_corrector,
            image_enhancer,
            image_quality_assessor,
        )

        processed: List[Image.Image] = []
        for i, img in enumerate(images):
            # 方向校正
            oriented, orient_angle = geometry_corrector.orient_page(img)
            # 倾斜校正
            oriented = geometry_corrector.deskew_page(oriented)
            # 质量评估 → 条件增强
            quality = image_quality_assessor.assess(oriented)
            if quality.needs_enhancement:
                oriented = image_enhancer.enhance(oriented)
            processed.append(oriented)
            logger.debug(
                "页预处理完成",
                page=i + 1,
                orient=orient_angle,
                enhanced=quality.needs_enhancement,
            )
        return processed

    def _detect_layout(
        self, images: List[Image.Image]
    ) -> List[List[Dict]]:
        """批量版面分析（PP-DocLayoutV3）。

        Args:
            images: PIL Image 列表。

        Returns:
            每页的区域列表 ``List[List[Dict]]``。
        """
        return self._layout_detector.process(images)

    async def _parallel_ocr_regions(
        self,
        images: List[Image.Image],
        layout_results: List[List[Dict]],
    ) -> List[Tuple[int, Dict]]:
        """所有区域 asyncio.gather 全并行送入 vLLM OCR。

        不设 Semaphore — 所有区域同时发起 HTTP 请求，
        vLLM 的 --max-num-seqs 控制实际并发，超过的请求自动排队等待。
        """
        from app.services.ocr.ocr_util.utils.image_utils import crop_image_region

        async def ocr_one_region(
            page_idx: int, region: Dict, cropped: Optional[Image.Image]
        ) -> Tuple[int, Dict]:
            task_type = region.get("task_type", "text")
            if task_type == "skip" or cropped is None:
                region["content"] = None
                return page_idx, region

            request_data = self._page_loader.build_request_from_image(
                cropped, task_type
            )
            # 同步 HTTP 调用 → 异步包装
            response, status_code = await asyncio.to_thread(
                self._ocr_client.process, request_data
            )
            if status_code == 200:
                region["content"] = (
                    response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
            else:
                region["content"] = ""
            return page_idx, region

        # 构建所有任务
        tasks: List[asyncio.Task] = []
        for page_idx, (image, layouts) in enumerate(zip(images, layout_results)):
            for region in layouts:
                task_type = region.get("task_type", "text")
                if task_type == "abandon":
                    continue
                if task_type == "skip":
                    tasks.append(
                        asyncio.ensure_future(
                            ocr_one_region(page_idx, region, None)
                        )
                    )
                else:
                    cropped = crop_image_region(
                        image, region["bbox_2d"], region.get("polygon")
                    )
                    tasks.append(
                        asyncio.ensure_future(
                            ocr_one_region(page_idx, region, cropped)
                        )
                    )

        # asyncio.gather 全并行 — 不设 Semaphore
        raw_results = await asyncio.gather(*tasks)
        return list(raw_results)

    def _format_results(
        self,
        ocr_results: List[Tuple[int, Dict]],
        num_pages: int,
    ) -> Tuple[str, str]:
        """按页码分组，格式化为 markdown + json。

        Args:
            ocr_results: (page_idx, region) 元组列表。
            num_pages: 总页数。

        Returns:
            (json_str, markdown_str) 元组。
        """
        # 按页码分组
        page_regions: Dict[int, List[Dict]] = defaultdict(list)
        for page_idx, region in ocr_results:
            page_regions[page_idx].append(region)

        # 按页码顺序构建 grouped
        grouped: List[List[Dict]] = []
        for page_idx in range(num_pages):
            grouped.append(page_regions.get(page_idx, []))

        json_str, markdown_str = self._result_formatter.process(grouped)
        return json_str, markdown_str

    def _build_layout_data(
        self,
        ocr_results: List[Tuple[int, Dict]],
        num_pages: int,
    ) -> List[Dict]:
        """构建版面块列表（与 document_tasks 契约对齐）。

        每项包含 block_content, page_index, block_type, block_id, bbox。
        """
        layout: List[Dict] = []
        block_id = 0
        for page_idx, region in ocr_results:
            content = region.get("content") or ""
            if not content:
                continue
            block_type = region.get("task_type", "text")
            bbox = region.get("bbox_2d")
            block_id += 1
            layout.append(
                {
                    "block_content": content,
                    "page_index": page_idx + 1,
                    "block_type": block_type,
                    "block_id": block_id,
                    "bbox": bbox,
                }
            )
        return layout


# 模块级单例
ocr_service = OcrService()
