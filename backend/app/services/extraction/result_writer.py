"""v3 抽取结果保存器。

将 ``ExtractionResult`` 序列化为 JSON 文件，保存到任务目录下。
路径规则：``{OCR_OUTPUT_DIR}/{task_id}/extract_result.json``

设计要点：
- 每次覆盖写（不缓存，保证时效性）
- 输出格式包含 categories / summary / timing
- 自动创建任务目录（如不存在）
- 使用 UTF-8 编码，ensure_ascii=False 保留中文
- 紧凑 JSON 输出（separators=(",", ":")，无多余空格和换行）

使用示例::

    from app.services.extraction.result_writer import result_writer

    await result_writer.save(task_id, extraction_result)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.services.extraction.extraction_models import (
    CategoryResult,
    ExtractionResult,
    SkippedFeature,
)

logger = get_logger(__name__)

# 结果文件名
_RESULT_FILENAME = "extract_result.json"


class ResultWriter:
    """v3 抽取结果保存器。

    将 ``ExtractionResult`` 写入 ``{OCR_OUTPUT_DIR}/{task_id}/extract_result.json``。
    """

    def get_result_path(self, task_id: str) -> Path:
        """获取任务结果文件路径。

        Args:
            task_id: 任务 ID（雪花 ID）。

        Returns:
            Path: 结果文件绝对路径。
        """
        task_dir = Path(settings.OCR_OUTPUT_DIR) / task_id
        return task_dir / _RESULT_FILENAME

    async def save(
        self,
        task_id: str,
        result: ExtractionResult,
        skipped_features: list[SkippedFeature] | None = None,
    ) -> Path:
        """保存抽取结果到任务目录（覆盖写）。

        Args:
            task_id: 任务 ID。
            result: v3 抽取最终结果。
            skipped_features: 被剔除的 feature 列表（Phase 2 过滤的）。

        Returns:
            Path: 结果文件路径。
        """
        result_path = self.get_result_path(task_id)
        result_path.parent.mkdir(parents=True, exist_ok=True)

        # 填充 summary（总数、活跃/剔除 feature）
        total_records = sum(len(c.records) for c in result.categories)
        total_rejected = sum(len(c.rejected) for c in result.categories)
        active_features = [c.feature for c in result.categories if c.records]
        result.summary = {
            "total_records": total_records,
            "total_rejected": total_rejected,
            "active_features": active_features,
            "skipped_features": [
                {
                    "feature": s.feature,
                    "reason": s.reason,
                    "confidence": s.confidence,
                }
                for s in (skipped_features or [])
            ],
        }

        # 序列化为紧凑 JSON（无多余空格和换行，减小文件体积）
        output = result.to_dict()
        result_path.write_text(
            json.dumps(output, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

        logger.info(
            "v3 抽取结果已保存",
            extra={
                "task_id": task_id,
                "path": str(result_path),
                "total_records": result.summary.get("total_records", 0),
                "total_rejected": result.summary.get("total_rejected", 0),
            },
        )
        return result_path


# 模块级单例
result_writer = ResultWriter()
