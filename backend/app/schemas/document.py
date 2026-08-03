"""文档 Schema 模块。

定义文档资源的请求与响应模型，对应 Document ORM 模型。
命名约定：DocumentBase / DocumentCreate / DocumentUpdate / DocumentResponse。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentBase(BaseModel):
    """文档基础属性。

    Attributes:
        filename: 文件名。
        file_size: 文件大小（字节）。
        file_type: 文件类型（如 pdf、docx），可为空。
    """

    filename: str
    file_size: int
    file_type: str | None = None


class DocumentCreate(BaseModel):
    """文档创建参数（内部使用）。

    用于内部创建文档记录，字段与 DocumentBase 一致，
    但独立定义以便未来扩展内部专用字段。

    Attributes:
        filename: 文件名。
        file_size: 文件大小（字节）。
        file_type: 文件类型，可为空。
    """

    filename: str
    file_size: int
    file_type: str | None = None


class DocumentUpdate(BaseModel):
    """文档更新参数。

    所有字段可选，用于部分更新文档状态与解析结果。

    Attributes:
        status: 文档处理状态。
        parsed_text: 解析后的纯文本。
        markdown_content: Popo Markdown 内容。
        extraction_status: 抽取状态。
        index_status: 索引状态。
        graph_status: 图谱状态。
        graph_error: 图谱错误信息。
        structured_data: 结构化抽取结果。
        layout_data: 版面分析结果。
    """

    status: str | None = None
    parsed_text: str | None = None
    markdown_content: str | None = None
    extraction_status: str | None = None
    index_status: str | None = None
    graph_status: str | None = None
    graph_error: str | None = None
    structured_data: dict | None = None
    layout_data: dict | None = None


class DocumentResponse(DocumentBase):
    """文档响应模型。

    扩展 DocumentBase，增加数据库生成的字段。
    通过 from_attributes=True 支持从 ORM 模型实例转换。

    Attributes:
        id: 文档唯一标识。
        status: 文档处理状态。
        parsed_text: 解析后的纯文本，未解析时为 None。
        markdown_content: Popo Markdown 内容。
        extraction_status: 抽取状态（null/completed/failed）。
        index_status: 索引状态（null/indexing/indexed/failed）。
        graph_status: 图谱状态（null/ready/failed）。
        graph_error: 图谱错误信息。
        structured_data: 结构化抽取结果，未解析时为 None。
        layout_data: 版面分析结果（含 merged 区域列表），未解析时为 None。
        created_at: 创建时间。
        updated_at: 更新时间，可为空。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    parsed_text: str | None = None
    markdown_content: str | None = None
    extraction_status: str | None = None
    index_status: str | None = None
    graph_status: str | None = None
    graph_error: str | None = None
    structured_data: dict | None = None
    layout_data: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None


class DocumentListResponse(BaseModel):
    """文档列表分页响应。

    遵循统一分页结构：{"items": [...], "total": 100, "page": 1, "page_size": 20}

    Attributes:
        items: 文档响应列表。
        total: 总记录数。
        page: 当前页码。
        page_size: 每页条数。
    """

    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int
