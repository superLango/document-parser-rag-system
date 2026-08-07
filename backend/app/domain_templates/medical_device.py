"""医疗器械文档抽取领域模板（medical_device）。

面向医疗器械注册证、技术要求、检验报告等文档的结构化抽取。
覆盖产品基本信息、技术指标、生物相容性、临床评价等类别。

本模板为示例配置，实际使用时可根据具体器械类型（如 IVD、有源、无源）
在配置中心调整 enum 取值与正则规则。
"""

from __future__ import annotations

from app.domain_templates.base import (
    CategoryDef,
    CategoryEnumDef,
    DomainTemplate,
    FieldTemplateDef,
    RegexRuleDef,
)


# 器械分类 enum（对齐国家药监局分类规则）
DEVICE_CATEGORY_ENUM = ["I类", "II类", "III类"]

# 技术指标单位 enum
TECH_UNITS = ["mm", "cm", "mL", "L", "mg", "g", "kg", "MPa", "kPa", "V", "A", "W", "Hz", "%", "℃"]

# 生物相容性试验项目 enum
BIOCOMPAT_ITEMS = [
    "细胞毒性",
    "致敏试验",
    "刺激试验",
    "皮内反应",
    "全身毒性",
    "血液相容性",
    "植入试验",
    "遗传毒性",
]

# 临床评价方式 enum
CLINICAL_EVAL_METHODS = ["同品种临床数据", "临床试验", "文献评价", "豁免临床"]


MEDICAL_DEVICE_TEMPLATE = DomainTemplate(
    code="medical_device",
    name="医疗器械文档抽取",
    description=(
        "面向医疗器械注册证、技术要求、检验报告的结构化抽取模板，"
        "覆盖产品基本信息、技术指标、生物相容性、临床评价等类别。"
    ),
    domain_code="medical_device",
    categories=[
        CategoryDef(
            name="产品基本信息",
            extraction_class="产品基本信息",
            description="医疗器械产品名称、型号、分类等基本信息",
            sort_order=10,
            enums=[
                CategoryEnumDef(field_name="管理类别", enum_values=DEVICE_CATEGORY_ENUM),
            ],
        ),
        CategoryDef(
            name="技术指标",
            extraction_class="技术指标",
            description="产品技术要求中的性能指标，如尺寸、力学性能、电气参数等",
            sort_order=20,
            recall_filter_threshold=0.55,
            enums=[
                CategoryEnumDef(field_name="单位", enum_values=TECH_UNITS),
            ],
        ),
        CategoryDef(
            name="生物相容性",
            extraction_class="生物相容性",
            description="生物相容性试验项目与结果",
            sort_order=30,
            recall_filter_threshold=0.6,
            enums=[
                CategoryEnumDef(field_name="项目", enum_values=BIOCOMPAT_ITEMS),
            ],
        ),
        CategoryDef(
            name="临床评价",
            extraction_class="临床评价",
            description="临床评价方式与结论",
            sort_order=40,
            enums=[
                CategoryEnumDef(field_name="评价方式", enum_values=CLINICAL_EVAL_METHODS),
            ],
        ),
    ],
    field_templates=[
        FieldTemplateDef(
            template_type="doc_info",
            fields=[
                {"name": "产品名称", "description": "医疗器械产品名称", "type": "string", "required": True},
                {"name": "型号规格", "description": "产品型号与规格", "type": "string", "required": True},
                {"name": "注册证编号", "description": "医疗器械注册证号", "type": "string", "required": False},
                {"name": "管理类别", "description": "I/II/III类", "type": "string", "required": True},
                {"name": "生产企业", "description": "生产企业名称", "type": "string", "required": False},
                {"name": "批准日期", "description": "注册证批准日期", "type": "string", "required": False},
                {"name": "有效期至", "description": "注册证有效期", "type": "string", "required": False},
            ],
            prompt="提取医疗器械注册证/技术要求的基本信息字段。",
        ),
        FieldTemplateDef(
            template_type="category_data",
            fields=[
                {"name": "型号", "description": "产品型号", "type": "string", "required": True},
                {"name": "项目", "description": "技术指标或试验项目名", "type": "string", "required": True},
                {"name": "单位", "description": "计量单位", "type": "string", "required": False},
                {"name": "标准要求", "description": "标准规定的技术要求值", "type": "string", "required": True},
                {"name": "检验结果", "description": "实际检验结果", "type": "string", "required": False},
            ],
            prompt="提取医疗器械技术指标或试验数据记录。",
        ),
    ],
    regex_rules=[
        RegexRuleDef(
            name="型号规格",
            pattern=r"[A-Z0-9][A-Za-z0-9\-_/]{2,30}",
            description="匹配医疗器械型号规格，如 SY-100A、IVD-200",
            sort_order=10,
        ),
        RegexRuleDef(
            name="数值与单位",
            pattern=r"\d+\.?\d*\s*(?:mm|cm|mL|L|mg|g|kg|MPa|kPa|V|A|W|Hz|℃|%)",
            description="匹配数值与单位的组合，如 100mm、3.5MPa",
            sort_order=20,
        ),
    ],
    config_override={
        "extraction": {
            "output_schema_mode": "auto",
            "passes": 2,
        },
    },
    hook_template=None,
)
