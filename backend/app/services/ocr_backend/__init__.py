"""OCRBackend 拦截层（Phase 3，U6/U7/U13）。

唯一实现：GLMOCRBackend（正文/表格/公式统一走 GLM-OCR，无 UniMERNet/StructEqTable/PaddleOCR）。
"""

from .base import OCRBackend
from .glmocr import GLMOCRBackend, OcrBlockError, get_ocr_backend

__all__ = ["GLMOCRBackend", "OCRBackend", "OcrBlockError", "get_ocr_backend"]
