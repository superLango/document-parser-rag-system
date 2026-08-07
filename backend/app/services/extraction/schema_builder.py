"""类别 Schema 构建（Phase 2 输出，Phase 4 输入）。

构建类别列表的 schema 定义，供 Phase 4 LLM 抽取使用。

schema 结构::

    {
        "feature": "化学成分",
        "result": {
            "type": "array",
            "properties": {
                "材料牌号": {"type": "string", "description": "..."},
                "项目名称": {"type": "string", "enum": ["C", "Si", ...]},
                ...
            }
        }
    }

使用示例::

    from app.services.extraction.schema_builder import schema_builder

    category_schemas = schema_builder.build_category_schemas(targets)
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_models import ExtractionTarget

logger = get_logger(__name__)


class SchemaBuilder:
    """类别 Schema 构建器。

    根据保留的 ExtractionTarget（含 fields/query_terms）构建类别 schema 定义，
    供 Phase 4 抽取器使用（glmocr 线路构建 prompt，langextract 线路构建 output_schema）。
    """

    def build_category_schemas(
        self,
        targets: list[ExtractionTarget],
    ) -> dict[str, dict[str, Any]]:
        """构建类别列表 schema（每个 target 一组，配置字段驱动）。

        schema 的字段定义（属性、枚举可选值）直接来自 ``target.fields``
        （Schema 模板字段 + 术语绑定可选值），不再依赖内置 ``CATEGORY_FIELDS``。

        Args:
            targets: 保留的 ExtractionTarget 列表（含 fields/query_terms）。

        Returns:
            dict: feature 名 → schema 定义，每个 schema 的 result.type="array"。
        """
        schemas: dict[str, dict[str, Any]] = {}
        for target in targets:
            schema = self._build_single_category_schema(target)
            schemas[target.feature] = schema
            target.schema = schema  # 回填到 target

        logger.info(
            "类别 schema 构建完成",
            extra={"feature_count": len(schemas), "features": list(schemas.keys())},
        )
        return schemas

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_single_category_schema(
        self,
        target: ExtractionTarget,
    ) -> dict[str, Any]:
        """构建单个类别的 schema（配置字段驱动）。

        Args:
            target: 该 feature 的 ExtractionTarget（含 fields/query_terms）。

        Returns:
            dict: schema 定义。
        """
        properties: dict[str, dict[str, Any]] = {}
        for field_def in target.fields or []:
            name = field_def.get("name", "")
            if not name:
                continue
            prop: dict[str, Any] = {
                "type": field_def.get("type", "string"),
                "description": field_def.get("description") or name,
            }
            if field_def.get("required"):
                prop["required"] = True
            # enum 可选值：来自术语绑定/数据集解析
            values = field_def.get("values") or []
            if values:
                prop["enum"] = values
            properties[name] = prop

        return {
            "feature": target.feature,
            "result": {
                "type": target.return_type or "array",
                "properties": properties,
            },
            # 附加元数据（供后处理使用）：可选值白名单
            "metadata": {
                "item_names": target.item_names,
                "confidence": target.confidence,
            },
        }


# 模块级单例
schema_builder = SchemaBuilder()
