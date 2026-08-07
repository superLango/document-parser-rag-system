"""合同条款抽取领域模板（contract）。

面向商业合同、协议书的结构化抽取，覆盖合同主体、金额条款、
期限条款、违约责任、争议解决等类别。

合同抽取以条款为核心单位，每条记录关联一个条款编号与条款内容。
"""

from __future__ import annotations

from app.domain_templates.base import (
    CategoryDef,
    CategoryEnumDef,
    DomainTemplate,
    FieldTemplateDef,
    RegexRuleDef,
)


# 合同类型 enum
CONTRACT_TYPES = [
    "买卖合同", "租赁合同", "承揽合同", "借款合同",
    "保证合同", "委托合同", "技术合同", "服务合同", "其他",
]

# 金额单位 enum
AMOUNT_UNITS = ["人民币元", "人民币万元", "美元", "欧元", "日元", "港元"]

# 争议解决方式 enum
DISPUTE_RESOLUTION = ["诉讼", "仲裁", "协商", "调解"]

# 期限单位 enum
TERM_UNITS = ["日", "月", "年", "工作日", "自然日"]


CONTRACT_TEMPLATE = DomainTemplate(
    code="contract",
    name="合同条款抽取",
    description=(
        "面向商业合同、协议书的结构化抽取模板，覆盖合同主体、金额条款、"
        "期限条款、违约责任、争议解决等类别，以条款为抽取单位。"
    ),
    domain_code="contract",
    categories=[
        CategoryDef(
            name="合同主体",
            extraction_class="合同主体",
            description="合同甲方、乙方等主体信息",
            sort_order=10,
            enums=[
                CategoryEnumDef(field_name="主体角色", enum_values=["甲方", "乙方", "丙方", "丁方"]),
            ],
        ),
        CategoryDef(
            name="金额条款",
            extraction_class="金额条款",
            description="合同标的金额、付款金额等",
            sort_order=20,
            enums=[
                CategoryEnumDef(field_name="金额单位", enum_values=AMOUNT_UNITS),
            ],
        ),
        CategoryDef(
            name="期限条款",
            extraction_class="期限条款",
            description="合同期限、付款期限、交付期限等",
            sort_order=30,
            enums=[
                CategoryEnumDef(field_name="期限单位", enum_values=TERM_UNITS),
            ],
        ),
        CategoryDef(
            name="违约责任",
            extraction_class="违约责任",
            description="违约情形与违约金、赔偿等责任约定",
            sort_order=40,
            enums=[],
        ),
        CategoryDef(
            name="争议解决",
            extraction_class="争议解决",
            description="争议解决方式与管辖机构",
            sort_order=50,
            enums=[
                CategoryEnumDef(field_name="解决方式", enum_values=DISPUTE_RESOLUTION),
            ],
        ),
    ],
    field_templates=[
        FieldTemplateDef(
            template_type="doc_info",
            fields=[
                {"name": "合同名称", "description": "合同标题", "type": "string", "required": True},
                {"name": "合同编号", "description": "合同编号", "type": "string", "required": False},
                {"name": "合同类型", "description": "合同类型", "type": "string", "required": True},
                {"name": "签订日期", "description": "合同签订日期", "type": "string", "required": False},
                {"name": "签订地点", "description": "合同签订地点", "type": "string", "required": False},
            ],
            prompt="提取合同文档的基本信息字段。",
        ),
        FieldTemplateDef(
            template_type="category_data",
            fields=[
                {"name": "条款编号", "description": "条款编号，如第三条、3.1", "type": "string", "required": True},
                {"name": "条款标题", "description": "条款标题", "type": "string", "required": False},
                {"name": "条款内容", "description": "条款核心内容摘要", "type": "string", "required": True},
            ],
            prompt="提取合同条款记录，每条记录对应一个条款。",
        ),
    ],
    regex_rules=[
        RegexRuleDef(
            name="条款编号",
            pattern=r"第[一二三四五六七八九十百千零\d]+条|第\d+\.?\d*款|\d+\.\d+",
            description="匹配合同条款编号，如 第一条、3.1、第2款",
            sort_order=10,
        ),
        RegexRuleDef(
            name="金额表达",
            pattern=r"\d+\.?\d*\s*(?:元|万元|亿元|美元|欧元|日元|港元)",
            description="匹配金额表达，如 100万元、3.5亿元",
            sort_order=20,
        ),
        RegexRuleDef(
            name="日期表达",
            pattern=r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}",
            description="匹配日期表达，如 2026年1月1日、2026-01-01",
            sort_order=30,
        ),
    ],
    config_override={
        "extraction": {
            "output_schema_mode": "auto",
            "passes": 2,
            "recall_classify_filter_enabled": False,
        },
    },
    hook_template=None,
)
