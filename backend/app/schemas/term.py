"""术语 Schema 模块。

定义术语标准化库的请求与响应模型。
术语库用于将文档中的非标准术语映射到标准术语。

命名约定：TermBase / TermCreate / TermUpdate / TermResponse。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TermBase(BaseModel):
    """术语基础属性。

    Attributes:
        term_name: 原始术语名称。
        standard_name: 标准术语名称，可为空。
        definition: 术语定义，可为空。
    """

    term_name: str
    standard_name: str | None = None
    definition: str | None = None


class TermCreate(TermBase):
    """术语创建参数。

    扩展 TermBase，增加同义词列表。

    Attributes:
        synonyms: 同义词列表，可为空。
    """

    synonyms: list[str] | None = None


class TermUpdate(BaseModel):
    """术语更新参数。

    所有字段可选，用于部分更新。

    Attributes:
        term_name: 原始术语名称。
        standard_name: 标准术语名称。
        definition: 术语定义。
        synonyms: 同义词列表。
        status: 术语状态。
    """

    term_name: str | None = None
    standard_name: str | None = None
    definition: str | None = None
    synonyms: list[str] | None = None
    status: str | None = None


class TermResponse(TermBase):
    """术语响应模型。

    扩展 TermBase，增加数据库生成的字段。
    通过 from_attributes=True 支持从 ORM 模型实例转换。

    Attributes:
        id: 术语唯一标识。
        synonyms: 同义词列表，可为空。
        status: 术语状态。
        created_at: 创建时间。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    synonyms: list[str] | None = None
    status: str
    created_at: datetime
