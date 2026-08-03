"""Few-shot 示例生成器（LangExtract 线路用）。

从基础表 ``ExtractionTarget.items`` 自动生成 few-shot 示例，
帮助 LLM 理解抽取目标。

策略：基础表自动生成 + 人工字段描述
- 从 target.items 取前 3 个 item，合成示例文本和 Extraction 对象
- 示例文本格式："{牌号} {feature}：{item.name} {sample_value}"
- Extraction 对象使用类+属性模式（extraction_class + attributes）

使用示例::

    from app.services.extraction.llm_extract.few_shot_generator import few_shot_generator

    examples = few_shot_generator.generate(target)
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_models import ExtractionTarget

logger = get_logger(__name__)

# 示例牌号（通用占位，实际应从文档抽取）
_SAMPLE_BRAND = "06Cr19Ni10"

# 每个 item 的示例值（按 feature 提供典型值）
_SAMPLE_VALUES: dict[str, str] = {
    "C": "≤0.08",
    "Si": "≤1.00",
    "Mn": "≤2.00",
    "P": "≤0.045",
    "S": "≤0.030",
    "Cr": "18.00-20.00",
    "Ni": "8.00-11.00",
    "Rp0.2": "≥205",
    "Rm": "≥520",
    "A": "≥40",
    "HBW": "≤187",
}


class FewShotGenerator:
    """Few-shot 示例生成器。

    从基础表自动生成 LangExtract 格式的 few-shot 示例。
    """

    def generate(
        self,
        target: ExtractionTarget,
        max_examples: int = 3,
    ) -> list[Any]:
        """从基础表自动生成 few-shot 示例。

        Args:
            target: 抽取目标（含 items）。
            max_examples: 最大示例数，默认 3。

        Returns:
            list: ExampleData 对象列表（langextract.core.data.ExampleData）。
        """
        try:
            from langextract.core.data import ExampleData, Extraction
        except ImportError:
            logger.warning("langextract 未安装，无法生成 few-shot 示例")
            return []

        examples: list[ExampleData] = []
        for item in target.items[:max_examples]:
            if not item.name:
                continue

            # 合成示例文本
            sample_value = _SAMPLE_VALUES.get(item.name, "标准值")
            sample_text = f"{_SAMPLE_BRAND} {target.feature}：{item.name} {sample_value}"

            # 构造 Extraction 对象（类+属性模式）
            extraction = Extraction(
                extraction_class=target.feature,
                extraction_text=_SAMPLE_BRAND,
                attributes={
                    "项目名称": item.name,
                    "单位": item.unit or "",
                    "标准要求": sample_value,
                },
            )
            examples.append(ExampleData(text=sample_text, extractions=[extraction]))

        logger.info(
            "few-shot 示例生成完成",
            extra={
                "feature": target.feature,
                "example_count": len(examples),
            },
        )
        return examples


# 模块级单例
few_shot_generator = FewShotGenerator()
