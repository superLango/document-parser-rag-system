"""嵌入模型配置模块。

从 ``app.core.config.settings`` 读取 bge-m3 嵌入相关配置，
作为 embedding 服务的统一配置入口。
"""

from __future__ import annotations

from app.core.config import settings


class EmbeddingConfig:
    """嵌入模型配置单例。

    整合 ``settings`` 中的 bge-m3 配置项：
    - 模型路径
    - 批量大小
    """

    def __init__(self) -> None:
        self.model_path: str = settings.EMBEDDING_MODEL_PATH
        self.batch_size: int = settings.EMBEDDING_BATCH_SIZE


embedding_config = EmbeddingConfig()
