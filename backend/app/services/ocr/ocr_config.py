"""OCR 模块配置整合。

从 ``app.core.config.settings`` 读取 GLM-OCR 相关配置，
并提供将环境变量注入 SDK ``load_config()`` 的桥接方法。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class OcrConfig:
    """OCR 模块配置单例。

    整合 ``settings`` 中的 GLM-OCR 配置项，提供：
    - vLLM 端点、模型名、API Key
    - PDF 渲染 DPI
    - 并发数、最大 token 数
    - OCR 输出目录
    - 文本清洗等级
    """

    def __init__(self) -> None:
        self.vllm_endpoint: str = settings.GLMOCR_SERVER_URL
        self.vllm_model: str = settings.GLMOCR_MODEL
        self.api_key: str = settings.GLMOCR_API_KEY
        self.pdf_dpi: int = settings.GLMOCR_PDF_DPI
        self.max_concurrency: int = settings.GLMOCR_MAX_CONCURRENCY
        self.max_tokens: int = settings.GLMOCR_MAX_TOKENS
        self.clean_level: str = settings.OCR_CLEAN_LEVEL
        self.output_dir: str = getattr(settings, "OCR_OUTPUT_DIR", "./data/ocr_data")

        # PP-DocLayoutV3 模型路径（从环境变量读取或使用默认 HF 缓存）
        self.layout_model_dir: str = os.environ.get(
            "GLMOCR_LAYOUT_MODEL_DIR",
            "/home/hanson/.cache/huggingface/hub/"
            "models--PaddlePaddle--PP-DocLayoutV3_safetensors/"
            "snapshots/a0abee1e2bb505e5662993235af873a5d89851e3",
        )

    def get_task_output_dir(self, task_id: str, kb_id=None) -> Path:
        """返回任务输出目录（自动创建）。

        - ``kb_id`` 为 None：``data/ocr_data/{task_id}/``（向后兼容旧流程）。
        - ``kb_id`` 不为 None：``data/ocr_data/{kb_id}/{task_id}/``（KB 物理隔离）。

        Args:
            task_id: 任务 ID。
            kb_id: 知识库 ID（uuid.UUID 或 None）。

        Returns:
            Path: 任务输出目录路径。
        """
        if kb_id is None:
            task_dir = Path(self.output_dir) / task_id
        else:
            task_dir = Path(self.output_dir) / str(kb_id) / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def build_sdk_overrides(self) -> Dict[str, Any]:
        """将 settings 转为 SDK ``load_config()`` 接受的 overrides。

        通过环境变量 ``GLMOCR_*`` 注入 SDK 内部配置，
        避免修改 ``ocr_util/config.yaml``。

        Returns:
            Dict 传递给 ``load_config(**overrides)`` 的关键字参数。
        """
        # 从 vllm_endpoint 解析 host 和 port
        # 格式: http://127.0.0.1:9977/v1
        endpoint = self.vllm_endpoint.rstrip("/")
        # 去掉 http:// 或 https://
        if "://" in endpoint:
            host_port = endpoint.split("://", 1)[1]
        else:
            host_port = endpoint
        # 去掉路径部分
        if "/" in host_port:
            host_port = host_port.split("/", 1)[0]
        # 分割 host 和 port
        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 9977

        overrides: Dict[str, Any] = {
            "pipeline.ocr_api.api_host": host,
            "pipeline.ocr_api.api_port": port,
            "pipeline.ocr_api.model": self.vllm_model,
            "pipeline.enable_layout": True,
        }

        if self.api_key:
            overrides["pipeline.ocr_api.api_key"] = self.api_key

        return overrides

    def apply_env(self) -> None:
        """设置环境变量供 SDK ``load_config()`` 读取。

        SDK 的 ``load_config()`` 会读取 ``GLMOCR_*`` 环境变量，
        此方法确保环境变量与 settings 同步。
        """
        os.environ["GLMOCR_OCR_API_HOST"] = self.vllm_endpoint.split("://")[1].split("/")[0].split(":")[0] if "://" in self.vllm_endpoint else "127.0.0.1"
        os.environ["GLMOCR_ENABLE_LAYOUT"] = "true"
        os.environ["GLMOCR_LAYOUT_MODEL_DIR"] = self.layout_model_dir
        os.environ["CUDA_VISIBLE_DEVICES"] = os.environ.get("CUDA_VISIBLE_DEVICES", "0")

        # 从 endpoint 解析 port
        try:
            port_part = self.vllm_endpoint.split(":")[-1].split("/")[0]
            os.environ["GLMOCR_OCR_API_PORT"] = port_part
        except (IndexError, ValueError):
            os.environ["GLMOCR_OCR_API_PORT"] = "9977"

        os.environ["GLMOCR_OCR_MODEL"] = self.vllm_model


ocr_config = OcrConfig()
