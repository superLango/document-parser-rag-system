"""抽取配置 Schema（M34/S2）：Schema 模板、Prompt、规则组、脚本。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.extraction import (
    EXTRACTION_STRATEGIES,
    FIELD_TYPES,
    NAME_SOURCES,
    PROMPT_SCOPES,
    RETURN_TYPES,
    SCRIPT_FOLDERS,
)


class SchemaTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    is_active: bool = True
    sort_order: int = 0


class SchemaTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    sort_order: int | None = None


class QuerySource(BaseModel):
    label: str = ""
    term_base_id: str = ""
    group_field: str = ""
    value_field: str = ""
    in_query: bool = False
    dedupe: bool = False
    query_main_limit: int = 30
    query_refined_limit: int = 8


class SchemaCategoryCreate(BaseModel):
    name: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=2000)
    return_type: str = "array"
    extraction_strategy: str = "auto"
    fixed_query: str = Field(default="", max_length=2000)
    confidence_threshold: float | None = None
    top_k: int | None = None
    rerank_top_k: int | None = None
    max_tokens: int | None = None
    name_source: str = "manual"
    name_term_base_id: str | None = None
    name_term_field: str = Field(default="", max_length=128)
    query_sources: list[QuerySource] = Field(default_factory=list)
    is_active: bool = True
    sort_order: int = 0

    @field_validator("return_type", "extraction_strategy", "name_source")
    @classmethod
    def _enum(cls, v: str, info):
        allowed = {
            "return_type": RETURN_TYPES,
            "extraction_strategy": EXTRACTION_STRATEGIES,
            "name_source": NAME_SOURCES,
        }[info.field_name]
        if v not in allowed:
            raise ValueError(f"无效取值：{v}")
        return v


class SchemaCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    return_type: str | None = None
    extraction_strategy: str | None = None
    fixed_query: str | None = Field(default=None, max_length=2000)
    confidence_threshold: float | None = None
    top_k: int | None = None
    rerank_top_k: int | None = None
    max_tokens: int | None = None
    name_source: str | None = None
    name_term_base_id: str | None = None
    name_term_field: str | None = Field(default=None, max_length=128)
    query_sources: list[QuerySource] | None = None
    is_active: bool | None = None
    sort_order: int | None = None

    @field_validator("return_type", "extraction_strategy", "name_source")
    @classmethod
    def _enum(cls, v: str | None, info):
        if v is None:
            return v
        allowed = {
            "return_type": RETURN_TYPES,
            "extraction_strategy": EXTRACTION_STRATEGIES,
            "name_source": NAME_SOURCES,
        }[info.field_name]
        if v not in allowed:
            raise ValueError(f"无效取值：{v}")
        return v


class SchemaFieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: str = "string"
    description: str = Field(default="", max_length=2000)
    example: str | None = Field(default=None, max_length=2000)
    required: bool = True
    sort_order: int = 0

    @field_validator("type")
    @classmethod
    def _type(cls, v: str):
        if v not in FIELD_TYPES:
            raise ValueError(f"无效字段类型：{v}")
        return v


class SchemaFieldUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    type: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    example: str | None = Field(default=None, max_length=2000)
    required: bool | None = None
    sort_order: int | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, v: str | None):
        if v is not None and v not in FIELD_TYPES:
            raise ValueError(f"无效字段类型：{v}")
        return v


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    scope: str = "simple"
    schema_template_id: str | None = None
    category_ids: list[str] = Field(default_factory=list)
    system_prompt: str = Field(default="", max_length=20000)
    user_prompt: str = Field(default="", max_length=20000)
    is_active: bool = True

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str):
        if v not in PROMPT_SCOPES:
            raise ValueError(f"无效模式：{v}")
        return v


class PromptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class PromptCategoryContent(BaseModel):
    category_id: str
    user_prompt: str = Field(default="", max_length=20000)


class PromptSaveRequest(BaseModel):
    system_prompt: str = Field(default="", max_length=20000)
    user_prompt: str = Field(default="", max_length=20000)
    categories: list[PromptCategoryContent] = Field(default_factory=list)
    is_active: bool | None = None


class RuleGroupCreate(BaseModel):
    schema_template_id: str
    name: str | None = Field(default=None, max_length=128)
    description: str = Field(default="", max_length=2000)


class RuleGroupItemSave(BaseModel):
    id: str | None = None
    script_name: str = Field(min_length=1, max_length=128)
    params: dict = Field(default_factory=dict)
    enabled: bool = True
    sort_order: int = 0


class RuleGroupItemsSave(BaseModel):
    category_id: str | None = None
    items: list[RuleGroupItemSave] = Field(default_factory=list)


class ScriptCreate(BaseModel):
    folder: str = "post"
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    code: str = Field(default="", max_length=100000)

    @field_validator("folder")
    @classmethod
    def _folder(cls, v: str):
        if v not in SCRIPT_FOLDERS:
            raise ValueError(f"无效脚本目录：{v}")
        return v


class ScriptUpdate(BaseModel):
    folder: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    code: str | None = Field(default=None, max_length=100000)

    @field_validator("folder")
    @classmethod
    def _folder(cls, v: str | None):
        if v is not None and v not in SCRIPT_FOLDERS:
            raise ValueError(f"无效脚本目录：{v}")
        return v


class ScriptRunRequest(BaseModel):
    script_id: str | None = None
    code: str | None = Field(default=None, max_length=100000)
    args: dict = Field(default_factory=dict)
