"""Schema 配置 Schema 模块。

定义文档结构化抽取的 Schema 配置模型。
Schema 用于指导 LLM 将文档解析为指定结构的 JSON。

命名约定：SchemaConfigBase / SchemaConfigCreate / SchemaConfigUpdate / SchemaConfigResponse。
文件名为 schema_model.py 以避免与 schemas 包命名冲突。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SchemaConfigBase(BaseModel):
    """Schema 配置基础属性。

    Attributes:
        name: Schema 名称。
        description: Schema 描述，可为空。
    """

    name: str
    description: str | None = None


class SchemaConfigCreate(SchemaConfigBase):
    """Schema 配置创建参数。

    扩展 SchemaConfigBase，增加 schema_definition 字段。

    Attributes:
        schema_definition: Schema 定义（JSON Schema 结构）。
    """

    schema_definition: dict


class SchemaConfigUpdate(BaseModel):
    """Schema 配置更新参数。

    所有字段可选，用于部分更新。

    Attributes:
        name: Schema 名称。
        description: Schema 描述。
        schema_definition: Schema 定义。
    """

    name: str | None = None
    description: str | None = None
    schema_definition: dict | None = None


class SchemaConfigResponse(SchemaConfigBase):
    """Schema 配置响应模型。

    扩展 SchemaConfigBase，增加数据库生成的字段。
    通过 from_attributes=True 支持从 ORM 模型实例转换。

    Attributes:
        id: Schema 配置唯一标识。
        schema_definition: Schema 定义（JSON Schema 结构）。
        is_template: 是否为模板。
        created_at: 创建时间。
        updated_at: 更新时间，可为空。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    schema_definition: dict
    is_template: bool
    created_at: datetime
    updated_at: datetime | None = None
