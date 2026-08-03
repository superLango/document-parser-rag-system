"""图像质量评估模块（阶段 2）。

借鉴 BlurDetection2 + Dynamsoft 方案，在 OCR 前评估扫描页图像质量，
决定是否需要触发条件增强。

评估维度：
1. **模糊度**：Laplacian 方差（越小越模糊）
2. **对比度**：灰度标准差（越小对比度越低）
3. **亮度**：灰度均值（过高/过低均异常）

仅当质量评估判定 ``needs_enhancement=True`` 时，才触发
``ImageEnhancer`` 做条件增强，避免对高质量图像过度处理引入噪声。

使用示例：
    from app.services.image_quality import ImageQualityAssessor

    assessor = ImageQualityAssessor()
    quality = assessor.assess(pil_image)
    if quality.needs_enhancement:
        # 触发 ImageEnhancer.enhance
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ImageQuality:
    """图像质量评估结果。

    Attributes:
        blur_score: Laplacian 方差，越小越模糊。
        contrast_score: 对比度（灰度标准差），越小对比度越低。
        brightness: 亮度（灰度均值），过高/过低均为异常。
        needs_enhancement: 是否需要增强。
        quality_level: 质量等级，"good" / "fair" / "poor"。
    """

    blur_score: float
    contrast_score: float
    brightness: float
    needs_enhancement: bool
    quality_level: str


class ImageQualityAssessor:
    """图像质量评估器。

    在 OCR 前评估扫描页图像质量，决定是否触发增强。
    评估三个维度：模糊度、对比度、亮度，任一异常即判定需要增强。

    阈值依据：
        - ``BLUR_THRESHOLD=100``：Laplacian 方差低于此值判定为模糊。
          正常扫描页通常 >100，模糊页 <50。
        - ``CONTRAST_THRESHOLD=40``：灰度标准差低于此值判定为低对比度。
          正常文本页通常 50-80，低对比度页 <40（淡色扫描件）。
        - ``BRIGHTNESS_TOO_HIGH/LOW=200/50``：亮度超出此范围为过曝/欠曝。

    Attributes:
        BLUR_THRESHOLD: 模糊度阈值（Laplacian 方差）。
        CONTRAST_THRESHOLD: 对比度阈值（灰度标准差）。
        BRIGHTNESS_TOO_HIGH: 亮度过高阈值。
        BRIGHTNESS_TOO_LOW: 亮度过低阈值。
    """

    # 模糊度阈值（Laplacian 方差）
    # 低于此值认为图像模糊，需增强
    BLUR_THRESHOLD: float = 100.0
    # 对比度阈值（灰度标准差）
    # 低于此值认为对比度不足（淡色扫描），需增强
    CONTRAST_THRESHOLD: float = 40.0
    # 亮度异常阈值
    # 白底扫描件正常亮度 220-245，>250 才算过曝（需增强）
    # 原 200 过低，会把正常白底扫描页误判为过曝（实测触发率 64.5%）
    BRIGHTNESS_TOO_HIGH: float = 250.0
    BRIGHTNESS_TOO_LOW: float = 50.0

    def assess(self, image: Image.Image) -> ImageQuality:
        """评估图像质量。

        Args:
            image: PIL 图像（任意模式，内部统一转灰度）。

        Returns:
            ImageQuality: 质量评估结果。
        """
        gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)

        # 1. 模糊度：Laplacian 方差，越小越模糊
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # 2. 对比度：灰度标准差，越小对比度越低
        contrast_score = float(gray.std())

        # 3. 亮度：灰度均值
        brightness = float(gray.mean())

        # 4. 综合判断是否需要增强（任一维度异常即触发）
        needs_enhancement = (
            blur_score < self.BLUR_THRESHOLD
            or contrast_score < self.CONTRAST_THRESHOLD
            or brightness > self.BRIGHTNESS_TOO_HIGH
            or brightness < self.BRIGHTNESS_TOO_LOW
        )

        if blur_score < self.BLUR_THRESHOLD * 0.5:
            quality_level = "poor"
        elif needs_enhancement:
            quality_level = "fair"
        else:
            quality_level = "good"

        return ImageQuality(
            blur_score=blur_score,
            contrast_score=contrast_score,
            brightness=brightness,
            needs_enhancement=needs_enhancement,
            quality_level=quality_level,
        )


# 模块级单例，避免重复实例化
image_quality_assessor = ImageQualityAssessor()
