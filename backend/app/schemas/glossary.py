"""专业术语集 Schema（S8/S2）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ApiParam(BaseModel):
    key: str
    value: str = ""
    in_location: Literal["query", "path", "header", "body"] = "query"
    enabled: bool = True


class ApiSourceConfig(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    method: Literal["GET", "POST", "PUT", "DELETE"] = "GET"
    params: list[ApiParam] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    json_path: str = ""
    timeout: int = Field(default=30, ge=1, le=120)


class DbSourceConfig(BaseModel):
    db_type: Literal["mysql"] = "mysql"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    user: str = ""
    password: str = ""
    database: str = ""
    charset: str = "utf8mb4"
    mode: Literal["table", "sql"] = "table"
    table: str = ""
    sql_query: str = ""


class TermBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    source_type: Literal["manual", "api", "db"] = "manual"
    source_config: dict = Field(default_factory=dict)
    columns: list[dict] = Field(default_factory=list)
    column_aliases: dict[str, str] = Field(default_factory=dict)
    sync_enabled: bool = False
    auto_import: bool = False
    import_data: list[dict] | None = None


class TermBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    source_config: dict | None = None
    columns: list[dict] | None = None
    column_aliases: dict[str, str] | None = None
    sync_enabled: bool | None = None


class TestApiRequest(ApiSourceConfig):
    pass


class TestDbRequest(DbSourceConfig):
    pass


class DbTablesRequest(BaseModel):
    db_type: Literal["mysql"] = "mysql"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    user: str = ""
    password: str = ""
    database: str = ""
    charset: str = "utf8mb4"


class PreviewSqlRequest(DbSourceConfig):
    pass

class TermCreateRequest(BaseModel):
    term: str = Field(min_length=1, max_length=256)
    term_base_id: str
    standard_name: str = Field(default="", max_length=256)
    english_term: str = Field(default="", max_length=256)
    definition: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=128)
    standard_number: str = Field(default="", max_length=128)
    synonyms: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    extras: dict = Field(default_factory=dict)


class TermUpdateRequest(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=256)
    standard_name: str | None = Field(default=None, max_length=256)
    english_term: str | None = Field(default=None, max_length=256)
    definition: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=128)
    standard_number: str | None = Field(default=None, max_length=128)
    synonyms: list[str] | None = None
    aliases: list[str] | None = None
    extras: dict | None = None


class TermReviewRequest(BaseModel):
    action: Literal["approve", "reject"]


class TermBatchRequest(BaseModel):
    items: list[dict] = Field(default_factory=list)


class TermItemUpsert(BaseModel):
    """术语集内批量保存项：id 为空=新增，有 id=更新。"""
    id: str | None = None
    term: str = Field(min_length=1, max_length=256)
    english_term: str = Field(default="", max_length=256)
    aliases: list[str] = Field(default_factory=list)
    definition: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=128)
    standard_number: str = Field(default="", max_length=128)
    synonyms: list[str] = Field(default_factory=list)
    extras: dict = Field(default_factory=dict)


class TermBatchSaveRequest(BaseModel):
    """术语集内批量保存：新增/修改/删除一次提交（对齐原项目 batch save）。"""
    items: list[TermItemUpsert] = Field(default_factory=list)
    deleted_ids: list[str] = Field(default_factory=list)
