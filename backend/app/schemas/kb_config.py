"""知识库配置中心 Schema 模块。

定义配置中心 API 的请求/响应模型，覆盖：
- KB config JSON 读取/更新
- 领域模板列表/详情/应用
- Hook 脚本管理
- 领域配置表（类别/枚举/正则/字段模板/字典配置）查询
- 配置校验与资源诊断

对应端点：``app.api.v1.endpoints.kb_config``
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# KB config JSON 读取/更新
# ============================================================
class KbConfigResponse(BaseModel):
    """知识库完整配置响应（合并后的 KBConfig）。"""

    kb_id: UUID
    config: dict[str, Any] = Field(description="合并后的扁平配置（ocr/vector/extraction/qa/dict）")
    categories: list[dict[str, Any]] = Field(
        default_factory=list, description="抽取类别列表（含 enum 约束）"
    )
    field_templates: dict[str, list] = Field(
        default_factory=dict, description="字段模板（doc_info / category_data）"
    )
    regex_rules: list[dict[str, Any]] = Field(default_factory=list, description="正则规则列表")
    template_code: str | None = Field(None, description="初始化所用模板编码")


class KbConfigUpdate(BaseModel):
    """更新 KB config JSON 请求。

    采用深合并策略：传入的配置覆盖同名键，子字典递归合并。
    传空 dict 等于不修改。

    Attributes:
        config: 配置覆盖项（ocr/vector/extraction/qa/dict 各节）。
    """

    config: dict[str, Any] = Field(
        default_factory=dict, description="配置覆盖项，深合并到现有 config"
    )


class KbConfigSectionUpdate(BaseModel):
    """更新 KB config 某一节请求。"""

    section: dict[str, Any] = Field(..., description="该节的配置覆盖项")


# ============================================================
# 领域模板
# ============================================================
class DomainTemplateSummary(BaseModel):
    """领域模板摘要（列表用）。"""

    code: str
    name: str
    description: str
    domain_code: str
    category_count: int
    regex_rule_count: int
    has_hook: bool


class DomainTemplateDetail(BaseModel):
    """领域模板完整详情。"""

    code: str
    name: str
    description: str
    domain_code: str
    categories: list[dict[str, Any]]
    field_templates: list[dict[str, Any]]
    regex_rules: list[dict[str, Any]]
    config_override: dict[str, Any]
    has_hook: bool


class ApplyTemplateRequest(BaseModel):
    """应用领域模板到知识库请求。"""

    template_code: str = Field(..., description="模板编码")


class ApplyTemplateResult(BaseModel):
    """应用模板结果。"""

    template_code: str
    template_name: str
    categories_written: int
    field_templates_written: int
    regex_rules_written: int
    config_override_merged: bool
    hook_script_written: bool


# ============================================================
# Hook 管理
# ============================================================
class KbHookInfo(BaseModel):
    """Hook 脚本信息。"""

    kb_id: str
    has_hook: bool
    path: str
    overridden_interfaces: list[str] = Field(default_factory=list)
    size: int | None = None
    mtime: float | None = None


class KbHookContent(BaseModel):
    """Hook 脚本内容。"""

    kb_id: str
    has_hook: bool
    content: str = Field(default="", description="Hook 脚本内容（has_hook=False 时为空）")
    overridden_interfaces: list[str] = Field(default_factory=list)


class KbHookUpdate(BaseModel):
    """更新 Hook 脚本请求。"""

    content: str = Field(..., min_length=1, description="Hook 脚本内容")


class KbHookReloadResult(BaseModel):
    """Hook 重载结果。"""

    kb_id: str
    reloaded: bool
    has_script: bool


# ============================================================
# 领域配置表查询响应
# ============================================================
class KbCategoryResponse(BaseModel):
    """类别定义响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    extraction_class: str
    description: str | None = None
    is_active: bool
    sort_order: int
    recall_filter_threshold: float | None = None
    enums: dict[str, list] = Field(default_factory=dict, description="字段 enum 约束")
    created_at: datetime
    updated_at: datetime | None = None


class KbCategoryCreate(BaseModel):
    """新增类别请求。"""

    name: str = Field(..., min_length=1, max_length=100)
    extraction_class: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    is_active: bool = True
    sort_order: int = 0
    recall_filter_threshold: float | None = None
    enums: dict[str, list] = Field(
        default_factory=dict, description="字段 enum 约束 {field_name: [values]}"
    )


class KbCategoryUpdate(BaseModel):
    """更新类别请求。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    extraction_class: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None
    sort_order: int | None = None
    recall_filter_threshold: float | None = None
    enums: dict[str, list] | None = Field(None, description="覆盖 enum 约束")


class KbRegexRuleResponse(BaseModel):
    """正则规则响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    pattern: str
    description: str | None = None
    enabled: bool
    sort_order: int
    created_at: datetime


class KbFieldTemplateResponse(BaseModel):
    """字段模板响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    template_type: str
    fields: list[dict[str, Any]]
    prompt: str | None = None


# ============================================================
# 配置校验与资源诊断
# ============================================================
class KbConfigValidationResult(BaseModel):
    """配置校验结果。"""

    valid: bool
    errors: list[str] = Field(default_factory=list, description="校验错误列表")
    warnings: list[str] = Field(default_factory=list, description="校验警告列表")
    checks: dict[str, bool] = Field(
        default_factory=dict, description="各项检查结果 {check_name: passed}"
    )


class KbResourceVerifyResult(BaseModel):
    """资源完整性诊断结果。"""

    kb_id: UUID
    steps: dict[str, dict[str, Any]] = Field(
        description="各资源步骤状态 {step: {ok, detail/error}}"
    )


class ServiceCheckResult(BaseModel):
    """单个服务校验结果。"""

    name: str = Field(description="服务名称，如 minio、milvus、nebula、llm、redis、ocr_vllm、popo_vllm")
    display_name: str = Field(description="服务显示名称")
    status: str = Field(description="校验状态: ok / error / warning")
    message: str = Field(description="校验结果消息")
    response_time_ms: float = Field(default=0, description="响应时间（毫秒）")
    details: dict[str, Any] = Field(default_factory=dict, description="额外详情")


class ServicesDiagnoseResult(BaseModel):
    """所有服务一键诊断结果。"""

    kb_id: UUID
    total: int = Field(description="总服务数")
    ok_count: int = Field(description="正常数量")
    error_count: int = Field(description="错误数量")
    warning_count: int = Field(description="警告数量")
    services: list[ServiceCheckResult] = Field(description="各服务校验结果列表")
    checked_at: datetime = Field(description="校验时间")


class ServiceConfigItem(BaseModel):
    """单个服务配置项。"""

    key: str = Field(description="配置键名")
    label: str = Field(description="配置显示名")
    type: str = Field(description="配置类型: string / number / boolean / password")
    value: Any = Field(description="当前值")
    default: Any = Field(default=None, description="默认值")
    required: bool = Field(default=False, description="是否必填")
    placeholder: str | None = Field(default=None, description="占位提示")
    description: str | None = Field(default=None, description="配置说明")


class ServiceConfigSection(BaseModel):
    """服务配置节。"""

    name: str = Field(description="服务标识名")
    display_name: str = Field(description="服务显示名称")
    description: str = Field(description="服务描述")
    icon: str | None = Field(default=None, description="图标名")
    category: str = Field(description="分类: storage / vector / graph / llm / model / cache")
    configurable: bool = Field(default=True, description="是否可配置（诊断通过后才可配置）")
    fields: list[ServiceConfigItem] = Field(description="配置项列表")
    last_status: dict | None = Field(default=None, description="上次校验结果状态")
