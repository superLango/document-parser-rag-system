"""三类 Schema 构建（Phase 2 输出，Phase 4 输入）。

构建三部分 schema 定义，供 Phase 4 LLM 抽取使用：

1. **标准基本信息**（single=True，返回单条 dict）
   - 标准名称、标准编号

2. **类别列表**（每个保留的 feature 一组，返回 list[dict]）
   - 材料牌号、项目名称、单位、标准要求、试验方法、位置、方向、
     尺寸厚度、试样状态、取样数量、取样说明、锻件类型
   - 项目名称 enum = 该 feature 的 sm_item.NAME 列表
   - 试验方法 enum = 该 feature 的 sm_method.NAME 列表

3. **热处理制度**（返回 list[dict]）
   - 材料牌号、项目大类、工艺名称、工序名称、装炉温度、升温速率、
     保温温度、保温时间、降温速率、出炉温度、冷却介质、介质温度

schema 结构::

    {
        "feature": "化学成分",
        "prompt": "请从文档中抽取化学成分...",
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

    doc_info_schema = schema_builder.build_doc_info_schema()
    category_schemas = schema_builder.build_category_schemas(targets)
    heat_treatment_schema = schema_builder.build_heat_treatment_schema(features)
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_models import ExtractionTarget

logger = get_logger(__name__)

# 类别列表字段定义（第二部分，所有 feature 共用）
CATEGORY_FIELDS: list[dict[str, Any]] = [
    {"name": "材料牌号", "type": "string", "required": True},
    {"name": "项目名称", "type": "string", "enum_source": "items", "required": True},
    {"name": "单位", "type": "string"},
    {"name": "标准要求", "type": "string", "required": True},
    {"name": "试验方法", "type": "string", "enum_source": "methods"},
    {"name": "试验温度", "type": "string"},
    {"name": "位置", "type": "string"},
    {"name": "方向", "type": "string"},
    {"name": "尺寸厚度", "type": "string"},
    {"name": "试样状态", "type": "string"},
    {"name": "取样数量", "type": "string"},
    {"name": "取样说明", "type": "string"},
    {"name": "锻件类型", "type": "string"},
]

# 热处理制度字段定义（第三部分）
HEAT_TREATMENT_FIELDS: list[dict[str, Any]] = [
    {"name": "材料牌号", "type": "string", "required": True},
    {"name": "项目大类", "type": "string", "enum_source": "features", "required": True},
    {"name": "工艺名称", "type": "string"},
    {"name": "工序名称", "type": "string"},
    {"name": "装炉温度", "type": "string"},
    {"name": "升温速率", "type": "string"},
    {"name": "保温温度", "type": "string"},
    {"name": "保温时间", "type": "string"},
    {"name": "降温速率", "type": "string"},
    {"name": "出炉温度", "type": "string"},
    {"name": "冷却介质", "type": "string"},
    {"name": "介质温度", "type": "string"},
]


class SchemaBuilder:
    """三类 Schema 构建器。

    根据 active features 及其 items/methods 构建 schema 定义，
    供 Phase 4 抽取器使用（glmocr 线路构建 prompt，langextract 线路构建 output_schema）。
    """

    def build_doc_info_schema(self) -> dict[str, Any]:
        """构建标准基本信息 schema（第一部分）。

        Returns:
            dict: schema 定义，result.type="object"（返回单条 dict）。
        """
        return {
            "feature": "标准基本信息",
            "prompt": "请从文档内容中抽取标准的基本信息（标准名称、标准编号）。",
            "result": {
                "type": "object",
                "properties": {
                    "标准名称": {
                        "type": "string",
                        "description": "标准的完整名称",
                    },
                    "标准编号": {
                        "type": "string",
                        "description": "标准编号，如 GB/T 1220-2007",
                    },
                },
            },
        }

    def build_category_schemas(
        self,
        targets: list[ExtractionTarget],
    ) -> dict[str, dict[str, Any]]:
        """构建类别列表 schema（第二部分，每个 feature 一组）。

        Args:
            targets: 保留的 ExtractionTarget 列表（含 items 和 methods）。

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

    def build_heat_treatment_schema(
        self,
        features: list[str],
    ) -> dict[str, Any]:
        """构建热处理制度 schema（第三部分）。

        Args:
            features: 全部 feature 名列表（用于"项目大类"字段 enum 约束）。

        Returns:
            dict: schema 定义，result.type="array"。
        """
        properties: dict[str, dict[str, Any]] = {}
        for field_def in HEAT_TREATMENT_FIELDS:
            prop: dict[str, Any] = {
                "type": field_def["type"],
                "description": self._get_field_description(field_def["name"]),
            }
            if field_def.get("enum_source") == "features":
                prop["enum"] = features
            properties[field_def["name"]] = prop

        return {
            "feature": "热处理制度",
            "prompt": "请从文档内容中抽取热处理制度数据，项目大类必须从提供的列表中选取。",
            "result": {
                "type": "array",
                "properties": properties,
            },
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_single_category_schema(
        self,
        target: ExtractionTarget,
    ) -> dict[str, Any]:
        """构建单个 feature 的类别 schema。

        Args:
            target: 该 feature 的 ExtractionTarget（含 items 和 methods）。

        Returns:
            dict: schema 定义。
        """
        properties: dict[str, dict[str, Any]] = {}
        for field_def in CATEGORY_FIELDS:
            prop: dict[str, Any] = {
                "type": field_def["type"],
                "description": self._resolve_field_description(field_def["name"], target),
            }
            # enum 约束：项目名称从 items 取，试验方法从 method_codes（标准编号）取
            if field_def.get("enum_source") == "items" and target.item_names:
                prop["enum"] = target.item_names
            elif field_def.get("enum_source") == "methods":
                # 试验方法用标准编号（method_codes），fallback 到方法名称
                method_enum = target.method_codes or target.method_names
                if method_enum:
                    prop["enum"] = method_enum

            properties[field_def["name"]] = prop

        return {
            "feature": target.feature,
            "prompt": f"请从文档内容中抽取{target.feature}相关的检测数据记录。"
            f"项目名称必须从提供的项目列表中匹配，试验方法必须从提供的方法列表中匹配。",
            "result": {
                "type": "array",
                "properties": properties,
            },
            # 附加元数据（供后处理使用）
            "metadata": {
                "item_names": target.item_names,
                "method_names": target.method_names,
                "method_codes": target.method_codes,
                "confidence": target.confidence,
            },
        }

    @staticmethod
    def _get_field_description(field_name: str) -> str:
        """获取字段描述（从 field_descriptions.yaml 加载，与 glmocr 线路统一）。

        替代原先的硬编码描述字典，确保 LangExtract（output_schema.description）
        与 glmocr（prompt field_defs）字段描述来源一致。

        Args:
            field_name: 字段名。

        Returns:
            str: 字段描述文本（未替换占位符，含 {feature} 等原样保留）。
        """
        from app.services.extraction.prompts.prompt_manager import prompt_manager

        desc_def = prompt_manager.get_field_description(field_name)
        return desc_def.get("description", field_name)

    @staticmethod
    def _resolve_field_description(
        field_name: str,
        target: ExtractionTarget,
    ) -> str:
        """获取字段描述并替换占位符（feature/items/method_codes）。

        用于类别 schema 构建（有 target 上下文），将 field_descriptions.yaml
        中的 {feature}/{items前20个}/{method_codes} 占位符替换为实际值，
        使 output_schema 的 description 字段语义完整。

        Args:
            field_name: 字段名。
            target: 抽取目标（提供 feature/items/methods 上下文）。

        Returns:
            str: 占位符替换后的字段描述文本。
        """
        from app.services.extraction.prompts.prompt_manager import prompt_manager

        desc_def = prompt_manager.get_field_description(field_name)
        desc = desc_def.get("description", field_name)

        # 替换占位符（与 prompt_manager.build_field_defs_text 保持一致）
        desc = desc.replace("{feature}", target.feature)
        items_str = "、".join(target.item_names[:20]) if target.item_names else ""
        desc = desc.replace("{items前20个}", items_str)
        methods = target.method_codes or target.method_names
        method_str = "、".join(methods[:10]) if methods else ""
        desc = desc.replace("{method_codes}", method_str)
        return desc


# 模块级单例
schema_builder = SchemaBuilder()
