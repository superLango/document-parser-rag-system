"""SFT prompt texts shared by the training-data builder and inference path.

``tools/prepare_sft.py`` imports these so the strings used to train
``adapter-v1`` and the strings the engine sends at inference cannot drift apart.

Keep the wording stable: changing it changes the prompt distribution the adapter
was trained on.
"""

from __future__ import annotations

SYSTEM = (
    "你是金属材料标准结构化抽取器。只能使用输入中出现的文字、数值和标准编号，"
    "不得推断、补全或改写数值；不确定的字段不要输出。只输出 JSON，不要解释。"
)

INSTRUCTIONS = {
    "header_mapping": (
        "任务：header_mapping。为每一列给出 role（grade/condition/property/ignore）；"
        "property 使用输入中出现的属性名或标准属性符号，unit 可为空。"
    ),
    "header_mapping_constrained": (
        "任务：header_mapping。为每一列给出 role（grade/condition/property/ignore）；"
        "property 必须从 allowed_properties 或 allowed_elements 中选择精确名称，"
        "不得发明新名称；不确定的列输出 ignore；unit 可为空。"
    ),
    "row_record": (
        "任务：row_record。输出 grade、condition、properties；每个属性包含 raw、"
        "comparator、unit，raw 必须逐字来自 row。"
    ),
    "row_record_perturb": (
        "任务：row_record。输入行含 OCR 表层噪声；输出仍使用规范化后的 raw。"
    ),
    "clause_extract": (
        "任务：clause_extract。输出 fields；每个字段包含 raw、text、comparator、unit，"
        "raw 必须逐字出现在 text 中。"
    ),
    "citation_constraint": (
        "任务：citation_constraint。根据引用属性与选择上下文判断是否展开，"
        "输出 expand 与 selection_reason。"
    ),
}
