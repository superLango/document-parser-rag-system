"""KB 级 BM25 稀疏向量编码器（Milvus SPARSE_FLOAT_VECTOR 数据源）。

Milvus 2.4 支持 ``SPARSE_FLOAT_VECTOR`` 字段，但不提供内置 BM25F 全文
索引（那是 2.5 的特性），因此稀疏向量需要在**客户端**计算后写入。本模块
实现：

- 分词：jieba（中文）+ 正则提取 ASCII 词元（元素符号 C/Cr/Mo、标准号
  GB/T 223、数值 0.015~0.060 等），兼顾术语/编码类强词法信号。
- 每 KB 一份 BM25 模型：在 KB 的块语料上拟合并持久化（vocab → token_id、
  idf、avgdl），保证插入与查询的 token_id 一致。
- 编码：
  - ``encode_document(text)``：文档块 → ``{token_id: weight}``（稀疏向量）。
  - ``encode_query(text)``：查询文本 → ``{token_id: weight}``。

持久化：模型保存为 ``data/bm25/{kb_id_hex}.json``，索引变更时重建。
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from pathlib import Path

import jieba

from app.core.logging import get_logger

logger = get_logger(__name__)

# 英文/数字词元（含小数点、±、~、/ 等）：元素符号、标准号、数值范围
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[.~\-\+][A-Za-z0-9]+)*")


def tokenize_text(text: str) -> list[str]:
    """将文本切分为词元列表。

    策略：
    - 先用正则提取 ASCII 词元（元素符号 C、Cr、Mo；数值 0.015、0.060；标准号）
    - 剩余中文字符串用 jieba 切词
    结果按原顺序拼接，保证召回时对术语/编码类强信号敏感。
    """
    if not text:
        return []

    tokens: list[str] = []
    pos = 0
    for m in _ASCII_TOKEN_RE.finditer(text):
        # 两个 ASCII 词元之间的中文字段用 jieba 切
        if m.start() > pos:
            seg = text[pos:m.start()]
            tokens.extend(_jieba_cut(seg))
        tokens.append(m.group(0))
        pos = m.end()
    if pos < len(text):
        tokens.extend(_jieba_cut(text[pos:]))
    return tokens


def _jieba_cut(segment: str) -> list[str]:
    out: list[str] = []
    for tok in jieba.cut(segment):
        tok = tok.strip()
        if tok:
            out.append(tok)
    return out


class KBBM25:
    """单 KB 的 BM25 稀疏向量模型。

    属性:
        kb_id: 知识库 ID（用于持久化文件命名与日志）。
        k1: BM25 参数（默认 1.5）。
        b: BM25 参数（默认 0.75）。
    """

    def __init__(self, kb_id: str, k1: float = 1.5, b: float = 0.75) -> None:
        self.kb_id = str(kb_id)
        self.k1 = k1
        self.b = b
        self.vocab: dict[str, int] = {}  # token -> id
        self.idf: dict[str, float] = {}  # token -> idf
        self.doc_freq: dict[str, int] = {}
        self.avgdl: float = 0.0
        self.n_docs: int = 0

    # ------------------------------------------------------------------
    # 拟合与持久化
    # ------------------------------------------------------------------
    def fit(self, documents: list[str]) -> "KBBM25":
        """在块语料上拟合 BM25（统计 df / idf / avgdl，构建词表）。

        Args:
            documents: 每个块的文本（content + title）。
        """
        tokenized_docs: list[list[str]] = [
            tokenize_text(d) for d in documents
        ]
        self.n_docs = len(tokenized_docs)
        total_len = 0
        doc_freq: dict[str, int] = {}

        for toks in tokenized_docs:
            total_len += len(toks)
            for tok in set(toks):
                doc_freq[tok] = doc_freq.get(tok, 0) + 1

        self.doc_freq = doc_freq
        self.avgdl = (total_len / self.n_docs) if self.n_docs else 0.0

        # idf（平滑，避免 log 0）
        self.idf = {
            tok: math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))
            for tok, df in doc_freq.items()
        }
        # 构建稳定的 token -> id 词表（按 idf 降序，词表越靠前越具区分度）
        sorted_tokens = sorted(self.idf, key=lambda t: (-self.idf[t], t))
        self.vocab = {t: i for i, t in enumerate(sorted_tokens)}

        logger.info(
            "KBBM25 拟合完成",
            extra={"kb_id": self.kb_id, "n_docs": self.n_docs, "vocab_size": len(self.vocab)},
        )
        return self

    def save(self, directory: str | None = None) -> str:
        """持久化模型到 JSON 文件，返回文件路径。"""
        path = self._path(self.kb_id, directory)
        payload = {
            "kb_id": self.kb_id,
            "k1": self.k1,
            "b": self.b,
            "avgdl": self.avgdl,
            "n_docs": self.n_docs,
            "vocab": self.vocab,
            "idf": self.idf,
            "doc_freq": self.doc_freq,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, kb_id: str, directory: str | None = None) -> "KBBM25 | None":
        """从 JSON 文件加载模型，不存在返回 None。"""
        path = cls._path(kb_id, directory)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            m = cls(kb_id)
            m.k1 = data.get("k1", 1.5)
            m.b = data.get("b", 0.75)
            m.avgdl = data.get("avgdl", 0.0)
            m.n_docs = data.get("n_docs", 0)
            m.vocab = data.get("vocab", {})
            m.idf = {str(k): float(v) for k, v in data.get("idf", {}).items()}
            m.doc_freq = {str(k): int(v) for k, v in data.get("doc_freq", {}).items()}
            return m
        except Exception as exc:  # noqa: BLE001
            logger.warning("KBBM25 加载失败，将重建", extra={"kb_id": kb_id, "error": str(exc)})
            return None

    @staticmethod
    def _path(kb_id: str, directory: str | None = None) -> str:
        from app.core.config import settings
        base = directory or os.path.join(getattr(settings, "DATA_DIR", "data"), "bm25")
        return os.path.join(base, f"{str(kb_id).replace('-', '')}.json")

    # ------------------------------------------------------------------
    # 编码
    # ------------------------------------------------------------------
    def encode_document(self, text: str) -> dict[int, float]:
        """文档块 → 稀疏向量 {token_id: BM25 权重}。"""
        toks = tokenize_text(text)
        if not toks or not self.vocab:
            return {}
        dl = len(toks)
        tf: dict[str, int] = {}
        for t in toks:
            if t in self.vocab:
                tf[t] = tf.get(t, 0) + 1
        norm = self.avgdl if self.avgdl > 0 else 1.0
        sparse: dict[int, float] = {}
        for t, freq in tf.items():
            idf = self.idf.get(t, 0.0)
            if idf <= 0:
                continue
            denom = freq + self.k1 * (1.0 - self.b + self.b * dl / norm)
            w = idf * (freq * (self.k1 + 1.0)) / denom if denom else 0.0
            if w > 0:
                sparse[self.vocab[t]] = round(w, 6)
        return sparse

    def encode_query(self, text: str) -> dict[int, float]:
        """查询文本 → 稀疏向量 {token_id: 权重}。

        查询权重使用 idf（不乘文档词频），命中即赋予该 token 的区分度。
        """
        toks = tokenize_text(text)
        sparse: dict[int, float] = {}
        seen: set[int] = set()
        for t in toks:
            tid = self.vocab.get(t)
            if tid is None or tid in seen:
                continue
            idf = self.idf.get(t, 0.0)
            if idf > 0:
                sparse[tid] = round(idf, 6)
                seen.add(tid)
        return sparse


# 模块级简单缓存（KB -> 模型），避免重复加载
_model_cache: dict[str, KBBM25] = {}
_cache_lock = threading.Lock()


def get_kb_bm25(kb_id: str) -> KBBM25 | None:
    """获取 KB 的 BM25 模型（命中缓存或从持久化文件加载）。"""
    kb_id = str(kb_id)
    with _cache_lock:
        if kb_id in _model_cache:
            return _model_cache[kb_id]
        m = KBBM25.load(kb_id)
        if m is not None:
            _model_cache[kb_id] = m
        return m


def set_kb_bm25(kb_id: str, model: KBBM25) -> None:
    """写入缓存（索引重建后更新）。"""
    with _cache_lock:
        _model_cache[str(kb_id)] = model


def ensure_kb_bm25(kb_id: str, corpus: list[str] | None = None) -> KBBM25:
    """确保 KB 的 BM25 模型存在。

    模型已存在（缓存或持久化文件）时直接返回；否则用传入语料拟合生成并持久化。
    由重建/入库流程在向量入库前显式调用，保证稀疏向量可编码。

    Args:
        kb_id: 知识库 ID。
        corpus: 模型缺失时用于拟合的语料（每个文档块文本）。

    Returns:
        就绪的 KBBM25 模型。

    Raises:
        ValueError: 模型缺失且未提供语料时。
    """
    kb_id = str(kb_id)
    existing = get_kb_bm25(kb_id)
    if existing is not None:
        return existing
    if not corpus:
        raise ValueError(
            f"KB {kb_id} 的 BM25 模型不存在，且未提供语料，无法生成模型"
        )
    model = KBBM25(kb_id).fit(corpus)
    model.save()
    set_kb_bm25(kb_id, model)
    logger.info("生成并持久化 KB BM25 模型", extra={"kb_id": kb_id, "n_docs": len(corpus)})
    return model
