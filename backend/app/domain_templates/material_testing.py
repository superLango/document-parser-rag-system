"""航天航空检测标准抽取领域模板（material_testing）。

本模板是当前项目的主领域配置，将 ``extraction_schemas.py`` /
``project_dict_service.py`` / ``field_template.py`` 中的硬编码配置项
提取为可配置数据，作为新建材料检测知识库的默认配置。

覆盖的硬编码源：
- ``extraction_schemas.py``: EXTRACTION_OUTPUT_SCHEMAS 注册表 + 各类 enum
- ``project_dict_service.py``: 三类候选项目正则（元素符号/力学符号/中文项目名）
- ``extraction_v2/config.py``: RECALL_FILTER_DYNAMIC_THRESHOLDS 等阈值
- ``field_template.py``: DEFAULT_FIELD_TEMPLATE

模板不含可执行逻辑，特殊后处理逻辑由 Hook 脚本承载（见 ``hook_template``）。
"""

from __future__ import annotations

from app.domain_templates.base import (
    CategoryDef,
    CategoryEnumDef,
    DictConfigDef,
    DomainTemplate,
    FieldTemplateDef,
    RegexRuleDef,
)

# ============================================================
# 化学成分项目（来自 sm_item WHERE feature='化学成分'）
# 对齐 extraction_schemas.py 的 CHEMICAL_ITEMS
# ============================================================
CHEMICAL_ITEMS = [
    "C", "Si", "Mn", "P", "S", "Cr", "Ni", "Mo",
    "Cu", "Ti", "Nb", "V", "W", "Co", "Al", "N",
]

# 室温拉伸项目（对齐 ROOM_TENSILE_ITEMS）
ROOM_TENSILE_ITEMS = [
    "规定非比例延伸强度Rp0.2",
    "抗拉强度Rm",
    "断后伸长率A",
    "断面收缩率Z",
]

# 冲击项目（对齐 IMPACT_ITEMS）
IMPACT_ITEMS = [
    "冲击吸收功KV2",
    "冲击吸收功KV8",
    "冲击韧性",
]

# 硬度项目（对齐 HARDNESS_ITEMS）
HARDNESS_ITEMS = ["HBW", "HRC", "HV", "HRB"]

# 气体项目（对齐 GAS_ITEMS）
GAS_ITEMS = ["O", "N", "H"]

# 单位 enum（按类别限制）
UNITS_CHEMICAL = ["%"]
UNITS_TENSILE = ["MPa", "%"]
UNITS_IMPACT = ["J", "J/cm²"]
UNITS_HARDNESS = ["HBW", "HRC", "HV"]
UNITS_GAS = ["ppm", "μg/g"]

# 温度 enum
TEMPERATURES_CHEMICAL = ["不适用"]
TEMPERATURES_ROOM = ["室温"]
TEMPERATURES_IMPACT = ["室温", "-196℃", "-80℃", "-40℃", "低温"]
TEMPERATURES_GAS = ["不适用"]


# ============================================================
# 候选项目正则（对齐 project_dict_service.py 的三类正则）
# ============================================================
# 注意：dataclass 字段中含反斜杠的正则需用原始字符串或双反斜杠
ELEMENT_PATTERN = (
    r"\b(?:C|Si|Mn|P|S|Cr|Ni|Mo|Cu|Ti|Nb|V|W|Co|Al|N|O|H|"
    r"As|Sn|Pb|Bi|Sb|Zr|B|Ca|Mg|Ce|La|Fe)\b"
)
MECH_SYMBOL_PATTERN = (
    r"\b(?:Rp\d+\.?\d*|Rm|Rt\d+\.?\d*|A\b|Z\b|Aku\d?|KV\d?|KU\d?|"
    r"HBW|HRC|HRB|HRA|HV|HS)\b"
)
CN_PROJECT_PATTERN = (
    r"[\u4e00-\u9fa5]{2,15}(?:强度|伸长率|收缩率|冲击|硬度|吸收功|韧性|延伸率|"
    r"屈服|抗拉|规定非比例|规定比例|断后|断面|永久|弹性模量|泊松比)"
)


# ============================================================
# 字段模板（对齐 field_template.py 的 DEFAULT_FIELD_TEMPLATE）
# ============================================================
DOC_INFO_FIELDS = [
    {"name": "标准号", "description": "标准编号，如 GB/T 1220-2007", "type": "string", "required": True},
    {"name": "标准名称", "description": "标准中文名称", "type": "string", "required": True},
    {"name": "发布日期", "description": "标准发布日期", "type": "string", "required": False},
    {"name": "实施日期", "description": "标准实施日期", "type": "string", "required": False},
    {"name": "发布单位", "description": "标准发布机构", "type": "string", "required": False},
    {"name": "标准状态", "description": "现行/废止/修订", "type": "string", "required": False},
    {"name": "代替标准", "description": "被代替的标准号", "type": "string", "required": False},
    {"name": "适用范围", "description": "标准适用范围描述", "type": "string", "required": False},
]

CATEGORY_DATA_FIELDS = [
    {"name": "牌号", "description": "材料牌号，如 06Cr19Ni10", "type": "string", "required": True},
    {"name": "项目", "description": "检测项目名（受类别 enum 约束）", "type": "string", "required": True},
    {"name": "单位", "description": "计量单位（受类别 enum 约束）", "type": "string", "required": True},
    {"name": "温度", "description": "试验温度（受类别 enum 约束）", "type": "string", "required": True},
    {"name": "标准要求", "description": "标准规定的技术要求值", "type": "string", "required": True},
]


# ============================================================
# 模板实例
# ============================================================
MATERIAL_TESTING_TEMPLATE = DomainTemplate(
    code="material_testing",
    name="航天航空检测标准抽取",
    description=(
        "面向航天航空材料检测标准文档的结构化抽取模板，覆盖化学成分、"
        "室温拉伸、冲击性能、硬度性能、气体分析等检测类别，"
        "含检测项目 enum 约束与候选项目正则规则，杜绝跨类混入。"
    ),
    domain_code="material_testing",
    categories=[
        CategoryDef(
            name="化学成分",
            extraction_class="化学成分",
            description="材料化学元素含量要求，如 C/Si/Mn/P/S/Cr 等",
            sort_order=10,
            enums=[
                CategoryEnumDef(field_name="项目", enum_values=CHEMICAL_ITEMS),
                CategoryEnumDef(field_name="单位", enum_values=UNITS_CHEMICAL),
                CategoryEnumDef(field_name="温度", enum_values=TEMPERATURES_CHEMICAL),
            ],
        ),
        CategoryDef(
            name="室温拉伸性能",
            extraction_class="室温拉伸",
            description="室温下材料拉伸力学性能，如 Rp0.2/Rm/A/Z",
            sort_order=20,
            recall_filter_threshold=0.6,
            enums=[
                CategoryEnumDef(field_name="项目", enum_values=ROOM_TENSILE_ITEMS),
                CategoryEnumDef(field_name="单位", enum_values=UNITS_TENSILE),
                CategoryEnumDef(field_name="温度", enum_values=TEMPERATURES_ROOM),
            ],
        ),
        CategoryDef(
            name="冲击性能",
            extraction_class="冲击性能",
            description="材料冲击韧性，如 KV2/KV8/冲击韧性",
            sort_order=30,
            recall_filter_threshold=0.6,
            enums=[
                CategoryEnumDef(field_name="项目", enum_values=IMPACT_ITEMS),
                CategoryEnumDef(field_name="单位", enum_values=UNITS_IMPACT),
                CategoryEnumDef(field_name="温度", enum_values=TEMPERATURES_IMPACT),
            ],
        ),
        CategoryDef(
            name="硬度性能",
            extraction_class="硬度性能",
            description="材料硬度指标，如 HBW/HRC/HV/HRB",
            sort_order=40,
            recall_filter_threshold=0.6,
            enums=[
                CategoryEnumDef(field_name="项目", enum_values=HARDNESS_ITEMS),
                CategoryEnumDef(field_name="单位", enum_values=UNITS_HARDNESS),
                CategoryEnumDef(field_name="温度", enum_values=TEMPERATURES_ROOM),
            ],
        ),
        CategoryDef(
            name="气体分析",
            extraction_class="气体分析",
            description="材料气体元素含量，如 O/N/H（保留兼容）",
            sort_order=50,
            is_active=False,  # 默认停用，按需启用
            enums=[
                CategoryEnumDef(field_name="项目", enum_values=GAS_ITEMS),
                CategoryEnumDef(field_name="单位", enum_values=UNITS_GAS),
                CategoryEnumDef(field_name="温度", enum_values=TEMPERATURES_GAS),
            ],
        ),
    ],
    field_templates=[
        FieldTemplateDef(
            template_type="doc_info",
            fields=DOC_INFO_FIELDS,
            prompt="提取标准文档的基本信息字段。",
        ),
        FieldTemplateDef(
            template_type="category_data",
            fields=CATEGORY_DATA_FIELDS,
            prompt=(
                "提取检测类别数据记录，每条记录包含牌号、项目、单位、温度、标准要求。"
                "项目名必须属于该类别的 enum 取值范围，杜绝跨类混入。"
            ),
        ),
    ],
    regex_rules=[
        RegexRuleDef(
            name="化学元素符号",
            pattern=ELEMENT_PATTERN,
            description="匹配化学元素符号，如 C/Si/Mn/P/S/Cr 等",
            sort_order=10,
        ),
        RegexRuleDef(
            name="力学性能符号",
            pattern=MECH_SYMBOL_PATTERN,
            description="匹配力学性能符号，如 Rp0.2/Rm/A/Z/HBW/HRC 等",
            sort_order=20,
        ),
        RegexRuleDef(
            name="中文项目名",
            pattern=CN_PROJECT_PATTERN,
            description="匹配中文检测项目名，如 抗拉强度/断后伸长率/冲击吸收功 等",
            sort_order=30,
        ),
    ],
    dict_config=DictConfigDef(
        enabled=True,
        match_threshold=0.6,
        whitelist_top_k=20,
        validation_top_k=1,
        validation_similarity_threshold=0.6,
        tables_mapping={
            "sm_feature": {"name_field": "NAME", "id_field": "ID", "flag_field": "FLAG"},
            "sm_item": {
                "name_field": "NAME",
                "id_field": "id",
                "english_name_field": "ENGLISH_NAME",
                "alias_field": "ITEM_ALIAS",
                "unit_field": "UNIT",
                "feature_field": "FEATURE",
            },
            "sm_method": {
                "name_field": "NAME",
                "id_field": "ID",
                "type_field": "TYPE",
                "code_field": "METHOD_CODE",
                "range_field": "RANGE",
                "feature_field": "FEATURE",
            },
        },
    ),
    config_override={
        "extraction": {
            "output_schema_mode": "auto",
            "passes": 3,
            "recall_classify_filter_enabled": True,
        },
    },
    hook_template=None,  # 材料检测领域默认逻辑可覆盖，无需 Hook
)
