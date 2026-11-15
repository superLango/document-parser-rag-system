"""Fixed output schema for standard documents (from legacy product_standard)."""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0.0"

# 必填字段（缺失即缺陷）。
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "standard_info": ("标准名称", "标准编号"),
    "items": ("项目名称", "材料牌号", "标准要求"),
    "heat_treatment": ("材料牌号", "工序名称", "项目大类"),
}

# 条件字段：源文出现就必须填；源文确实没有才允许为空。
CONDITIONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "items": (
        "单位",
        "试验方法",
        "试验温度",
        "位置",
        "方向",
        "尺寸厚度",
        "试样状态",
        "取样数量",
        "取样说明",
        "锻件类型",
    ),
    "heat_treatment": (
        "工艺名称",
        "保温温度",
        "保温时间",
        "冷却介质",
        "介质温度",
        "装炉温度",
        "出炉温度",
        "升温速率",
        "降温速率",
    ),
}

# 源文出现这些词，说明对应条件字段"有"，输出不能为空。
FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "试验方法": ("试验方法", "检测方法", "检验方法", "试验标准", "GB/T", "ASTM", "ISO"),
    "试验温度": ("试验温度", "温度", "℃", "°C"),
    "位置": ("位置", "D/4", "1/2", "表面", "中心"),
    "方向": ("方向", "纵向", "横向", "切向", "径向", "轴向"),
    "尺寸厚度": ("尺寸", "厚度", "外径", "壁厚", "直径"),
    "试样状态": ("试样状态", "状态", "铸态", "锻态", "固溶", "时效", "退火"),
    "取样数量": ("取样", "数量", "每批", "每炉"),
    "取样说明": ("取样说明",),
    "锻件类型": ("锻件类型", "锻件"),
    "工艺名称": ("工艺", "固溶", "退火", "淬火", "回火", "时效"),
    "保温温度": ("保温温度", "保温"),
    "保温时间": ("保温时间", "保温"),
    "冷却介质": ("冷却", "空冷", "油冷", "水冷", "炉冷"),
    "介质温度": ("介质温度",),
    "装炉温度": ("装炉",),
    "出炉温度": ("出炉",),
    "升温速率": ("升温",),
    "降温速率": ("降温",),
}

PROPERTY_NAMES: dict[str, str] = {
    "Rm": "抗拉强度",
    "Rp0.2": "规定塑性延伸强度",
    "ReH": "屈服强度",
    "ReL": "屈服强度",
    "A": "断后伸长率",
    "A50mm": "断后伸长率(A50mm)",
    "Z": "断面收缩率",
    "KV2": "冲击吸收能量",
    "KU2": "冲击吸收能量",
    "HB": "布氏硬度",
    "HBW": "布氏硬度",
    "HRC": "洛氏硬度",
    "HRB": "洛氏硬度",
    "HV": "维氏硬度",
    "E": "弹性模量",
    "KIC": "断裂韧度",
}

PROPERTY_UNITS: dict[str, str] = {
    "Rm": "MPa",
    "Rp0.2": "MPa",
    "ReH": "MPa",
    "ReL": "MPa",
    "A": "%",
    "A50mm": "%",
    "Z": "%",
}

# 固定项目大类顺序（用于检查 项目大类 字段与排序）。
FEATURE_ORDER = (
    "化学成分",
    "室温拉伸",
    "高温拉伸",
    "低温拉伸",
    "高温光滑持久",
    "室温持久",
    "夏比冲击",
    "布氏硬度",
    "洛氏硬度",
    "维氏硬度",
    "低倍",
    "高倍组织",
    "超声波检测",
    "渗透检测",
    "射线检测",
    "外观质量",
    "尺寸",
)


def property_name(measure: str) -> str:
    return PROPERTY_NAMES.get(str(measure), str(measure))


def field_hints(field: str) -> tuple[str, ...]:
    return FIELD_HINTS.get(field, (field,))


def schema_summary() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "required": {key: list(values) for key, values in REQUIRED_FIELDS.items()},
        "conditional": {
            key: list(values) for key, values in CONDITIONAL_FIELDS.items()
        },
        "property_names": dict(PROPERTY_NAMES),
        "feature_order": list(FEATURE_ORDER),
    }
