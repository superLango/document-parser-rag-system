"""GLMOCRBackend：vLLM 9977 OpenAI 兼容接口（U6/U7/U13）。"""

from __future__ import annotations

import base64
import io
import time

import httpx
from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger

from .base import OCRBackend

logger = get_logger(__name__)


class OcrBlockError(Exception):
    """块级 OCR 失败（重试后仍失败，U13）。"""


PROMPTS = {
    "title": "请完整识别图片中的标题文字，直接输出标题文本，不要输出任何解释。",
    "text": "请完整识别图片中的正文文字，保留原有段落和换行，直接输出 Markdown 文本，不要输出任何解释。",
    "table": "请将图片中的表格完整识别并转换为 HTML <table> 格式输出，保留所有行列内容，不要输出解释。",
    "formula": "请将图片中的公式识别并转换为 LaTeX 公式输出，不要输出解释。",
    "image_caption": "请识别图片中的图注文字，直接输出文本，不要输出解释。",
    "table_caption": "请识别图片中的表注文字，直接输出文本，不要输出解释。",
    "footnote": "请识别图片中的脚注文字，直接输出文本，不要输出解释。",
    "aside_text": "请识别图片中的旁注文字，直接输出文本，不要输出解释。",
}


class GLMOCRBackend(OCRBackend):
    """GLM-OCR（vLLM OpenAI 兼容接口）块级识别。"""

    def __init__(
        self,
        server_url: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        max_edge: int | None = None,
        min_edge: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.server_url = server_url or settings.GLMOCR_SERVER_URL
        self.model = model or settings.GLMOCR_MODEL
        self.max_tokens = max_tokens or settings.GLMOCR_MAX_TOKENS
        self.timeout = timeout or settings.GLMOCR_TIMEOUT_SECONDS
        self.retries = settings.GLMOCR_RETRIES if retries is None else retries
        self.max_edge = max_edge or settings.GLMOCR_MAX_EDGE
        self.min_edge = min_edge or settings.GLMOCR_MIN_EDGE
        # GLM-OCR 是本机回环服务；忽略 Clash 等进程级代理，避免 httpx 在
        # 请求路由前初始化无关的 SOCKS transport。
        self._client = client or httpx.Client(
            timeout=self.timeout,
            trust_env=False,
        )

    @staticmethod
    def _prepare_image(image_bytes: bytes, max_edge: int, min_edge: int) -> str:
        """缩放图片（U6 实测上限，超出等比缩小）并编码 data URL。"""
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = img.size
        longest = max(width, height)
        if longest > max_edge:
            scale = max_edge / longest
            new_size = (
                max(min_edge, int(width * scale)),
                max(min_edge, int(height * scale)),
            )
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    @staticmethod
    def _prompt_for(block_type: str) -> str:
        return PROMPTS.get(block_type, PROMPTS["text"])

    def ocr_block_sync(
        self,
        image_bytes: bytes,
        block_type: str,
        *,
        page_index: int = 0,
        bbox: list[float] | None = None,
    ) -> str:
        data_url = self._prepare_image(image_bytes, self.max_edge, self.min_edge)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": self._prompt_for(block_type)},
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self._client.post(self.server_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = (
                    data.get("choices", [{}])[0].get("message", {}).get("content") or ""
                ).strip()
                if not content:
                    raise OcrBlockError("GLM-OCR 返回空内容")
                if attempt > 0:
                    logger.info(
                        "GLM-OCR 块级重试成功",
                        page=page_index,
                        block_type=block_type,
                        attempts=attempt + 1,
                    )
                return content
            except Exception as exc:  # noqa: BLE001 - OCR 服务异常统一重试（U13）
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise OcrBlockError(
            f"GLM-OCR 块识别失败（page={page_index}, type={block_type}, "
            f"bbox={bbox}）：{last_error}"
        )


_backend: GLMOCRBackend | None = None


def get_ocr_backend() -> GLMOCRBackend:
    """全局 GLM-OCR 后端单例（唯一实现，U13 无回退）。"""
    global _backend
    if _backend is None:
        _backend = GLMOCRBackend()
        logger.info(
            "GLM-OCR 后端已初始化",
            server_url=settings.GLMOCR_SERVER_URL,
            model=settings.GLMOCR_MODEL,
        )
    return _backend
