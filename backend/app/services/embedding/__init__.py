"""bge-m3 嵌入服务（从 services 根目录迁入，保持单一数据源）。"""

from app.services.embedding.embedding_service import EmbeddingService, embedding_service

__all__ = ["EmbeddingService", "embedding_service"]
