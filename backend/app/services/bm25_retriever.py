"""BM25 检索服务模块（P2.3 优化）。

在现有 Dense + Sparse 两路检索基础上增加 BM25 第三路检索，
通过 RRF 融合三路结果提升召回率（预期 +15%）。

设计要点：
- 使用 rank_bm25.BM25Okapi 实现轻量级 BM25 检索
- 使用 jieba 进行中文分词
- 懒加载：首次检索时从 Milvus 加载所有分块文本构建 BM25 索引
- 支持增量添加文档（文档入库时调用 add_documents）
- 支持按 doc_id 过滤

使用示例：
    from app.services.bm25_retriever import bm25_retriever

    # 检索（首次调用会自动从 Milvus 加载构建索引）
    results = await bm25_retriever.search("304不锈钢化学成分", top_k=10)

    # 文档入库时增量添加
    bm25_retriever.add_documents(chunks)
"""

import asyncio
from typing import Any

import jieba
from rank_bm25 import BM25Okapi

from app.core.logging import get_logger

logger = get_logger(__name__)

# 中文停用词（高频无意义词）
_STOP_WORDS: set[str] = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没",
    "看", "好", "自己", "这", "那", "与", "及", "或", "等", "为", "以", "于",
    "由", "从", "向", "对", "按", "据", "用", "把", "被", "让", "使", "给",
    "但", "而", "且", "则", "故", "若", "如", "虽", "虽", "然", "因", "所",
    "其", "此", "该", "某", "每", "各", "另", "并", "还", "已", "将", "正",
}


def _tokenize(text: str) -> list[str]:
    """中文分词 + 停用词过滤。

    使用 jieba 精确模式分词，过滤停用词和空白字符。

    Args:
        text: 待分词的文本。

    Returns:
        list[str]: 分词后的词项列表（已过滤停用词）。
    """
    if not text:
        return []
    tokens = jieba.lcut(text.strip())
    return [
        t for t in tokens
        if t.strip() and t not in _STOP_WORDS and len(t.strip()) > 0
    ]


class BM25Retriever:
    """BM25 检索器（P2.3 优化）。

    在内存中维护 BM25 索引，支持懒加载和增量更新。
    首次检索时自动从 Milvus 加载所有分块文本构建索引。

    Attributes:
        _bm25: BM25Okapi 实例，None 表示未构建。
        _corpus: 语料库，list[dict]，每项含 chunk_id、text、doc_id、metadata。
        _tokenized_corpus: 分词后的语料库，与 _corpus 一一对应。
        _built: 是否已构建索引。
        _building: 是否正在构建（防止并发重复构建）。
    """

    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._corpus: list[dict[str, Any]] = []
        self._tokenized_corpus: list[list[str]] = []
        self._built: bool = False
        self._building: bool = False

    async def _ensure_built(self) -> None:
        """确保 BM25 索引已构建（懒加载入口）。

        首次调用时从 Milvus 加载所有分块文本构建索引。
        使用 _building 标志防止并发重复构建。
        """
        if self._built or self._building:
            return
        self._building = True
        try:
            await self._build_from_milvus()
        finally:
            self._building = False

    async def _build_from_milvus(self) -> None:
        """从 Milvus 加载所有分块文本构建 BM25 索引。

        查询 Milvus 中所有记录的 chunk_id、text、doc_id、title_chain、metadata
        字段，构建 BM25 索引。数据量大时可能较慢，但仅在首次调用时执行。
        """
        from app.services.vector_store import vector_store

        logger.info("开始从 Milvus 构建 BM25 索引...")
        try:
            # 确保 Milvus 已连接（懒加载入口）
            vector_store._ensure_connected()
            # 查询 Milvus 中所有分块
            results = await asyncio.to_thread(
                vector_store._collection.query,
                expr="id >= 0",
                output_fields=["chunk_id", "text", "doc_id", "title_chain", "metadata"],
                limit=10000,
            )
        except Exception as err:
            logger.error("从 Milvus 加载分块失败", error=str(err))
            return

        if not results:
            logger.warning("Milvus 中无分块数据，BM25 索引为空")
            return

        # 构建语料库
        self._corpus = []
        self._tokenized_corpus = []
        for r in results:
            text = r.get("text", "")
            if not text or not text.strip():
                continue
            self._corpus.append(
                {
                    "chunk_id": r.get("chunk_id", ""),
                    "text": text,
                    "doc_id": r.get("doc_id", ""),
                    "title_chain": r.get("title_chain", ""),
                    "metadata": r.get("metadata", {}),
                }
            )
            self._tokenized_corpus.append(_tokenize(text))

        if self._tokenized_corpus:
            self._bm25 = BM25Okapi(self._tokenized_corpus)
        self._built = True

        logger.info(
            "BM25 索引构建完成",
            corpus_size=len(self._corpus),
        )

    def add_documents(self, chunks: list[dict]) -> None:
        """增量添加文档到 BM25 索引。

        文档入库时调用，将新分块追加到语料库并重建 BM25 索引。
        BM25Okapi 不支持增量更新，需要重建，但语料量小时重建很快。

        Args:
            chunks: 分块列表，每个分块需含 chunk_id、text、doc_id、metadata。
        """
        if not chunks:
            return

        for chunk in chunks:
            text = chunk.get("text", "")
            if not text or not text.strip():
                continue
            meta = chunk.get("metadata", {})
            self._corpus.append(
                {
                    "chunk_id": chunk.get("chunk_id", ""),
                    "text": text,
                    "doc_id": chunk.get("doc_id", meta.get("doc_id", "")),
                    "title_chain": meta.get("title_chain", ""),
                    "metadata": meta,
                }
            )
            self._tokenized_corpus.append(_tokenize(text))

        if self._tokenized_corpus:
            self._bm25 = BM25Okapi(self._tokenized_corpus)
            if not self._built:
                self._built = True

        logger.info("BM25 索引增量更新完成", added=len(chunks), total=len(self._corpus))

    def clear(self) -> None:
        """清空 BM25 索引（用于知识库重建）。"""
        self._bm25 = None
        self._corpus = []
        self._tokenized_corpus = []
        self._built = False
        logger.info("BM25 索引已清空")

    async def search(
        self,
        query: str,
        top_k: int = 10,
        doc_ids: list[str] | None = None,
    ) -> list[dict]:
        """BM25 检索。

        Args:
            query: 查询文本。
            top_k: 返回结果数。
            doc_ids: 限定检索的文档 ID 列表，None 表示不限制。

        Returns:
            list[dict]: 检索结果，按 BM25 分数降序排列，每项包含：
                - chunk_id: 分块唯一标识
                - text: 分块原文
                - doc_id: 所属文档 ID
                - title_chain: 文档标题层级链
                - metadata: 扩展元信息
                - score: BM25 分数
                - rank: 排名（从 1 开始）
        """
        if not query or not query.strip():
            return []

        await self._ensure_built()

        if self._bm25 is None or not self._corpus:
            logger.warning("BM25 索引未构建或为空")
            return []

        # 分词查询
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        # BM25 打分（在线程池中执行，避免阻塞事件循环）
        scores = await asyncio.to_thread(self._bm25.get_scores, query_tokens)

        # 按文档 ID 过滤（如指定）
        doc_id_set = set(doc_ids) if doc_ids else None

        # 收集结果并排序
        scored_results: list[tuple[float, dict]] = []
        for idx, score in enumerate(scores):
            if score <= 0:
                continue
            entry = self._corpus[idx]
            if doc_id_set and entry.get("doc_id") not in doc_id_set:
                continue
            scored_results.append((float(score), entry))

        # 按 BM25 分数降序排列
        scored_results.sort(key=lambda x: x[0], reverse=True)

        # 截取 top_k 并格式化输出
        results: list[dict] = []
        for rank, (score, entry) in enumerate(scored_results[:top_k]):
            results.append(
                {
                    "chunk_id": entry.get("chunk_id", ""),
                    "text": entry.get("text", ""),
                    "doc_id": entry.get("doc_id", ""),
                    "title_chain": entry.get("title_chain", ""),
                    "metadata": entry.get("metadata", {}),
                    "score": score,
                    "rank": rank + 1,
                }
            )

        logger.info(
            "BM25 检索完成",
            query_preview=query[:50],
            top_k=top_k,
            result_count=len(results),
        )
        return results

    def get_stats(self) -> dict[str, Any]:
        """获取 BM25 索引统计信息。"""
        return {
            "built": self._built,
            "corpus_size": len(self._corpus),
        }


# 模块级单例
bm25_retriever = BM25Retriever()
