"""OCR 任务文件管理。

参照 GLM-OCR 项目的文件处理方式，为每次 OCR 任务创建独立目录，
保存上传的源文件、解析结果的 JSON 和 Markdown。

目录结构::

    data/ocr_data/{task_id}/
    ├── source.{ext}     # 上传的源文件（保留原始扩展名）
    ├── result.md        # OCR 解析结果 Markdown
    └── merged.json      # OCR 解析结果 JSON
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from app.core.logging import get_logger
from app.services.ocr.ocr_config import ocr_config

logger = get_logger(__name__)


def _detect_extension(file_bytes: bytes, filename: str = "") -> str:
    """根据 magic bytes 或文件名判断扩展名。

    Args:
        file_bytes: 文件字节流。
        filename: 原始文件名（备用）。

    Returns:
        扩展名（含点，如 ``.pdf``、``.png``）。
    """
    # PDF magic bytes
    if file_bytes[:5] == b"%PDF-":
        return ".pdf"
    # PNG magic bytes
    if file_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    # JPEG magic bytes
    if file_bytes[:3] == b"\xff\xd8\xff":
        return ".jpg"
    # TIFF magic bytes
    if file_bytes[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff"
    # BMP magic bytes
    if file_bytes[:2] == b"BM":
        return ".bmp"
    # 从文件名提取
    if filename and "." in filename:
        ext = Path(filename).suffix.lower()
        if ext in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
            return ext
    # 默认
    return ".bin"


class FileManager:
    """OCR 任务文件管理器。

    负责创建任务目录、保存源文件与解析结果。
    """

    def prepare_task_dir(self, task_id: str, kb_id=None) -> Path:
        """创建任务输出目录。

        - ``kb_id`` 为 None：``data/ocr_data/{task_id}/``（向后兼容）。
        - ``kb_id`` 不为 None：``data/ocr_data/{kb_id}/{task_id}/``（KB 隔离）。

        Args:
            task_id: 任务唯一标识。
            kb_id: 知识库 ID（uuid.UUID 或 None）。

        Returns:
            任务目录 Path 对象。
        """
        task_dir = ocr_config.get_task_output_dir(task_id, kb_id)
        logger.debug("任务输出目录已准备", task_id=task_id, dir=str(task_dir))
        return task_dir

    def save_source_file(
        self,
        task_id: str,
        file_bytes: bytes,
        filename: str = "source",
        kb_id=None,
    ) -> Path:
        """保存上传的源文件到任务目录。

        Args:
            task_id: 任务唯一标识。
            file_bytes: 文件字节流。
            filename: 原始文件名（用于推断扩展名）。
            kb_id: 知识库 ID（uuid.UUID 或 None），透传至 prepare_task_dir。

        Returns:
            保存的文件路径。
        """
        task_dir = self.prepare_task_dir(task_id, kb_id)
        ext = _detect_extension(file_bytes, filename)
        source_path = task_dir / f"source{ext}"
        source_path.write_bytes(file_bytes)
        logger.info(
            "源文件已保存",
            task_id=task_id,
            path=str(source_path),
            size=len(file_bytes),
        )
        return source_path

    def save_result(
        self,
        task_id: str,
        markdown: str,
        json_data: Any,
        kb_id=None,
    ) -> Tuple[Path, Path]:
        """保存 OCR 解析结果到任务目录。

        Args:
            task_id: 任务唯一标识。
            markdown: OCR 结果的 Markdown 文本。
            json_data: OCR 结果的结构化数据（dict 或 JSON 字符串）。
            kb_id: 知识库 ID（uuid.UUID 或 None），透传至 prepare_task_dir。

        Returns:
            (md_path, json_path) 元组。
        """
        task_dir = self.prepare_task_dir(task_id, kb_id)

        # 保存 Markdown
        md_path = task_dir / "result.md"
        md_path.write_text(markdown, encoding="utf-8")

        # 保存 JSON
        json_path = task_dir / "merged.json"
        if isinstance(json_data, str):
            json_path.write_text(json_data, encoding="utf-8")
        else:
            json_path.write_text(
                json.dumps(json_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        logger.info(
            "OCR 结果已保存",
            task_id=task_id,
            md_path=str(md_path),
            json_path=str(json_path),
            md_size=len(markdown),
        )
        return md_path, json_path

    def get_task_dir(self, task_id: str, kb_id=None) -> Path:
        """获取任务目录路径（不创建）。

        Args:
            task_id: 任务唯一标识。
            kb_id: 知识库 ID（uuid.UUID 或 None）。None 时返回全局路径，
                非 None 时返回 ``data/ocr_data/{kb_id}/{task_id}/``。

        Returns:
            任务目录 Path 对象。
        """
        if kb_id is None:
            return Path(ocr_config.output_dir) / task_id
        return Path(ocr_config.output_dir) / str(kb_id) / task_id


file_manager = FileManager()
