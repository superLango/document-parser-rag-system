"""内置规则注册表（RULE_REGISTRY）。

把 v3 硬编码的后处理 / 校验逻辑注册为可配置规则，与 Schema 模板同级的
"内置规则"来源。用户可在配置中心选择启用、调整参数、绑定作用域。

注册内容：
- rule_key：规则标识
- name / description：展示名与说明
- stage：post（后处理）/ validation（校验）
- enabled_default：内置默认启用状态（保证未配置时行为不回归）
- sort_order：同 stage 内默认执行顺序
- params_schema：参数定义（供前端动态渲染表单）
- default_params：默认参数（与现有硬编码默认值对齐）

新增规则只需在对应 stage 的 dict 中追加一项，无需改数据库结构。
"""

from __future__ import annotations

from typing import Any

RULE_STAGE_POST = "post"
RULE_STAGE_VALIDATION = "validation"


def _spec(
    name: str,
    description: str,
    enabled_default: bool,
    sort_order: int,
    params_schema: list[dict[str, Any]],
    default_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一条规则元数据。"""
    return {
        "rule_key": "",  # 由调用方覆盖
        "name": name,
        "description": description,
        "stage": "",
        "enabled_default": enabled_default,
        "sort_order": sort_order,
        "params_schema": params_schema,
        "default_params": default_params or {},
    }


def _fill_key(rules: dict[str, dict[str, Any]], stage: str) -> dict[str, dict[str, Any]]:
    """为每条规则填充 rule_key 与 stage 字段。"""
    for key, spec in rules.items():
        spec["rule_key"] = key
        spec["stage"] = stage
    return rules


# 后处理规则（stage=post），顺序与现有 post_processor 一致
POST_RULES: dict[str, dict[str, Any]] = {
    "normalize_item": _spec(
        name="项目名归一化",
        description="项目名向量匹配优先，失败回落轻量匹配；可引用术语集扩充候选",
        enabled_default=True,
        sort_order=10,
        params_schema=[
            {"key": "match_sim_threshold", "label": "匹配相似度阈值", "type": "number", "default": 0.85},
            {"key": "use_vector", "label": "启用向量匹配", "type": "switch", "default": True},
            {"key": "fallback_matcher", "label": "启用轻量匹配兜底", "type": "switch", "default": True},
            {"key": "term_refs", "label": "术语集引用", "type": "terms", "default": []},
        ],
        default_params={"match_sim_threshold": 0.85, "use_vector": True, "fallback_matcher": True, "term_refs": []},
    ),
    "normalize_method_year": _spec(
        name="方法年代号补全",
        description="无年代号时从方法列表补全最新年代号",
        enabled_default=True,
        sort_order=20,
        params_schema=[
            {"key": "latest_only", "label": "仅取最新年代号", "type": "switch", "default": True},
        ],
        default_params={"latest_only": True},
    ),
    "temperature_filter": _spec(
        name="温度分类修正",
        description="高温/低温拉伸剔除温度不匹配记录，室温拉伸补室温",
        enabled_default=True,
        sort_order=30,
        params_schema=[
            {"key": "apply_categories", "label": "生效类别", "type": "list",
             "default": ["高温拉伸", "低温拉伸", "室温拉伸"]},
        ],
        default_params={"apply_categories": ["高温拉伸", "低温拉伸", "室温拉伸"]},
    ),
    "dedup": _spec(
        name="记录去重",
        description="按字段哈希去重，剔除重复记录",
        enabled_default=True,
        sort_order=50,
        params_schema=[
            {"key": "sim_threshold", "label": "相似度阈值", "type": "number", "default": 0.95},
        ],
        default_params={"sim_threshold": 0.95},
    ),
}

# 校验规则（stage=validation）
VALIDATION_RULES: dict[str, dict[str, Any]] = {
    "cross_validate": _spec(
        name="跨类校验",
        description="项目名全表检索 + 白名单兜底，剔除跨类混入；白名单可引用术语集扩充",
        enabled_default=True,
        sort_order=10,
        params_schema=[
            {"key": "sim_threshold", "label": "置信度阈值", "type": "number", "default": 0.35},
            {"key": "whitelist_sim", "label": "白名单相似度", "type": "number", "default": 0.90},
            {"key": "fallback_whitelist", "label": "启用白名单兜底", "type": "switch", "default": True},
            {"key": "term_refs", "label": "白名单术语集", "type": "terms", "default": []},
        ],
        default_params={"sim_threshold": 0.35, "whitelist_sim": 0.90, "fallback_whitelist": True, "term_refs": []},
    ),
    "field_required": _spec(
        name="必填校验",
        description="校验指定字段非空，可选剔除或仅告警",
        enabled_default=False,
        sort_order=20,
        params_schema=[
            {"key": "fields", "label": "必填字段", "type": "list", "default": []},
            {"key": "policy", "label": "策略", "type": "enum", "default": "warn",
             "options": ["reject", "warn"]},
        ],
        default_params={"fields": [], "policy": "warn"},
    ),
    "field_enum": _spec(
        name="枚举校验",
        description="校验字段值属于术语集/静态枚举",
        enabled_default=False,
        sort_order=30,
        params_schema=[
            {"key": "field", "label": "校验字段", "type": "string", "default": ""},
            {"key": "whitelist_source", "label": "枚举来源", "type": "enum",
             "default": "term_base", "options": ["term_base", "static"]},
            {"key": "values", "label": "静态枚举值", "type": "list", "default": []},
            {"key": "term_refs", "label": "术语集引用", "type": "terms", "default": []},
        ],
        default_params={"field": "", "whitelist_source": "term_base", "values": [], "term_refs": []},
    ),
    "field_value_range": _spec(
        name="数值范围校验",
        description="校验数值字段落在指定区间",
        enabled_default=False,
        sort_order=40,
        params_schema=[
            {"key": "field", "label": "校验字段", "type": "string", "default": ""},
            {"key": "min", "label": "下限", "type": "number", "default": None},
            {"key": "max", "label": "上限", "type": "number", "default": None},
        ],
        default_params={"field": "", "min": None, "max": None},
    ),
    "field_consistency": _spec(
        name="字段一致性",
        description="校验两个字段满足指定关系",
        enabled_default=False,
        sort_order=50,
        params_schema=[
            {"key": "field_a", "label": "字段A", "type": "string", "default": ""},
            {"key": "field_b", "label": "字段B", "type": "string", "default": ""},
            {"key": "operator", "label": "关系", "type": "enum", "default": "eq",
             "options": ["eq", "contains"]},
        ],
        default_params={"field_a": "", "field_b": "", "operator": "eq"},
    ),
}

# 全量注册表：{stage: {rule_key: spec}}
RULE_REGISTRY: dict[str, dict[str, dict[str, Any]]] = {
    RULE_STAGE_POST: _fill_key(POST_RULES, RULE_STAGE_POST),
    RULE_STAGE_VALIDATION: _fill_key(VALIDATION_RULES, RULE_STAGE_VALIDATION),
}


def get_builtin_rule(stage: str, rule_key: str) -> dict[str, Any] | None:
    """按 stage + rule_key 取内置规则元数据。"""
    return RULE_REGISTRY.get(stage, {}).get(rule_key)


def default_enabled_map() -> dict[str, bool]:
    """内置默认启用掩码：{rule_key: enabled}（覆盖 post + validation）。"""
    mapping: dict[str, bool] = {}
    for rules in RULE_REGISTRY.values():
        for key, spec in rules.items():
            mapping[key] = spec["enabled_default"]
    return mapping