"""L1 单元测试：M26 BGE-M3 嵌入服务（配置/单例/空输入/缺失模型）。"""

import asyncio

import pytest

from app.core.config import settings


def test_embedding_config_defaults():
    """L1M26-01：嵌入配置默认值（D2：BGE-M3 1024 维）。"""
    assert settings.EMBEDDING_DIM == 1024
    assert settings.EMBEDDING_MAX_LENGTH == 8192
    assert settings.EMBEDDING_BATCH_SIZE == 16
    assert settings.EMBEDDING_MODEL_DIR.endswith("models/bge-m3")


def test_embedding_service_singleton():
    """L1M26-02：EmbeddingService 为单例。"""
    from app.services.embedding.embedding_service import EmbeddingService

    a = EmbeddingService()
    b = EmbeddingService()
    assert a is b


def test_embedding_service_dimension():
    """L1M26-03：dimension 属性返回 1024。"""
    from app.services.embedding.embedding_service import embedding_service

    assert embedding_service.dimension == 1024


async def test_embed_empty_list_short_circuit():
    """L1M26-04：空列表不触发模型加载/加锁。"""
    from app.services.embedding.embedding_service import embedding_service

    assert await embedding_service.embed([]) == []


def test_provider_missing_model_raises():
    """L1M26-05：模型目录缺失时给出明确 RuntimeError。"""
    from app.services.embedding.embedding_service import BgeM3TransformersProvider

    provider = BgeM3TransformersProvider(
        model_dir="/nonexistent/bge-m3", device="cpu", fp16=False
    )
    with pytest.raises(RuntimeError, match="embedding_model.py"):
        provider.load()


def test_provider_encode_empty_returns_empty_array():
    """L1M26-07：provider 直接编码空列表返回 (0, dim) 空数组。"""
    import numpy as np

    from app.services.embedding.embedding_service import BgeM3TransformersProvider

    provider = BgeM3TransformersProvider(
        model_dir="/nonexistent/bge-m3", device="cpu", fp16=False
    )
    out = provider.encode([], batch_size=16, max_length=8192)
    assert isinstance(out, np.ndarray)
    assert out.shape == (0, 1024)


async def test_embed_lock_initialized():
    """L1M26-06：服务实例持有串行锁。"""
    from app.services.embedding.embedding_service import embedding_service

    assert embedding_service._embed_lock is not None
    assert isinstance(embedding_service._embed_lock, asyncio.Lock)
