"""L4 边界异常：M26 嵌入服务。"""

from pathlib import Path

import pytest

from app.core.config import settings

MODEL_READY = (Path(settings.EMBEDDING_MODEL_DIR) / "pytorch_model.bin").exists()

pytestmark = pytest.mark.skipif(
    not MODEL_READY, reason="BGE-M3 权重未下载"
)


async def test_empty_texts_batch():
    """L4M26-01：空列表与空字符串混合不崩溃。"""
    from app.services.embedding.embedding_service import embedding_service

    assert await embedding_service.embed([]) == []
    vecs = await embedding_service.embed(["", "正常文本"])
    assert len(vecs) == 2
    assert len(vecs[1]) == 1024


async def test_long_text_truncated_within_limit():
    """L4M26-02：超长文本按 8192 token 截断不崩溃。"""
    from app.services.embedding.embedding_service import embedding_service

    long_text = "不锈钢材料标准内容。" * 20000  # 远超 8192 token
    vecs = await embedding_service.embed([long_text], max_length=2048)
    assert len(vecs) == 1 and len(vecs[0]) == 1024


async def test_single_char_text():
    """L4M26-03：单字符/纯符号文本正常编码。"""
    from app.services.embedding.embedding_service import embedding_service

    vecs = await embedding_service.embed(["A", "1", "≥"])
    assert len(vecs) == 3
    assert all(len(v) == 1024 for v in vecs)
