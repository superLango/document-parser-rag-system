"""领域模板基类与数据结构定义。

定义领域模板的标准数据结构，与 ``app.models.kb_domain_config`` ORM 模型对齐。
模板是纯数据，不含可执行逻辑（可执行逻辑由 Hook 脚本承载）。

数据流向：
    DomainTemplate（本模块）
        ↓ domain_template_service.init_kb_from_template
    KbCategory / KbCategoryEnum / KbFieldTemplate / KbRegexRule
        ↓ kb_config_loader.KBConfigLoader.load
    KBConfig（运行时配置对象）
        ↓ 抽取 / RAG / OCR 等服务消费
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CategoryEnumDef:
    """类别字段 enum 约束定义。

    对应 ``KbCategoryEnum`` 表，约束某类别某字段的取值范围，杜绝跨类混入。

    Attributes:
        field_name: 字段名（如 "项目"、"单位"、"温度"）。
        enum_values: 允许取值列表（如 ["C","Si","Mn",...]）。
    """

    field_name: str
    enum_values: list[str]


@dataclass
class CategoryDef:
    """抽取类别定义。

    对应 ``KbCategory`` 表，替代 ``extraction_schemas.py`` 中硬编码的
    ``EXTRACTION_OUTPUT_SCHEMAS`` 注册表。

    Attributes:
        name: 类别名（如 "化学成分"）。
        extraction_class: LangExtract extraction_class 名（如 "室温拉伸"）。
        description: 类别描述。
        sort_order: 排序权重。
        recall_filter_threshold: 召回过滤阈值（None=用全局默认）。
        enums: 该类别的字段 enum 约束列表。
    """

    name: str
    extraction_class: str
    description: str = ""
    is_active: bool = True
    sort_order: int = 0
    recall_filter_threshold: float | None = None
    enums: list[CategoryEnumDef] = field(default_factory=list)


@dataclass
class FieldTemplateDef:
    """字段模板定义。

    对应 ``KbFieldTemplate`` 表，替代 ``field_template.py`` 中的
    ``DEFAULT_FIELD_TEMPLATE`` 硬编码。

    Attributes:
        template_type: 模板类型（doc_info | category_data）。
        fields: 字段定义列表 JSON（[{name,description,type,required}, ...]）。
        prompt: 字段抽取提示词补充说明。
    """

    template_type: str  # doc_info | category_data
    fields: list[dict[str, Any]]
    prompt: str | None = None


@dataclass
class RegexRuleDef:
    """候选项目正则规则定义。

    对应 ``KbRegexRule`` 表，承载候选项目的三类正则。

    Attributes:
        name: 规则名（如 "化学元素符号"）。
        pattern: 正则表达式字符串。
        description: 规则描述。
        sort_order: 排序权重。
    """

    name: str
    pattern: str
    description: str = ""
    sort_order: int = 0


@dataclass
class DomainTemplate:
    """领域模板完整定义。

    一个领域模板包含该领域知识库初始化所需的全部配置数据，由
    ``domain_template_service.init_kb_from_template`` 落库到 KB 专属配置表。

    Attributes:
        code: 模板编码（如 ``material_testing``），全局唯一，用作 ``template_code``。
        name: 模板显示名（如 "航天航空检测标准抽取"）。
        description: 模板描述。
        domain_code: 领域编码（与 ``KnowledgeBase.domain_code`` 对齐）。
        categories: 抽取类别定义列表。
        field_templates: 字段模板列表（doc_info / category_data）。
        regex_rules: 候选项目正则规则列表。
        config_override: KB config JSON 覆盖项（合并到 ``KnowledgeBase.config``）。
        hook_template: 初始 Hook 脚本内容（写入 ``app/kb_hooks/{kb_id}/hooks.py``）。
            None=不创建 Hook 文件，使用默认逻辑。
    """

    code: str
    name: str
    description: str
    domain_code: str
    categories: list[CategoryDef] = field(default_factory=list)
    field_templates: list[FieldTemplateDef] = field(default_factory=list)
    regex_rules: list[RegexRuleDef] = field(default_factory=list)
    config_override: dict[str, Any] = field(default_factory=dict)
    hook_template: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """生成模板摘要（用于列表接口，不含完整配置详情）。"""
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "domain_code": self.domain_code,
            "category_count": len(self.categories),
            "regex_rule_count": len(self.regex_rules),
            "has_hook": self.hook_template is not None,
        }

    def to_detail(self) -> dict[str, Any]:
        """生成模板完整详情（用于详情接口）。"""
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "domain_code": self.domain_code,
            "categories": [
                {
                    "name": c.name,
                    "extraction_class": c.extraction_class,
                    "description": c.description,
                    "is_active": c.is_active,
                    "sort_order": c.sort_order,
                    "recall_filter_threshold": c.recall_filter_threshold,
                    "enums": [
                        {"field_name": e.field_name, "enum_values": e.enum_values}
                        for e in c.enums
                    ],
                }
                for c in self.categories
            ],
            "field_templates": [
                {
                    "template_type": f.template_type,
                    "fields": f.fields,
                    "prompt": f.prompt,
                }
                for f in self.field_templates
            ],
            "regex_rules": [
                {
                    "name": r.name,
                    "pattern": r.pattern,
                    "description": r.description,
                    "sort_order": r.sort_order,
                }
                for r in self.regex_rules
            ],
            "config_override": self.config_override,
            "has_hook": self.hook_template is not None,
        }
