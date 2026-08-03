"""Output Schema 构建器（LangExtract 线路 XGrammar 强约束）。

将 ``ExtractionTarget.schema`` 转换为 LangExtract 的 ``output_schema`` 格式，
启用 vLLM 的 XGrammar 结构化输出约束，保证 JSON 格式合规。

output_schema 格式（LangExtract 兼容）::

    {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "材料牌号": {"type": "string"},
                "项目名称": {"type": "string", "enum": ["C", "Si", ...]},
                ...
            }
        }
    }

使用示例::

    from app.services.extraction.llm_extract.output_schema_builder import output_schema_builder

    schema = output_schema_builder.build(target)
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_models import ExtractionTarget

logger = get_logger(__name__)


class OutputSchemaBuilder:
    """Output Schema 构建器。

    将 ExtractionTarget.schema 转换为 LangExtract output_schema 格式。
    """

    def build(
        self,
        target: ExtractionTarget,
    ) -> dict[str, Any] | None:
        """构建 LangExtract output_schema。

        Args:
            target: 抽取目标（含 schema 定义）。

        Returns:
            dict | None: output_schema 字典，target 无 schema 时返回 None。
        """
        if not target.schema:
            logger.debug("target 无 schema，跳过 output_schema 构建", extra={"feature": target.feature})
            return None

        result_def = target.schema.get("result", {})
        result_type = result_def.get("type", "array")
        properties = result_def.get("properties", {})

        # 转换 properties 为 JSON Schema 格式
        json_properties: dict[str, dict[str, Any]] = {}
        field_names: list[str] = []
        for field_name, field_def in properties.items():
            prop: dict[str, Any] = {"type": field_def.get("type", "string")}
            if "enum" in field_def and field_def["enum"]:
                prop["enum"] = field_def["enum"]
            if "description" in field_def:
                prop["description"] = field_def["description"]
            json_properties[field_name] = prop
            field_names.append(field_name)

        # LangExtract 的数据模型：每条记录是一个 Extraction，extraction_class
        # 为类别名（feature），attributes 为各字段值。用 extraction_item_schema
        # 构建 item schema（extraction_class=feature，attributes=字段定义），
        # 再用 extractions_schema 包装成 envelope（顶层 object + extractions array）。
        # 这样 LangExtract 抽取多条记录，每条 extraction_class=feature，
        # attributes 含 材料牌号/项目名称/标准要求/... 各字段。
        from langextract.schema import extractions_schema, extraction_item_schema

        item_schema = extraction_item_schema(
            extraction_class=target.feature,
            attributes=json_properties,
            additional_properties=False,
        )
        output_schema = extractions_schema(item_schema)

        logger.debug(
            "output_schema 构建完成",
            extra={
                "feature": target.feature,
                "result_type": result_type,
                "field_count": len(json_properties),
            },
        )
        return output_schema

    def build_doc_info_schema(self, doc_info_schema: dict[str, Any]) -> dict[str, Any]:
        """构建基础信息 output_schema（object 类型）。

        Args:
            doc_info_schema: schema_builder 构建的基础信息 schema。

        Returns:
            dict: output_schema 字典。
        """
        result_def = doc_info_schema.get("result", {})
        properties = result_def.get("properties", {})

        json_properties: dict[str, dict[str, Any]] = {}
        for field_name, field_def in properties.items():
            prop: dict[str, Any] = {"type": field_def.get("type", "string")}
            if "description" in field_def:
                prop["description"] = field_def["description"]
            json_properties[field_name] = prop

        return {
            "type": "object",
            "properties": json_properties,
        }


# 模块级单例
output_schema_builder = OutputSchemaBuilder()
