"""GLM-OCR 自托管模式独立工具模块。

从 glmocr SDK 提取的自托管文档解析能力，封装为可直接调用的工具模块。
ocr_service 直接操控底层组件（PageLoader / PPDocLayoutDetector / OCRClient /
ResultFormatter）实现最大化并行，不再使用 Pipeline 三线程流水线封装。

用法::

    from app.services.ocr.ocr_util.ocr_util_config import load_config
    from app.services.ocr.ocr_util.dataloader import PageLoader
    from app.services.ocr.ocr_util.layout import PPDocLayoutDetector
    from app.services.ocr.ocr_util.ocr_client import OCRClient
    from app.services.ocr.ocr_util.postprocess import ResultFormatter
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__version__ = "0.1.1-local"
__author__ = "ZHIPUAI (extracted self-hosted module)"

__all__ = [
    "dataloader",
    "layout",
    "postprocess",
    "utils",
    "GlmOcrConfig",
    "load_config",
]

_LAZY_SUBMODULES = {"dataloader", "layout", "postprocess", "utils"}
_LAZY_ATTRS = {
    "GlmOcrConfig": ("config", "GlmOcrConfig"),
    "load_config": ("config", "load_config"),
}


def __getattr__(name: str):
    """惰性加载子模块与属性，避免导入即加载 torch 等重依赖。"""
    if name in _LAZY_SUBMODULES:
        return importlib.import_module(f"{__name__}.{name}")

    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    module_name, attr_name = target
    module = importlib.import_module(f"{__name__}.{module_name}")
    return getattr(module, attr_name)


def __dir__():
    return sorted(list(globals().keys()) + list(__all__))


if TYPE_CHECKING:  # pragma: no cover
    from . import dataloader, layout, postprocess, utils
    from .config import GlmOcrConfig, load_config
