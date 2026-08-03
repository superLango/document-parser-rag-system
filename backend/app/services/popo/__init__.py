"""MinerU-Popo OCR 后处理模块。

使用 Qwen3-VL 4B 模型对 GLM-OCR 输出做四大后处理：
1. 文本截断分析（跨页段落合并）
2. 标题层级分析（识别章节层级）
3. 图文关联分析（图片与题注对应）
4. 表格截断分析（跨页表格合并）

所有组件均为本模块独立实现，不复用 ``app/popo/`` 原代码。

主要接口::

    from app.services.popo import popo_service

    # 完整后处理流程
    result = popo_service.reconstruct("task_id")
"""

from app.services.popo.markdown_renderer import render as render_markdown
from app.services.popo.normalizer import GlmOcrNormalizer, glm_ocr_normalizer
from app.services.popo.popo_inference import PopoInference, popo_inference
from app.services.popo.popo_service import PopoReconstructionService, popo_service
from app.services.popo.tree_builder import build_tree, count_nodes

__all__ = [
    # 归一化
    "GlmOcrNormalizer",
    "glm_ocr_normalizer",
    # 推理
    "PopoInference",
    "popo_inference",
    # 树构建
    "build_tree",
    "count_nodes",
    # Markdown 渲染
    "render_markdown",
    # 主服务
    "PopoReconstructionService",
    "popo_service",
]
