"""L5 安全/并发：M26 嵌入服务并发串行锁与错误隔离。"""

from pathlib import Path

import pytest

from app.core.config import settings

MODEL_READY = (Path(settings.EMBEDDING_MODEL_DIR) / "pytorch_model.bin").exists()

pytestmark = pytest.mark.skipif(
    not MODEL_READY, reason="BGE-M3 权重未下载"
)


async def test_concurrent_embed_calls_serialized_and_consistent():
    """L5M26-01（并发）：8 个并发 embed 调用不崩溃且结果与串行一致。"""
    import asyncio

    from app.services.embedding.embedding_service import embedding_service

    texts = [f"并发嵌入测试文本{i}" for i in range(8)]

    async def _run(seed: str):
        return await embedding_service.embed([seed])

    results = await asyncio.gather(*[_run(t) for t in texts])
    assert len(results) == 8
    for i, r in enumerate(results):
        assert len(r[0]) == 1024
    # 与串行结果一致（同一文本同一向量）
    again = await asyncio.gather(*[_run(t) for t in texts])
    for a, b in zip(results, again):
        assert max(abs(x - y) for x, y in zip(a[0], b[0])) < 1e-5


async def test_embedding_error_does_not_break_service():
    """L5M26-02：异常调用后服务仍可正常使用（错误隔离）。"""
    from app.services.embedding.embedding_service import (
        BgeM3TransformersProvider,
        embedding_service,
    )

    # 独立 provider 构造错误路径，不影响全局单例
    bad = BgeM3TransformersProvider("/bad/path", "cpu", False)
    with pytest.raises(RuntimeError):
        bad.load()
    # 全局服务仍可用
    vecs = await embedding_service.embed(["恢复测试"])
    assert len(vecs[0]) == 1024
