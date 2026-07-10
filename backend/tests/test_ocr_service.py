"""OCR 识别服务测试模块。

测试 OCRService 的核心功能：
- 懒加载机制：__init__ 不加载模型
- recognize_with_layout()：返回结构校验
- 错误处理：无效图像字节流

所有测试通过 mock 避免加载真实 PaddleOCR-VL 模型，确保无 GPU 环境可运行。
"""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.core.exceptions import BusinessException
from app.services.ocr_service import OCRService, _label_to_type, _prompt_for_label


# ---------------------------------------------------------------
# 辅助函数：生成测试图像字节
# ---------------------------------------------------------------
def _make_image_bytes(width: int = 100, height: int = 50, color: str = "white") -> bytes:
    """生成 PNG 格式的测试图像字节流。

    Args:
        width: 图像宽度。
        height: 图像高度。
        color: 背景颜色。

    Returns:
        bytes: PNG 图像字节流。
    """
    img = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------
# 懒加载测试
# ---------------------------------------------------------------
class TestLazyLoading:
    """OCRService 懒加载机制测试。"""

    def test_model_not_loaded_in_init(self):
        """测试 __init__ 不加载模型。

        构造 OCRService 后，_model / _processor / _pipeline 均应为 None，
        _loaded 应为 False。
        """
        service = OCRService(model_path="/fake/path")

        assert service._model is None
        assert service._processor is None
        assert service._pipeline is None
        assert service._layout_detector is None
        assert service._loaded is False
        assert service._backend is None

    def test_model_path_stored(self):
        """测试构造时保存模型路径。"""
        service = OCRService(model_path="/custom/model/path")

        assert service.model_path == "/custom/model/path"

    def test_inference_lock_initialized(self):
        """测试构造时初始化推理锁。"""
        service = OCRService(model_path="/fake/path")

        assert service._inference_lock is not None

    def test_load_model_skipped_when_already_loaded(self):
        """测试已加载时 _load_model 直接返回不重复加载。"""
        service = OCRService(model_path="/fake/path")
        service._loaded = True
        service._backend = "paddleocr-vl"

        # 应直接返回不执行任何加载逻辑
        service._load_model()

        assert service._model is None  # 未触发加载


# ---------------------------------------------------------------
# _to_pil 测试
# ---------------------------------------------------------------
class TestToPil:
    """_to_pil 静态方法测试。"""

    def test_to_pil_from_bytes(self):
        """测试从字节流转换为 PIL 图像。"""
        img_bytes = _make_image_bytes(80, 60, "red")

        img = OCRService._to_pil(img_bytes)

        assert img.size == (80, 60)
        assert img.mode == "RGB"

    def test_to_pil_from_pil_image(self):
        """测试直接传入 PIL 图像时返回 RGB 转换结果。"""
        original = Image.new("RGBA", (50, 50), "blue")

        img = OCRService._to_pil(original)

        assert img.mode == "RGB"
        assert img.size == (50, 50)

    def test_to_pil_invalid_bytes_raises(self):
        """测试无效字节流时抛出 BusinessException。"""
        with pytest.raises(BusinessException) as exc_info:
            OCRService._to_pil(b"not an image")

        assert "无法解析输入图像" in exc_info.value.message

    def test_to_pil_empty_bytes_raises(self):
        """测试空字节流时抛出 BusinessException。"""
        with pytest.raises(BusinessException):
            OCRService._to_pil(b"")


# ---------------------------------------------------------------
# recognize_with_layout() 测试
# ---------------------------------------------------------------
class TestRecognizeWithLayout:
    """recognize_with_layout 方法测试。"""

    @pytest.mark.asyncio
    async def test_recognize_with_layout_return_structure(self):
        """测试 recognize_with_layout 返回结构正确。

        Mock 模型加载与 pipeline 推理，验证返回 dict 包含
        text / layout / pages 三个键。
        """
        service = OCRService(model_path="/fake/path")
        img_bytes = _make_image_bytes(100, 100)

        # Mock 模型加载为空操作
        service._load_model = MagicMock()
        service._loaded = True
        service._backend = "paddleocr-vl"

        # Mock pipeline 后端的识别结果
        expected_result = {
            "text": "测试文本",
            "layout": [
                {
                    "type": "text",
                    "bbox": [0, 0, 100, 50],
                    "text": "测试文本",
                }
            ],
            "pages": 1,
        }
        service._recognize_with_layout_pipeline = MagicMock(return_value=expected_result)

        result = await service.recognize_with_layout(img_bytes)

        assert "text" in result
        assert "layout" in result
        assert "pages" in result
        assert result["text"] == "测试文本"
        assert result["pages"] == 1
        assert len(result["layout"]) == 1
        assert result["layout"][0]["type"] == "text"
        assert result["layout"][0]["text"] == "测试文本"
        assert len(result["layout"][0]["bbox"]) == 4

    @pytest.mark.asyncio
    async def test_recognize_with_layout_transformers_backend(self):
        """测试 transformers 后端的返回结构。"""
        service = OCRService(model_path="/fake/path")
        img_bytes = _make_image_bytes(100, 100)

        service._load_model = MagicMock()
        service._loaded = True
        service._backend = "transformers"

        expected_result = {
            "text": "transformers 后端文本",
            "layout": [],
            "pages": 1,
        }
        service._recognize_with_layout_transformers = MagicMock(
            return_value=expected_result
        )

        result = await service.recognize_with_layout(img_bytes)

        assert result["text"] == "transformers 后端文本"
        assert result["pages"] == 1

    @pytest.mark.asyncio
    async def test_recognize_with_layout_invalid_image_raises(self):
        """测试无效图像字节时抛出 BusinessException。"""
        service = OCRService(model_path="/fake/path")

        with pytest.raises(BusinessException) as exc_info:
            await service.recognize_with_layout(b"invalid image bytes")

        assert "无法解析输入图像" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_recognize_with_layout_pil_input(self):
        """测试直接传入 PIL Image 时的处理。"""
        service = OCRService(model_path="/fake/path")
        pil_image = Image.new("RGB", (100, 100), "white")

        service._load_model = MagicMock()
        service._loaded = True
        service._backend = "paddleocr-vl"

        expected_result = {"text": "PIL 输入测试", "layout": [], "pages": 1}
        service._recognize_with_layout_pipeline = MagicMock(
            return_value=expected_result
        )

        result = await service.recognize_with_layout(pil_image)

        assert result["text"] == "PIL 输入测试"


# ---------------------------------------------------------------
# recognize() 测试
# ---------------------------------------------------------------
class TestRecognize:
    """recognize 方法测试。"""

    @pytest.mark.asyncio
    async def test_recognize_returns_text(self):
        """测试 recognize 返回纯文本。"""
        service = OCRService(model_path="/fake/path")
        img_bytes = _make_image_bytes(100, 50)

        service._load_model = MagicMock()
        service._loaded = True
        service._backend = "paddleocr-vl"

        service._infer_pipeline_text = MagicMock(return_value="识别结果文本")

        text = await service.recognize(img_bytes)

        assert text == "识别结果文本"

    @pytest.mark.asyncio
    async def test_recognize_invalid_bytes_raises(self):
        """测试无效字节流时抛出 BusinessException。"""
        service = OCRService(model_path="/fake/path")

        with pytest.raises(BusinessException):
            await service.recognize(b"not an image")


# ---------------------------------------------------------------
# recognize_batch() 测试
# ---------------------------------------------------------------
class TestRecognizeBatch:
    """recognize_batch 方法测试。"""

    @pytest.mark.asyncio
    async def test_recognize_batch_empty_list(self):
        """测试空列表输入返回空列表。"""
        service = OCRService(model_path="/fake/path")

        result = await service.recognize_batch([])

        assert result == []

    @pytest.mark.asyncio
    async def test_recognize_batch_multiple_images(self):
        """测试批量识别多张图像。"""
        service = OCRService(model_path="/fake/path")
        images = [_make_image_bytes(), _make_image_bytes(), _make_image_bytes()]

        # Mock recognize 方法返回不同结果
        service.recognize = AsyncMock(
            side_effect=["文本1", "文本2", "文本3"]
        )

        results = await service.recognize_batch(images)

        assert len(results) == 3
        assert results[0] == "文本1"
        assert results[1] == "文本2"
        assert results[2] == "文本3"


# ---------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------
class TestLabelToType:
    """_label_to_type 辅助函数测试。"""

    def test_label_to_type_title(self):
        """测试标题类标签归并为 title。"""
        assert _label_to_type("doc_title") == "title"
        assert _label_to_type("paragraph_title") == "title"
        assert _label_to_type("figure_title") == "title"

    def test_label_to_type_table(self):
        """测试表格类标签归并为 table。"""
        assert _label_to_type("table") == "table"

    def test_label_to_type_figure(self):
        """测试图像/图表类标签归并为 figure。"""
        assert _label_to_type("image") == "figure"
        assert _label_to_type("chart") == "figure"
        assert _label_to_type("seal") == "figure"

    def test_label_to_type_text_default(self):
        """测试其余标签归并为 text。"""
        assert _label_to_type("text") == "text"
        assert _label_to_type("aside_text") == "text"
        assert _label_to_type("unknown_label") == "text"


class TestPromptForLabel:
    """_prompt_for_label 辅助函数测试。"""

    def test_prompt_for_table(self):
        """测试表格标签返回表格识别提示词。"""
        assert "Table" in _prompt_for_label("table")

    def test_prompt_for_chart(self):
        """测试图表标签返回图表识别提示词。"""
        assert "Chart" in _prompt_for_label("chart")

    def test_prompt_for_text(self):
        """测试文本标签返回通用 OCR 提示词。"""
        assert _prompt_for_label("text") == "OCR:"

    def test_prompt_for_title(self):
        """测试标题标签返回通用 OCR 提示词。"""
        assert _prompt_for_label("doc_title") == "OCR:"


# ---------------------------------------------------------------
# warmup() 测试
# ---------------------------------------------------------------
class TestWarmup:
    """warmup 方法测试。"""

    @pytest.mark.asyncio
    async def test_warmup_loads_model(self):
        """测试 warmup 触发模型加载。"""
        service = OCRService(model_path="/fake/path")

        service._load_model = MagicMock()
        service._backend = "paddleocr-vl"
        service._run_pipeline = MagicMock()

        await service.warmup()

        service._load_model.assert_called_once()

    @pytest.mark.asyncio
    async def test_warmup_failure_raises_business_exception(self):
        """测试 warmup 失败时抛出 BusinessException。"""
        service = OCRService(model_path="/fake/path")

        service._load_model = MagicMock(side_effect=RuntimeError("加载失败"))

        with pytest.raises(BusinessException):
            await service.warmup()
