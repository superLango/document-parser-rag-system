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
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import SkippedFeature

logger = get_logger(__name__)


class FeatureFilter:
    """Feature 置信度过滤器。

    根据 hybrid_search 的 max score 判断文档是否包含该 feature 的数据。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

    def filter(
        self,
        feature_hits: dict[str, list[dict[str, Any]]],
        threshold: float | None = None,
    ) -> tuple[list[str], list[SkippedFeature]]:
        """过滤 feature，返回保留和剔除的列表。

        Args:
            feature_hits: feature 名 → hybrid_search 返回的 hits 列表。
            threshold: 置信度阈值，None 时使用配置项。

        Returns:
            tuple: (kept_features, skipped_features)
                - kept_features: 保留的 feature 名列表（按置信度降序）
                - skipped_features: 被剔除的 SkippedFeature 列表
        """
        thresh = threshold if threshold is not None else self._settings.category_confidence_threshold

        kept: list[tuple[str, float]] = []  # (feature, confidence)
        skipped: list[SkippedFeature] = []

        for feature, hits in feature_hits.items():
            if not hits:
                skipped.append(SkippedFeature(
                    feature=feature,
                    reason="无召回",
                    confidence=0.0,
                ))
                logger.debug(
                    "feature 剔除：无召回",
                    extra={"feature": feature},
                )
                continue

            # 置信度 = max(hits.score)
            confidence = max(h.get("score", 0.0) for h in hits)
            if confidence < thresh:
                skipped.append(SkippedFeature(
                    feature=feature,
                    reason=f"置信度过低（{confidence:.4f} < {thresh}）",
                    confidence=confidence,
                ))
                logger.debug(
                    "feature 剔除：置信度过低",
                    extra={"feature": feature, "confidence": confidence, "threshold": thresh},
                )
            else:
                kept.append((feature, confidence))
                logger.debug(
                    "feature 保留",
                    extra={"feature": feature, "confidence": confidence},
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
