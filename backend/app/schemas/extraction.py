"""抽取配置 Schema（M34/S2）：Schema 模板、Prompt、规则组、脚本。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.extraction import (
    EXTRACTION_STRATEGIES,
    FIELD_TYPES,
    NAME_SOURCES,
    PROMPT_SCOPES,
    RETURN_TYPES,
    SCRIPT_FOLDERS,
)


class ExtractionResultUpdate(BaseModel):
    """手动编辑后的抽取结果保存（新增/修改/删除记录与类型）。"""
    categories: list[dict] = Field(default_factory=list)


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
    # 术语集展开类别的特殊要求映射（{"类别名": "要求文本"}），Prompt 用 ${special_requirement} 组装
    special_requirements: dict[str, str] | None = Field(default=None)
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
    special_requirements: dict[str, str] | None = Field(default=None)
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


class PromptPreviewRequest(BaseModel):
    """Prompt 预览渲染：与真实抽取共用后端 prompt_renderer，保证所见即所得。"""
    schema_template_id: str | None = None
    category_id: str | None = None
    group_value: str | None = Field(default=None, max_length=128, description="术语集展开类别名（预览指定类别）")
    system_prompt: str | None = Field(default=None, max_length=20000)
    user_prompt: str | None = Field(default=None, max_length=40000)


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
    script_id: str = Field(min_length=1, max_length=64)
    stage: Literal["post", "validation"] = "post"
    category_name: str = Field(default="", max_length=128)
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


# ============================================================
# 全局配置（结构化抽取：retrieval / llm / kb_tool）
# ============================================================
class GlobalContextConfig(BaseModel):
    chars_per_token: float = Field(default=1.5, gt=0)


class GlobalRetrievalWeights(BaseModel):
    title: float = Field(default=0.2, ge=0)
    content: float = Field(default=0.8, ge=0)


class GlobalCategoryRecallConfig(BaseModel):
    """类别召回模式（9.5 演进第三版）。

    - loose：零命中剔除，置信度仅记录不强制（第一版行为）；
    - strict：命中分 < 阈值且词法命中不足时剔除（词法兜底 keyword_min_hits）；
    - off：全部类别参与（关闭召回过滤，含零命中类别）。
    """

    mode: Literal["loose", "strict", "off"] = "loose"
    top_k: int = Field(default=5, ge=1)
    per_dim_top_k: int = Field(default=10, ge=1)


class GlobalQueryEmbedConfig(BaseModel):
    content_max_chars: int = Field(default=2000, ge=1)
    dedupe_similarity_threshold: float = Field(default=0.85, ge=0, le=1)


class GlobalHybridConfig(BaseModel):
    enabled: bool = True
    rrf_k: float = Field(default=60.0, gt=0)
    dense_weight: float = Field(default=1.0, ge=0)
    keyword_weight: float = Field(default=1.2, ge=0)
    keyword_min_hits: int = Field(default=1, ge=1)


class GlobalRerankerConfig(BaseModel):
    enabled: bool = False
    model: str = Field(default="", max_length=500)
    top_n: int = Field(default=15, ge=1)
    # 抽取过滤开关（与 DEFAULT_GLOBAL_CONFIG.reranker 保持一致）：
    # threshold 重排分数阈值；category_filter_enabled 类别级过滤；
    # block_filter_enabled 块级过滤；rerank_query_enabled 重排专用精选 query。
    # 缺少这些字段会导致 Pydantic 静默丢弃，保存后回落默认值（无法关闭）。
    threshold: float = Field(default=0.0)
    category_filter_enabled: bool = True
    block_filter_enabled: bool = True
    rerank_query_enabled: bool = True


class GlobalRetrievalConfig(BaseModel):
    top_k: int = Field(default=10, ge=1)
    candidate_mult: int = Field(default=2, ge=1)
    weights: GlobalRetrievalWeights = Field(default_factory=GlobalRetrievalWeights)
    default_confidence_threshold: float = Field(default=0.35, ge=0, le=1)
    context_top_k: int = Field(default=20, ge=1)
    context_max_tokens: int = Field(default=56000, ge=1)
    context: GlobalContextConfig = Field(default_factory=GlobalContextConfig)
    data_route_top_k: int = Field(default=10, ge=1)
    meta_route_top_k: int = Field(default=5, ge=1)
    category_recall: GlobalCategoryRecallConfig = Field(default_factory=GlobalCategoryRecallConfig)
    query_embed: GlobalQueryEmbedConfig = Field(default_factory=GlobalQueryEmbedConfig)
    hybrid: GlobalHybridConfig = Field(default_factory=GlobalHybridConfig)
    reranker: GlobalRerankerConfig = Field(default_factory=GlobalRerankerConfig)


class GlobalConcurrencyConfig(BaseModel):
    max_concurrency: int = Field(default=24, ge=1)
    cross_category: int = Field(default=24, ge=1)
    within_category: int = Field(default=1, ge=1)


class GlobalBatchConfig(BaseModel):
    single_threshold: int = Field(default=16000, ge=1)
    batch_chars: int = Field(default=6000, ge=1)
    overlap: int = Field(default=500, ge=0)
    context_truncate: int = Field(default=64000, ge=1)


class GlobalBaseExtractConfig(BaseModel):
    temperature: float = Field(default=0.0, ge=0, le=2)
    top_p: float = Field(default=0.1, ge=0, le=1)
    top_k: int = Field(default=20, ge=1)
    max_tokens: int = Field(default=200000, ge=1)
    timeout: int = Field(default=300, ge=1)
    enable_thinking: bool = False
    concurrency: GlobalConcurrencyConfig = Field(default_factory=GlobalConcurrencyConfig)
    batch: GlobalBatchConfig = Field(default_factory=GlobalBatchConfig)


class GlobalLangExtractConfig(GlobalBaseExtractConfig):
    format_type: Literal["JSON", "YAML"] = "JSON"
    fence_output: bool = False
    max_examples: int = Field(default=3, ge=0)
    passes: int = Field(default=2, ge=1)
    context_window_chars: int = Field(default=56000, ge=1)
    max_char_buffer: int = Field(default=80000, ge=1)


class GlobalLLMConfig(BaseModel):
    engine: Literal["BaseExtract", "LangExtractPkg"] = "BaseExtract"
    engines: dict[str, GlobalBaseExtractConfig | GlobalLangExtractConfig] = Field(default_factory=dict)


class GlobalKbToolConfig(BaseModel):
    embed_batch_size: int = Field(default=16, ge=1)
    search_concurrency: int = Field(default=10, ge=1)
    semantic_top_k: int = Field(default=5, ge=1)
    match_top_k: int = Field(default=1, ge=1)
    match_threshold: float = Field(default=0.9, ge=0, le=1)
    script_timeout: int = Field(default=60, ge=1)
    script_max_output_bytes: int = Field(default=1024 * 1024, ge=1024)
    script_max_term_rows: int = Field(default=1000, ge=1)


class GlobalConfigContent(BaseModel):
    retrieval: GlobalRetrievalConfig = Field(default_factory=GlobalRetrievalConfig)
    llm: GlobalLLMConfig = Field(default_factory=GlobalLLMConfig)
    kb_tool: GlobalKbToolConfig = Field(default_factory=GlobalKbToolConfig)


class GlobalConfigSave(BaseModel):
    enabled: bool = True
    content: GlobalConfigContent = Field(default_factory=GlobalConfigContent)


class ScriptEmbedRequest(BaseModel):
    """脚本子进程嵌入回调请求（内部令牌鉴权，非用户 API）。"""

    token: str
    texts: list[str]
