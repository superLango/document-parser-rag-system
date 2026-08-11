"""L2 集成 + L3 功能：M26 真实 BGE-M3 嵌入（维度/归一化/语义 + 分块链路）。"""

import json
from pathlib import Path

import pytest

from app.core.config import settings

MODEL_READY = (Path(settings.EMBEDDING_MODEL_DIR) / "pytorch_model.bin").exists()

pytestmark = pytest.mark.skipif(
    not MODEL_READY, reason="BGE-M3 权重未下载（scripts/download_embedding_model.py）"
)


async def test_real_embedding_dimension_and_normalized():
    """L2M26-01：真实模型输出 1024 维且 L2 归一化。"""
    from app.services.embedding.embedding_service import embedding_service

    vectors = await embedding_service.embed(["不锈钢化学成分"])
    assert len(vectors) == 1
    vec = vectors[0]
    assert len(vec) == 1024
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-3


async def test_embedding_semantic_similarity():
    """L2M26-02：中文语义相似性 sanity check（相关句 > 无关句）。"""
    from app.services.embedding.embedding_service import embedding_service

    vecs = await embedding_service.embed(
        ["抗拉强度应符合表1规定", "抗拉强度指标", "今天天气很好"]
    )

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))

    assert cos(vecs[0], vecs[1]) > cos(vecs[0], vecs[2])
    assert cos(vecs[0], vecs[1]) > 0.5


async def test_batch_embedding_consistent_with_single():
    """L2M26-03：批量与单条编码结果一致。"""
    from app.services.embedding.embedding_service import embedding_service

    texts = ["文本一", "文本二", "文本三", "文本四"]
    batch = await embedding_service.embed(texts, batch_size=2)
    single = [await embedding_service.embed([t]) for t in texts]
    for bv, sv in zip(batch, single):
        assert max(abs(x - y) for x, y in zip(bv, sv[0])) < 1e-5


async def test_warmup_then_embed():
    """L3M26-05：warmup 预热后可正常编码（懒加载路径）。"""
    from app.services.embedding.embedding_service import embedding_service

    await embedding_service.warmup()
    vecs = await embedding_service.embed(["预热后测试"])
    assert len(vecs[0]) == 1024


async def test_chunker_to_embedding_flow():
    """L3M26-04：分块产物（title/content 双文本）可编码。"""
    import json as _json
    from pathlib import Path as _Path

    from app.services.embedding.embedding_service import embedding_service
    from app.services.indexing.chunker import HierarchyChunker

    fixture = _json.loads(
        (_Path(__file__).parents[1] / "fixtures" / "layout_sample.json").read_text(
            encoding="utf-8"
        )
    )
    _, children = HierarchyChunker().chunk(fixture, "doc-emb")
    title_texts = [
        f"{c.hierarchy_path} {c.title}" for c in children
    ]
    content_texts = [c.content_for_embedding for c in children]
    t_vecs = await embedding_service.embed(title_texts)
    c_vecs = await embedding_service.embed(content_texts, max_length=2048)
    assert len(t_vecs) == len(children) == len(c_vecs)
    assert all(len(v) == 1024 for v in t_vecs + c_vecs)
