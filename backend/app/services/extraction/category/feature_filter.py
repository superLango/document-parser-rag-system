"""Feature 置信度过滤器（Phase 2）。

根据 hybrid_search 返回的检索结果，过滤掉置信度过低或无召回的 feature。

过滤规则：
- 无召回结果 → 剔除（reason="无召回"）
- max(hits.score) < 阈值 → 剔除（reason="置信度过低"）
- max(hits.score) ≥ 阈值 → 保留，置信度 = max(hits.score)

使用示例::

    from app.services.extraction.category.feature_filter import feature_filter

    kept, skipped = feature_filter.filter(
        feature_hits={"化学成分": hits1, "室温拉伸": hits2, ...}
    )
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import get_logger
from app.core.exceptions import BusinessException
from app.services.extraction.extraction_models import SkippedFeature

logger = get_logger(__name__)


class FeatureFilter:
    """Feature 置信度过滤器。

    根据 hybrid_search 的 max score 判断文档是否包含该 feature 的数据。
    """

    def __init__(self) -> None:
        pass

    def filter(
        self,
        feature_hits: dict[str, list[dict[str, Any]]],
        threshold: float | None = None,
        sparse_hits: dict[str, list[dict[str, Any]]] | None = None,
        keyword_min_hits: int = 1,
    ) -> tuple[list[str], list[SkippedFeature]]:
        """过滤 feature，返回保留和剔除的列表。

        Args:
            feature_hits: feature 名 → 稠密 hybrid_search 返回的 hits 列表。
            threshold: 稠密置信度阈值，None 时使用配置项。
            sparse_hits: feature 名 → 稀疏（BM25 词法）检索命中的 hits 列表。
                仅当混合检索开启时传入；为 None 表示不做稀疏兜底。
            keyword_min_hits: 稀疏兜底保留所需的词法命中数下限（默认 1 即
                文档内词条字面命中即保留，用于恢复化学成分等强词法类别）。

        Returns:
            tuple: (kept_features, skipped_features)
                - kept_features: 保留的 feature 名列表（按置信度降序）
                - skipped_features: 被剔除的 SkippedFeature 列表
        """
        # 阈值由调用方从配置解析传入（类别级→全局 default_confidence_threshold），
        # 缺失即报错，不允许 settings/env 兜底
        if threshold is None:
            raise BusinessException("未配置类别置信度阈值（retrieval.default_confidence_threshold）")
        thresh = threshold

        kept: list[tuple[str, float]] = []  # (feature, confidence)
        skipped: list[SkippedFeature] = []

        for feature, hits in feature_hits.items():
            if not hits:
                dense_conf = 0.0
            else:
                # 置信度 = max(hits.score)
                dense_conf = max(h.get("score", 0.0) for h in hits)

            if dense_conf < thresh:
                # 稠密分未达阈值 → 尝试稀疏词法兜底：类别 query 词条在文档内
                # 字面命中（强词法信号）即视为存在该类别（如化学成分元素符号）。
                sparse_kept = False
                if sparse_hits is not None:
                    sparse = sparse_hits.get(feature) or []
                    if len(sparse) >= max(keyword_min_hits, 1):
                        sparse_conf = max(h.get("score", 0.0) for h in sparse)
                        confidence = max(dense_conf, sparse_conf)
                        kept.append((feature, confidence))
                        sparse_kept = True
                        logger.debug(
                            "feature 保留：稀疏词法命中兜底",
                            extra={
                                "feature": feature,
                                "dense_conf": round(dense_conf, 4),
                                "sparse_hits": len(sparse),
                                "keyword_min_hits": keyword_min_hits,
                            },
                        )
                if not sparse_kept:
                    skipped.append(SkippedFeature(
                        feature=feature,
                        reason=f"置信度过低（{dense_conf:.4f} < {thresh}）",
                        confidence=dense_conf,
                    ))
                    logger.debug(
                        "feature 剔除：置信度过低",
                        extra={"feature": feature, "confidence": dense_conf, "threshold": thresh},
                    )
            else:
                kept.append((feature, dense_conf))
                logger.debug(
                    "feature 保留",
                    extra={"feature": feature, "confidence": dense_conf},
                )

        # 按置信度降序排列
        kept.sort(key=lambda x: x[1], reverse=True)
        kept_features = [f for f, _ in kept]

        # 返回保留的置信度映射（供 category_builder 使用）
        self._last_confidences: dict[str, float] = {f: c for f, c in kept}

        logger.info(
            "feature 过滤完成",
            extra={
                "total": len(feature_hits),
                "kept": len(kept_features),
                "skipped": len(skipped),
                "threshold": thresh,
            },
        )
        return kept_features, skipped

    def get_confidence(self, feature: str) -> float:
        """获取最近一次过滤中保留 feature 的置信度。

        Args:
            feature: feature 名。

        Returns:
            float: 置信度（未找到返回 0.0）。
        """
        return getattr(self, "_last_confidences", {}).get(feature, 0.0)


# 模块级单例
feature_filter = FeatureFilter()
