"""领域模板包。

提供内置领域模板，支持通过模板快速初始化知识库领域配置，替代手工逐项配置。
新建知识库时指定 ``template_code``，由 ``domain_template_service`` 将模板
配置写入 ``kb_categories`` / ``kb_field_templates`` / ``kb_regex_rules`` 等表。

内置模板（4 个）：
- ``material_testing``：航天航空检测标准抽取（材料检测，默认领域）
- ``medical_device``：医疗器械文档抽取
- ``contract``：合同条款抽取
- ``general_qa``：通用问答（无结构化抽取，纯 RAG）

设计原则：
1. 模板是**纯数据**（dataclass / dict），不含可执行逻辑，便于序列化与跨环境迁移
2. 模板数据与 ``kb_domain_config`` ORM 对齐，可直接落库
3. 无法通用化的特殊领域逻辑通过 Hook 脚本实现（见 ``app/kb_hooks/``）
4. 模板可指定 ``hook_template``（初始 Hook 脚本内容），由领域模板服务在
   初始化时写入 ``app/kb_hooks/{kb_id_hex}/hooks.py``，用户后续可独立修改
"""

from app.domain_templates.base import (
    CategoryDef,
    CategoryEnumDef,
    DomainTemplate,
    FieldTemplateDef,
    RegexRuleDef,
)
from app.domain_templates.contract import CONTRACT_TEMPLATE
from app.domain_templates.general_qa import GENERAL_QA_TEMPLATE
from app.domain_templates.material_testing import MATERIAL_TESTING_TEMPLATE
from app.domain_templates.medical_device import MEDICAL_DEVICE_TEMPLATE

# 模板注册表：template_code → DomainTemplate
TEMPLATES: dict[str, DomainTemplate] = {
    tpl.code: tpl
    for tpl in (
        MATERIAL_TESTING_TEMPLATE,
        MEDICAL_DEVICE_TEMPLATE,
        CONTRACT_TEMPLATE,
        GENERAL_QA_TEMPLATE,
    )
}


def get_template(code: str) -> DomainTemplate | None:
    """按 code 获取领域模板。

    Args:
        code: 模板编码（如 ``material_testing``）。

    Returns:
        DomainTemplate 或 None（未找到）。
    """
    return TEMPLATES.get(code)


def list_templates() -> list[DomainTemplate]:
    """列出全部内置领域模板。"""
    return list(TEMPLATES.values())


__all__ = [
    "CategoryDef",
    "CategoryEnumDef",
    "DomainTemplate",
    "FieldTemplateDef",
    "RegexRuleDef",
    "TEMPLATES",
    "get_template",
    "list_templates",
    "MATERIAL_TESTING_TEMPLATE",
    "MEDICAL_DEVICE_TEMPLATE",
    "CONTRACT_TEMPLATE",
    "GENERAL_QA_TEMPLATE",
]
