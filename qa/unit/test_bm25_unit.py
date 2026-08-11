"""L1 单元测试：M29 jieba BM25（分词/计数/打分/统计）。"""

import uuid

from app.services.indexing.bm25 import (
    bm25_score,
    chunk_token_counts,
    tokenize_text,
)


def test_tokenize_standard_and_elements():
    """L1M29-01：标准号/元素符号/数值范围/中文混合分词。"""
    tokens = tokenize_text("抗拉强度按 GB/T 228.1 执行，C 含量 0.015~0.060。")
    assert "GB/T" in tokens
    assert "228.1" in tokens
    assert "C" in tokens
    assert "0.015~0.060" in tokens
    assert "抗拉强度" in tokens
    # 标点不作为词元
    assert "，" not in tokens and "。" not in tokens


def test_tokenize_empty_and_symbols():
    """L1M29-02：空文本/纯符号不产生词元。"""
    assert tokenize_text("") == []
    assert tokenize_text("，。！？") == []
    assert tokenize_text("≥ ≤ ± ℃ ×") == []


def test_chunk_token_counts():
    """L1M29-03：块词元计数。"""
    counts = chunk_token_counts("不锈钢 C Cr，C 含量 0.060")
    assert counts["C"] == 2
    assert counts.get("Cr") == 1
    assert "，".__class__ is str


def test_bm25_score_idf_penalizes_common():
    """L1M29-04：高频词 idf 低，同频率得分低于低频词。"""
    common = bm25_score(term_freq=2, doc_len=50, avg_dl=50, n_docs=1000, doc_freq=800)
    rare = bm25_score(term_freq=2, doc_len=50, avg_dl=50, n_docs=1000, doc_freq=5)
    assert rare > common


def test_bm25_score_frequency_increases():
    """L1M29-05：词频越高得分越高（其余相同）。"""
    low = bm25_score(1, 50, 50, 100, 10)
    high = bm25_score(3, 50, 50, 100, 10)
    assert high > low


def test_bm25_score_zero_avgdl():
    """L1M29-06：avg_dl<=0 时得分为 0（防御）。"""
    assert bm25_score(1, 10, 0, 100, 10) == 0.0
