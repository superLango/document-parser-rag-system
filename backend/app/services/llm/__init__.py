"""vLLM 大模型服务封装（从 services 根目录迁入，保持单一数据源）。"""

from app.services.llm.llm_service import LLMService, llm_service

__all__ = ["LLMService", "llm_service"]
