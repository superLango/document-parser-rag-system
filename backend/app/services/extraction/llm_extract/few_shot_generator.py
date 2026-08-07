"""Few-shot 示例生成器（LangExtract 线路用）。

从 Schema 模板字段的 ``example`` 自动生成 few-shot 示例，
帮助 LLM 理解抽取目标。配置驱动下直接基于字段定义生成。

策略：字段示例生成（配置驱动）
- 从 ``target.fields`` 收集各字段的 ``example``（支持标量 / 列表）
- 示例文本仅由「类别名 + 字段名 示例值」拼接，不依赖写死的牌号占位
  （材料牌号等字段本身配置了 example，自然出现在示例中）
- 轮转窗口生成至多 ``max_examples`` 条示例（覆盖不同字段组合）
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


class FewShotGenerator:
    """Few-shot 示例生成器。

    从 Schema 模板字段的 ``example`` 自动生成 LangExtract 格式的 few-shot 示例。
    """

    def generate(
        self,
        target: ExtractionTarget,
        max_examples: int = 3,
    ) -> list[Any]:
        """从 Schema 模板字段的 ``example`` 自动生成 few-shot 示例。

        Args:
            target: 抽取目标（含 fields，字段需配置 example）。
            max_examples: 最大示例数，默认 3。

        Returns:
            list: ExampleData 对象列表（langextract.core.data.ExampleData）。
        """
        try:
            from langextract.core.data import ExampleData, Extraction
        except ImportError:
            logger.warning("langextract 未安装，无法生成 few-shot 示例")
            return []

        # 收集字段示例（支持标量 / 列表，全部展开为 (字段名, 示例值)）
        field_examples: list[tuple[str, str]] = []
        for f in target.fields or []:
            name = f.get("name", "")
            if not name:
                continue
            ex = f.get("example")
            if ex is None:
                continue
            if isinstance(ex, list):
                for v in ex:
                    if v is not None and str(v).strip():
                        field_examples.append((name, str(v)))
            elif str(ex).strip():
                field_examples.append((name, str(ex)))

        if not field_examples:
            logger.warning(
                "类别字段未配置 example，无法生成 few-shot 示例",
                extra={"feature": target.feature},
            )
            return []

        # 轮转窗口生成示例，覆盖不同字段组合
        examples: list[ExampleData] = []
        window = min(max_examples, len(field_examples))
        for i in range(window):
            attrs: dict[str, str] = {}
            for name, value in field_examples[i : i + window]:
                attrs.setdefault(name, value)

            parts = [target.feature]
            for name, value in attrs.items():
                parts.append(f"{name} {value}")
            sample_text = "，".join(parts)

            extraction = Extraction(
                extraction_class=target.feature,
                attributes=dict(attrs),
            )
            examples.append(ExampleData(text=sample_text, extractions=[extraction]))

        logger.info(
            "few-shot 示例生成完成",
            extra={
                "feature": target.feature,
                "example_count": len(examples),
                "field_examples": len(field_examples),
            },
        )
        return examples


# 模块级单例
few_shot_generator = FewShotGenerator()