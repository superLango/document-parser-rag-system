"""MinerU-Popo 文档后处理服务。

基于 MinerU-Popo 4B VLM 模型，对 OCR/版面分析结果进行文档级后处理：
- 文本截断恢复（跨页段落合并）
- 表格截断恢复（跨页表格合并）
- 标题层级重建
- 图文关联

模型为 Qwen3-VL 4B 微调版本，通过 transformers 库加载推理。
"""

import asyncio
import glob
import json
import os
import sys
import tempfile
import traceback
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Popo 引擎代码路径
_POPO_ENGINE_DIR = str(Path(__file__).parent / "popo_engine")

# 类型映射: 我们的 layout 类型 -> Popo 类型；值为 None 表示跳过该类型
_TYPE_MAP = {
    "text": "text",
    "title": "title",
    "table": "table",
    "figure": "image",
    "header": None,  # 跳过
    "footer": None,  # 跳过
}


class PopoService:
    """MinerU-Popo 后处理服务。

    封装 Popo 推理代码，提供统一的异步接口供文档解析流水线调用。
    推理失败时静默返回 None，不影响主流程。
    """

    def __init__(self) -> None:
        # 是否已设置环境变量与 sys.path
        self._initialized: bool = False
        # 解析后的模型绝对路径
        self._model_path: str = ""

    def _ensure_env(self) -> None:
        """设置环境变量，确保 Popo 引擎能找到模型。

        幂等：仅首次调用时执行实际初始化，后续调用直接返回。
        """
        if self._initialized:
            return

        model_dir = getattr(settings, "POPO_MODEL_DIR", "models/MinerU-Popo")
        # 解析为绝对路径：popo_service.py 位于 backend/app/services/，
        # parents[3] 即为项目根目录 /home/hanson/doc_parse_project
        project_root = Path(__file__).resolve().parents[3]
        model_path = project_root / model_dir
        if not model_path.exists():
            # 配置的路径不是绝对路径时退化为相对路径，便于测试覆盖
            model_path = Path(model_dir)

        self._model_path = str(model_path)
        os.environ["POPO_MODEL_PATH"] = self._model_path
        os.environ["POPO_INFERENCE_BACKEND"] = "transformers"

        # 将 popo_engine 添加到 sys.path，使 `from inference import main` 可导入
        if _POPO_ENGINE_DIR not in sys.path:
            sys.path.insert(0, _POPO_ENGINE_DIR)

        self._initialized = True
        logger.info("Popo 后处理服务初始化", model_path=self._model_path)

    def _normalize_layout(
        self,
        merged_layout: list[dict],
        page_size: dict,
    ) -> dict[str, list[dict]]:
        """将 merged_layout 转换为 Popo 输入格式。

        Args:
            merged_layout: 版面分析结果列表，每项含 type/bbox/text|html|latex。
            page_size: ``{"width": float, "height": float}``，用于将像素坐标
                归一化到 [0, 1] 区间。

        Returns:
            dict[str, list[dict]]: 键为页码字符串（"1"），值为 Popo 块列表。
            每个块结构为 ``{"type", "content", "bbox": [x1,y1,x2,y2]}``，
            其中 bbox 已归一化。若无有效块则返回空 dict。
        """
        width = float(page_size.get("width", 1))
        height = float(page_size.get("height", 1))

        blocks: list[dict] = []
        for region in merged_layout:
            rtype = region.get("type", "text")
            popo_type = _TYPE_MAP.get(rtype)
            if popo_type is None:
                # header / footer 跳过
                continue

            bbox = region.get("bbox", [0, 0, 0, 0])
            if len(bbox) < 4:
                continue

            # 归一化到 [0, 1]
            x1 = max(0.0, min(1.0, bbox[0] / width))
            y1 = max(0.0, min(1.0, bbox[1] / height))
            x2 = max(0.0, min(1.0, bbox[2] / width))
            y2 = max(0.0, min(1.0, bbox[3] / height))

            if x2 <= x1 or y2 <= y1:
                continue

            # 优先使用 text，其次 html / latex
            content = region.get("text", "") or region.get("html", "") or ""
            if not content.strip():
                continue

            blocks.append(
                {
                    "type": popo_type,
                    "content": content[:5000],  # 限制长度，避免 prompt 过长
                    "bbox": [x1, y1, x2, y2],
                }
            )

        # 单页文档：使用 "1" 作为页码
        return {"1": blocks} if blocks else {}

    def _save_as_temp_pdf(self, document_bytes: bytes) -> str:
        """将文档字节保存为临时 PDF 文件。

        Popo 的推理代码需要 PDF 文件路径来渲染页面图像。
        - 如果输入是合法 PDF 字节流，直接落盘；
        - 否则尝试作为图片打开并用 PIL 转换为单页 PDF。

        Args:
            document_bytes: 原始文档字节（PDF 或 PNG/JPEG）。

        Returns:
            str: 临时 PDF 文件绝对路径。调用方负责清理。
        """
        # 尝试检测文件类型
        try:
            # 尝试作为 PDF 打开
            import fitz

            doc = fitz.open(stream=document_bytes, filetype="pdf")
            if doc.page_count > 0:
                doc.close()
                # 直接保存为 PDF
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False, mode="wb"
                )
                tmp.write(document_bytes)
                tmp.close()
                return tmp.name
            doc.close()
        except Exception:
            # 非 PDF 或打开失败，进入图片分支
            pass

        # 作为图片处理，转换为单页 PDF
        img = Image.open(BytesIO(document_bytes))
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        img.save(tmp.name, "PDF", resolution=150.0)
        return tmp.name

    def _parse_popo_result(self, doc_blocks: list[dict]) -> dict:
        """将 inference.main 输出的 doc_blocks 列表解析为统一的结果结构。

        inference.py 中每个 block 携带以下字段：
        - id: 1-based 块 ID
        - contd: -1 表示无截断合并，否则为目标块 ID（1-based）
        - level: -1 表示非标题，否则为标题层级（>=0）
        - image: -1 表示无关联，否则为关联图像块 ID（1-based）
        - table_merge: -1 表示无表格合并，否则为关联表格块 ID（1-based）
        - content: 文本内容

        Args:
            doc_blocks: inference.main 写入 JSON 的原始 list。

        Returns:
            dict: 包含 title_hierarchy / text_continuations /
            image_associations / table_continuations / enriched_text 五个字段。
        """
        title_hierarchy: list[dict] = []
        text_continuations: list[dict] = []
        image_associations: list[dict] = []
        table_continuations: list[dict] = []
        text_parts: list[str] = []

        for block in doc_blocks or []:
            block_id = block.get("id")
            content = block.get("content", "") or ""

            def _as_int(value, default: int = -1) -> int:
                """安全转换为 int，转换失败返回 default。"""
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return default

            contd = _as_int(block.get("contd", -1))
            level = _as_int(block.get("level", -1))
            image = _as_int(block.get("image", -1))
            table_merge = _as_int(block.get("table_merge", -1))

            if block_id is not None and level >= 0:
                title_hierarchy.append(
                    {
                        "block_id": _as_int(block_id),
                        "level": level,
                        "content": content,
                    }
                )

            if block_id is not None and contd >= 0:
                text_continuations.append(
                    {
                        "src_id": _as_int(block_id),
                        "tgt_id": contd,
                    }
                )

            if block_id is not None and image >= 0:
                image_associations.append(
                    {
                        "image_id": _as_int(block_id),
                        "caption_id": image,
                    }
                )

            if block_id is not None and table_merge >= 0:
                table_continuations.append(
                    {
                        "src_id": _as_int(block_id),
                        "tgt_id": table_merge,
                    }
                )

            if content:
                text_parts.append(content)

        enriched_text = "\n".join(text_parts)

        return {
            "title_hierarchy": title_hierarchy,
            "text_continuations": text_continuations,
            "image_associations": image_associations,
            "table_continuations": table_continuations,
            "enriched_text": enriched_text,
        }

    def _run_inference(
        self,
        pdf_path: str,
        normalized_pages: dict[str, list[dict]],
    ) -> dict | None:
        """执行 Popo 推理（同步，供 ``asyncio.to_thread`` 调用）。

        Args:
            pdf_path: 临时 PDF 文件路径。
            normalized_pages: Popo 输入格式 dict。

        Returns:
            dict | None: 解析后的结果 dict；推理失败返回 None。
        """
        try:
            # 导入推理模块（依赖 sys.path 包含 popo_engine 目录）
            from inference import main as popo_main

            # 创建临时输出目录
            output_dir = tempfile.mkdtemp(prefix="popo_output_")

            # 运行推理
            popo_main(
                input_label=pdf_path,
                ocr_res=normalized_pages,
                output_dir=output_dir,
                raw_output_dir=None,
            )

            # 读取输出 JSON
            json_files = glob.glob(os.path.join(output_dir, "*.json"))
            if not json_files:
                logger.warning("Popo 推理未产生输出文件")
                return None

            with open(json_files[0], "r", encoding="utf-8") as f:
                raw_result = json.load(f)

            # 将原始 doc_blocks 解析为统一结构
            if isinstance(raw_result, list):
                return self._parse_popo_result(raw_result)
            if isinstance(raw_result, dict) and "doc_blocks" in raw_result:
                return self._parse_popo_result(raw_result["doc_blocks"])
            return raw_result

        except Exception as err:
            logger.error(
                "Popo 推理失败",
                error=str(err),
                traceback=traceback.format_exc(),
            )
            return None

    async def post_process(
        self,
        document_bytes: bytes,
        merged_layout: list[dict],
        page_size: dict,
    ) -> dict | None:
        """对文档进行后处理。

        Args:
            document_bytes: 原始文档字节（PDF 或图片）。
            merged_layout: 版面分析合并后的布局结果。
            page_size: 页面尺寸 ``{"width": float, "height": float}``。

        Returns:
            dict | None: 后处理结果，包含 title_hierarchy /
            text_continuations / image_associations / table_continuations /
            enriched_text 五个字段；失败或跳过时返回 None。
        """
        self._ensure_env()

        # 归一化布局
        normalized_pages = self._normalize_layout(merged_layout, page_size)
        if not normalized_pages or not any(normalized_pages.values()):
            logger.info("无有效布局块，跳过 Popo 后处理")
            return None

        logger.info(
            "开始 Popo 后处理",
            blocks=sum(len(v) for v in normalized_pages.values()),
        )

        # 保存为临时 PDF
        pdf_path = await asyncio.to_thread(self._save_as_temp_pdf, document_bytes)

        try:
            # 运行推理（同步函数通过 to_thread 包装为异步调用）
            result = await asyncio.to_thread(
                self._run_inference, pdf_path, normalized_pages
            )

            if result:
                logger.info("Popo 后处理完成", result_keys=list(result.keys()))
            else:
                logger.warning("Popo 后处理未返回结果")

            return result
        finally:
            # 清理临时 PDF 文件
            try:
                os.unlink(pdf_path)
            except OSError:
                pass


# 模块级单例
popo_service = PopoService()
