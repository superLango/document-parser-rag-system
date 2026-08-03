"""图像增强模块（阶段 2，条件触发）。

仅在 ``ImageQualityAssessor`` 判定 ``needs_enhancement=True`` 时调用，
对低质量扫描页做 CLAHE 对比度增强 + Top-Hat 淡色文本提取。

关键修正：CLAHE ``clipLimit`` 从原方案的 3.0 降至 **2.0**。
依据：theneuralbase 2026-04 验证，``clipLimit > 2.5`` 会产生椒盐噪声，
被 OCR 误判为标点符号，降低识别准确率。2.0 为保守安全值。

处理流程：
1. **CLAHE 增强 L 通道对比度**（clipLimit=2.0，tileGridSize=8x8）
   在 LAB 颜色空间的亮度通道上应用，避免颜色失真。
2. **Top-Hat 形态学操作**提取浅色细小文本（注解、页脚小字）
   Top-Hat = 原图 − 开运算结果，提取比周围亮的细小区域。
3. **叠加**到灰度图，强化淡色内容。

使用示例：
    from app.services.image_enhancer import ImageEnhancer

    enhancer = ImageEnhancer()
    enhanced = enhancer.enhance(pil_image)
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.core.logging import get_logger

logger = get_logger(__name__)


class ImageEnhancer:
    """图像增强器（条件触发，非全量处理）。

    仅在图像质量评估判定 ``needs_enhancement=True`` 时调用。
    对低质量扫描页应用 CLAHE + Top-Hat 增强，强化淡色注解文本。

    Attributes:
        CLAHE_CLIP_LIMIT: CLAHE 截断限制，2.0（保守值，避免噪声）。
        CLAHE_TILE_GRID: CLAHE 分块网格，(8, 8)。
        TOPHAT_KERNEL_SIZE: Top-Hat 形态学核大小，15。
    """

    # ★ clipLimit 从原方案 3.0 修正：阶段 2 测试噪声 9.37% 未达标（>5%），
    # 按方案文档风险表回退策略，降至 1.5（保守值，避免椒盐噪声被 OCR 误判）
    # 依据：clipLimit > 2.5 会产生椒盐噪声，2.0 在高亮度页仍噪声偏高
    CLAHE_CLIP_LIMIT: float = 1.5
    CLAHE_TILE_GRID: tuple = (8, 8)
    # Top-Hat 核大小：提取浅色细小文本（注解、小字）
    # 15→9：减小核降低 morphologyEx 耗时（大图 118ms→~70ms），且对注解小文本提取更精准
    TOPHAT_KERNEL_SIZE: int = 9

    def enhance(self, image: Image.Image) -> Image.Image:
        """对低质量图像应用 CLAHE + Top-Hat 增强。

        仅在图像质量评估判定 ``needs_enhancement=True`` 时调用。
        处理流程：CLAHE 增强 L 通道 → Top-Hat 提取淡色文本 → 叠加。

        Args:
            image: PIL 图像。

        Returns:
            Image.Image: 增强后的 RGB PIL 图像。
        """
        img = np.array(image.convert("RGB"))

        # 1. CLAHE 增强对比度（clipLimit=2.0，保守值）
        # 在 LAB 颜色空间的 L 通道上应用，避免颜色失真
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(
            clipLimit=self.CLAHE_CLIP_LIMIT,
            tileGridSize=self.CLAHE_TILE_GRID,
        )
        l = clahe.apply(l)
        lab = cv2.merge((l, a, b))
        img = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

        # 2. Top-Hat 提取浅色细小文本（注解、页脚小字）
        # Top-Hat = 原图 - 开运算结果，提取比周围亮的细小区域
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (self.TOPHAT_KERNEL_SIZE, self.TOPHAT_KERNEL_SIZE),
        )
        tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
        enhanced = cv2.add(gray, tophat)

        return Image.fromarray(enhanced).convert("RGB")


# 模块级单例
image_enhancer = ImageEnhancer()
