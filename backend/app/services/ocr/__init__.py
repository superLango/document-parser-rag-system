"""OCR 模块：GLM-OCR 自托管文档解析。

唯一保留的 OCR 引擎，基于 PP-DocLayoutV3 版面分析 + GLM-OCR vLLM 全并行识别。

模块结构::

    ocr/
    ├── ocr_service.py     # 主服务（parse_document 入口）
    ├── config.py          # 配置整合
    ├── file_manager.py    # data/ocr_data/{task_id}/ 文件管理
    ├── ocr_util/          # GLM-OCR SDK 工具（原 glmocr_sdk_selfhost）
    ├── preprocess/        # 图像预处理（方向校正/倾斜校正/增强/质量评估）
    └── postprocess/       # 后处理（文本清洗）

用法::

    from app.services.ocr import ocr_service

    result = await ocr_service.parse_document(
        file_bytes=pdf_bytes,
        task_id="task-abc123",
        filename="document.pdf",
    )
    # result == {"text", "layout", "markdown", "json", "pages", "output_dir"}
"""

from __future__ import annotations

# 直接导入实例（ocr_service.py 模块级别不加载 torch 等重依赖，
# 重依赖在 _ensure_started() 中懒加载）
from app.services.ocr.ocr_service import OcrService, ocr_service
from app.services.ocr.ocr_config import ocr_config
from app.services.ocr.file_manager import file_manager

__all__ = [
    "ocr_service",
    "OcrService",
    "ocr_config",
    "file_manager",
]
