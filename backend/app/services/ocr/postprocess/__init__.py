"""OCR 后处理模块。

提供 OCR 输出文本的清洗能力，移除噪声、规范化格式。
"""

from app.services.ocr.postprocess.text_cleaner import text_cleaner

__all__ = ["text_cleaner"]
