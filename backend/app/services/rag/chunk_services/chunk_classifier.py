"""召回分块零样本分类服务。

基于 gliclass-multilang-mini 模型，对召回阶段检索到的文本分块进行
类别归属判断，过滤掉不属于当前抽取类别的分块，减少跨类混入。

设计要点：
- 单例模式确保模型只加载一次，与 embedding_service 同模式
- 懒加载：首次调用时加载模型，避免启动时占显存
- asyncio.to_thread 包装同步推理，不阻塞事件循环
- 超长 chunk 截断：mdeberta-v3 max_position_embeddings=512，
  取前 256 + 后 256 字符保留表格表头与尾部上下文
- 候选标签使用中文描述，提升零样本准确率
- 失败降级：分类异常时返回空列表（调用方降级为无过滤）
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("chunk_classifier")

# 候选类别标签 → 中文描述映射
# 使用描述性标签提升零样本分类准确率
_CATEGORY_LABELS: dict[str, str] = {
    "化学成分": "化学成分：材料中各元素的质量分数或含量，如碳C、硅Si、锰Mn、磷P、硫S等",
    "室温拉伸性能": "室温拉伸：材料在室温下的力学性能，如抗拉强度、屈服强度、伸长率、断面收缩率",
    "高温拉伸": "高温拉伸：材料在高温下的拉伸性能，如高温抗拉强度、高温屈服强度",
    "冲击性能": "冲击性能：材料的冲击韧性试验结果，如夏比冲击功、冲击吸收能量",
    "硬度性能": "硬度：材料的硬度测试结果，如布氏硬度HBW、洛氏硬度HRC、维氏硬度HV",
    "布氏硬度": "布氏硬度：使用钢球或硬质合金球压入测量的硬度值HBW",
    "洛氏硬度": "洛氏硬度：使用金刚石圆锥或钢球压入测量的硬度值HRC/HRA/HRB",
    "维氏硬度": "维氏硬度：使用金刚石四棱锥压入测量的硬度值HV",
    "组合持久": "组合持久：材料在高温下的持久强度试验结果，如持久断裂时间、持久伸长率",
    "高温光滑持久": "高温光滑持久：光滑试样在高温下的持久强度试验",
    "气体分析": "气体分析：材料中气体元素含量分析，如氮N、氢H、氧O含量",
}


class ChunkClassifierService:
    """基于 gliclass 的零样本文本分类服务。

    用于召回阶段对检索到的文本分块进行类别判断，
    过滤掉不属于当前抽取类别的分块。
    """

    _instance: ChunkClassifierService | None = None
    _pipe: Any = None
    _load_lock: asyncio.Lock | None = None

    def __new__(cls) -> ChunkClassifierService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._load_lock = asyncio.Lock()

    def _load_model(self) -> None:
        """加载 gliclass 模型和 pipeline。"""
        from gliclass import GLiClassModel, ZeroShotClassificationPipeline
        from transformers import AutoTokenizer

        model_path = settings.GLICLASS_MODEL_PATH
        logger.info("加载 gliclass 模型", model_path=model_path)

        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = GLiClassModel.from_pretrained(model_path)

        self._pipe = ZeroShotClassificationPipeline(
            model=model,
            tokenizer=tokenizer,
            max_classes=25,
            max_length=settings.GLICLASS_MAX_LENGTH,
            classification_type="multi-label",
            device="cuda:0",
            progress_bar=False,
        )
        logger.info("gliclass 模型加载完成")

    def _ensure_model(self) -> None:
        """懒加载：首次调用时加载模型。"""
        if self._pipe is None:
            self._load_model()

    @staticmethod
    def _truncate_text(text: str, max_chars: int = 512) -> str:
        """截断超长文本，保留头部与尾部。

        mdeberta-v3 max_position_embeddings=512 tokens，
        中文约 1.5 字符/token，512 tokens ≈ 768 字符。
        取前 384 + 后 384 字符，保留表格表头与尾部上下文。

        Args:
            text: 原始文本。
            max_chars: 最大字符数。

        Returns:
            str: 截断后的文本。
        """
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return text[:half] + "\n...\n" + text[-half:]

    def _classify_sync(
        self,
        texts: list[str],
        labels: list[str],
        threshold: float,
        batch_size: int,
    ) -> list[list[dict]]:
        """同步执行分类推理。"""
        self._ensure_model()
        # 截断超长文本
        truncated_texts = [self._truncate_text(t) for t in texts]
        # 调用 pipeline
        results = self._pipe(
            texts=truncated_texts,
            labels=labels,
            threshold=threshold,
            batch_size=batch_size,
        )
        # 标准化输出格式：[{label, score}, ...]
        normalized: list[list[dict]] = []
        for text_result in results:
            normalized.append(
                [
                    {"label": r["label"], "score": float(r["score"])}
                    for r in text_result
                ]
            )
        return normalized

    async def classify_chunks(
        self,
        chunks: list[dict],
        candidate_categories: list[str],
        threshold: float | None = None,
    ) -> list[list[dict]]:
        """对召回分块进行零样本分类。

        Args:
            chunks: 召回分块列表，每个分块需包含 "text" 字段。
            candidate_categories: 候选类别名列表（如 ["化学成分", "室温拉伸性能"]）。
            threshold: 置信度阈值，None 时使用配置默认值。

        Returns:
            list[list[dict]]: 每个分块的分类结果，
                每个结果为 [{"label": "化学成分", "score": 0.94}, ...]。
            分类失败时返回空列表。
        """
        if not chunks or not candidate_categories:
            return [[] for _ in chunks]

        # 构建候选标签（使用描述性标签提升准确率）
        labels = [
            _CATEGORY_LABELS.get(cat, cat)
            for cat in candidate_categories
        ]

        # 提取文本
        texts = [c.get("text", "") for c in chunks]
        if not any(texts):
            return [[] for _ in chunks]

        thresh = threshold or settings.EXTRACTION_RECALL_CLASSIFY_THRESHOLD
        batch_size = settings.GLICLASS_BATCH_SIZE

        try:
            # 串行化模型加载 + 推理，避免 torch 多线程并发问题
            async with self._load_lock:  # type: ignore[union-attr]
                results = await asyncio.to_thread(
                    self._classify_sync,
                    texts,
                    labels,
                    thresh,
                    batch_size,
                )
            return results
        except Exception as err:
            logger.warning(
                "gliclass 分类推理失败，返回空结果",
                error=str(err),
                chunk_count=len(chunks),
                labels=labels,
            )
            return [[] for _ in chunks]

    async def classify_single(
        self,
        text: str,
        candidate_categories: list[str],
        threshold: float | None = None,
    ) -> list[dict]:
        """对单个文本进行分类。

        Args:
            text: 待分类文本。
            candidate_categories: 候选类别名列表。
            threshold: 置信度阈值。

        Returns:
            list[dict]: 分类结果 [{"label": ..., "score": ...}, ...]
        """
        results = await self.classify_chunks(
            [{"text": text}],
            candidate_categories,
            threshold,
        )
        return results[0] if results else []

    def warmup(self) -> None:
        """预热模型（在 worker 启动时调用）。"""
        self._ensure_model()
        logger.info("gliclass 模型预热完成")


# 模块级单例
chunk_classifier_service = ChunkClassifierService()
