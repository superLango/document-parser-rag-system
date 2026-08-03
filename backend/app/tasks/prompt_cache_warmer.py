"""Prompt 缓存预热任务。

低峰期向 vLLM 发送包含静态前缀的 Prompt，触发 prefill 并驻留 KV cache，
提升生产请求的 prefix cache 命中率。

策略：
1. 遍历所有抽取类别的 schema 定义
2. 构造每个类别的静态 prompt 前缀（description 部分）
3. 发送 max_tokens=1 的 completions 请求到 vLLM
4. 串行执行，避免并发抢占 GPU
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("prompt_cache_warmer")


async def warmup_prompt_cache_task(ctx: dict) -> dict:
    """预热 vLLM prefix cache。

    遍历所有类别的静态 prompt 前缀，发送 1-token 请求触发 prefill。
    串行执行避免并发抢占生产 GPU。

    Args:
        ctx: arq 任务上下文。

    Returns:
        dict: 预热结果统计。
    """
    if not settings.EXTRACTION_PROMPT_CACHE_WARMUP_ENABLED:
        logger.info("Prompt 缓存预热已禁用，跳过")
        return {"status": "disabled", "warmed": 0}

    # TODO: extraction_service和extraction_schemas已删除，prompt缓存预热待重构
    logger.info("Prompt 缓存预热暂时跳过（extraction_service已重构）")
    return {"status": "skipped", "warmed": 0, "reason": "extraction_service已重构"}
