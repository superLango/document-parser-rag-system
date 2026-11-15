"""Rule-based table profile and orientation detection.

Rewritten from the legacy ``tablegrid/profile.py``; detection stays cheap and
deterministic, and the contract is unchanged if a model classifier replaces the
fallback later.
"""

import re

from ..contracts import TableGrid
from .normalize import canonical_element, clean_text

MECHANICAL_MARKERS = (
    "力学性能", "抗拉", "屈服", "伸长", "收缩", "冲击", "硬度",
    "比例极限", "rm", "rel", "rp0.2", "kv2", "hb", "hrc", "hv",
    "σb", "σ0.2", "δ5", "ψ", "aku",
    "持久", "蠕变", "延伸率", "断面收缩", "抗剪",
    "疲劳", "应力比", "最大应力", "室温", "高温", "规定值",
    "mechanical propert", "tensile strength", "yield strength",
    "proof strength", "elongation", "reduction of area",
    "impact energy", "hardness",
)
CHEMICAL_MARKERS = (
    "碳当量", "裂纹敏感性", "cev", "pcm",
    "组分", "元素含量", "其他元素含量", "含量(摩尔分数)",
    "主要成分", "主要元素", "杂质元素", "成分%", "化学成分",
    "氯化物", "可浸出",
    "composition", "alloying element", "heat analysis",
    "chemical analysis", "chemical composition",
)
INSPECTION_MARKERS = (
    "检验项目", "取样数量", "取样部位", "取样要求", "试验方法", "判定", "检验规则",
    "工艺参数",
    "合格级别", "低倍", "低倍组织", "疏松", "偏析", "夹杂物", "非金属夹杂",
    "晶粒度", "显微组织", "晶间腐蚀", "应力腐蚀", "腐蚀试验", "腐蚀减重",
    "塔形", "超声波检验", "结果要求",
    "膜层", "电导率", "测量部位", "试样数量", "试样状态", "外观质量", "缺陷名称",
    "允许误差",
    "检验类型", "检验频次", "抽样水平", "抽样数量", "每批包含件数",
    "试验和检查", "试验标准", "试验项目", "适用文件", "试验类型", "取样位置",
    "热处理条件", "锻比", "操作说明", "锻造变形过程", "锻造方式", "锭型",
    "粗系", "细系", "硫化物", "氧化铝", "硅酸盐", "球状",
    "inspection item", "sample position", "testing standard", "sample qty",
    "test item", "test category", "acceptance criteria", "acceptance requirement",
    "test condition", "test method", "examination",
    "测试项目", "先决条件", "控制项目", "检验报告", "质量计划",
    "荧光", "渗透", "射线", "无损", "不合格", "不符合项",
    "lot size", "sample size",
)
DIMENSION_MARKERS = (
    "直径", "厚度", "宽度", "长度", "偏差", "尺寸", "外形",
    "弯曲度", "不圆度", "壁厚", "外径", "圆度",
    "长试样", "短试样", "交付规格", "公差要求",
    "测量表", "精密测量", "厚さ", "基本質量", "算出式", "规格",
    "dimension", "tolerance", "diameter", "thickness", "width",
)
ADMIN_MARKERS = (
    "审签", "会签", "签名", "签字", "更改", "修改为", "修改履历", "改版", "版本", "版次",
    "编号", "本标准", "文件号", "文件名称", "发文号", "发往单位", "份数", "页数", "页码",
    "章节", "编制", "审核", "批准", "校核", "审查", "标准化", "主题词", "内部文件",
    "内部编码", "编制单位", "军事代表室", "参考电站编码", "图号", "型别",
    "产品名称", "产品代号", "零件号", "项目名称", "适用范围", "技术要求", "章条号",
    "组批原则", "取样批次", "合格证", "交接确认", "锻件名称", "锻件图号",
    "采购规范", "登记号", "台签", "分发", "确认时间", "特殊过程", "序列号",
    "泵类型", "安全规定", "分析方法", "光度法",
    "approval process", "change log", "revision details", "rev. no.", "abbreviation",
    "rcc-m", "顾客代表", "变更原因", "工程变更", "首件试制", "台数", "使用部门",
    "要求类型", "具体要求", "输出文件", "违约", "质量红线", "修改号", "修改日期",
    "审批", "流程活动",
    "prepared by", "reviewed by", "approved by", "document no", "revision no",
    "conversion table", "correspondence", "换算", "对应关系",
)
STANDARD_CODE_RE = re.compile(
    r"(?:GB\s*/\s*T|GB|GJB|JB\s*/\s*T|YB\s*/\s*T|NB\s*/\s*T|YS\s*/\s*T|ASTM|"
    r"ISO(?=\s*-?\s*\d)|EN(?=\s*-?\s*\d)|DIN(?=\s*-?\s*\d)|RCC-M|HAF|Q\s*/\s*S|Q\s*/\s*Du)"
    r"\s*-?\s*[\dA-Z]",
    re.IGNORECASE,
)
CLASSIFICATION_MARKERS = (
    "分类", "新旧状态", "新状态", "旧状态", "状态对照", "类别", "钢类", "组别",
    "钢材种类", "牌号", "種類の記号", "分類", "種類",
    "classification", "alloy type",
)


def header_text(table: TableGrid, *, include_caption: bool = True) -> str:
    parts: list[str] = []
    for path in table.header_paths:
        parts.extend(path)
    if include_caption and table.caption:
        parts.append(table.caption)
    return clean_text(" ".join(parts)).lower()


ELEMENT_HEADER_RE = re.compile(r"[A-Z][a-z]?(?:\s*[+＋]\s*[A-Z][a-z]?)?(?:\*|[a-z])?")
NON_ELEMENT_HEADER_RE = re.compile(
    r"tensile|yield|proof|strength|elongation|reduction|hardness|impact|"
    r"temperature|thickness|diameter|width|length|size|property|properties|"
    r"treatment|condition|surface|test",
    re.IGNORECASE,
)


def _is_element_header(text: str) -> bool:
    value = clean_text(text)
    if not value:
        return False
    if NON_ELEMENT_HEADER_RE.search(value):
        return False
    # "Carbon, max." / "Oxygen range or max." / full English element names.
    # ``canonical_element`` already understands symbols, names and "+" sums.
    return canonical_element(value) is not None


ELEMENT_CELL_RE = re.compile(r"^[A-Z][a-z]?$")


def _is_element_cell(text: str) -> bool:
    value = clean_text(text)
    if ELEMENT_CELL_RE.fullmatch(value):
        return canonical_element(value) is not None
    # AMS composition tables label rows with full English names ("Silicon").
    # Grade codes such as C45 / H14 / Co9998 must not look like elements.
    if len(value) < 3 or any(char.isdigit() for char in value):
        return False
    if len(value.split()) != 1:
        return False
    return canonical_element(value) is not None


def _has_element_rows(table: TableGrid) -> bool:
    """Composition tables may keep elements in a data column, not in headers."""
    data = table.rows[table.header_rows :]
    if len(data) < 3:
        return False
    width = min(3, max((len(row) for row in data), default=0))
    headers = [" ".join(path) for path in table.header_paths]
    skip_tokens = (
        "质量等级", "等级", "class", "类别",
        "状态", "牌号", "厚度", "规格", "温度", "方向", "直径", "尺寸",
    )
    for col in range(width):
        header = headers[col] if col < len(headers) else ""
        if any(token in header for token in skip_tokens):
            # Quality/temper columns contain B/C/F or "O" values but are not
            # elements; a column of "O" (annealed temper) used to be mistaken
            # for oxygen, turning every mechanical table into element_rows.
            continue
        hits = [
            canonical_element(clean_text(row[col]))
            for row in data[:20]
            if col < len(row) and _is_element_cell(row[col])
        ]
        symbols = {symbol for symbol in hits if symbol}
        if len(hits) >= 3 and len(symbols) >= 2:
            return True
    return False


def _has_element_columns(table: TableGrid) -> bool:
    hits = 0
    seen: set[str] = set()
    for path in table.header_paths:
        for part in path:
            text = clean_text(part)
            if not text or len(text) > 8 or NON_ELEMENT_HEADER_RE.search(text):
                continue
            if _is_element_header(text):
                symbol = canonical_element(text)
                if symbol and symbol not in seen:
                    seen.add(symbol)
                    hits += 1
                break
    return hits >= 3


INSPECTION_TABLE_MARKERS = (
    "检验项目", "取样规定", "章条号", "试验方法",
    "test item", "test category", "acceptance criteria", "test method",
)
INCLUSION_MARKERS = ("非金属夹杂", "夹杂物", "inclusion")
MECHANICAL_CONCRETE = tuple(
    marker for marker in MECHANICAL_MARKERS if marker != "力学性能"
)
# Heat-treatment schedule tables (GB/T 3280 Annex C, GB/T 14976 Table 1) carry
# "热处理温度及冷却方式" / "推荐热处理制度" columns but no performance measures.
HEAT_HEADER_RE = re.compile(
    r"热处理(?:温度|制度|工艺)?|固溶处理|淬火|回火|正火|退火处理|时效处理|沉淀硬化"
)
HEAT_MECHANICAL_EXCLUSION = (
    "抗拉", "屈服", "伸长", "收缩", "冲击", "硬度",
    "rm", "rp0.2", "kv2", "hb", "hrc", "hv",
)


def _strong_header_profile(table: TableGrid, text: str) -> str:
    if any(
        marker in text
        for marker in ("允许偏差", "成品分析偏差", "permissible variation", "product analysis")
    ):
        return "admin"
    if any(marker in text for marker in INCLUSION_MARKERS):
        return "inspection"
    if ("sqrt" in text or "√" in text) and ("ksi" in text or "mpa" in text):
        # Fracture-toughness tables (ksi√in / MPa√m) carry a "Thickness"
        # column but are mechanical, not dimensional.
        return "mechanical_properties"
    if re.search(r"bend\s*(?:factor|test|radius)|弯曲(?:试验|性能|半径|压头)", text):
        # Bend tables print a thickness column but the measure is mechanical
        # (AMS "Bend Factor", GB/T "弯曲试验").
        return "mechanical_properties"
    if (
        HEAT_HEADER_RE.search(text)
        and "检验项目" not in text
        and "试验项目" not in text
        and not any(marker in text for marker in HEAT_MECHANICAL_EXCLUSION)
        and not any(marker in text for marker in CHEMICAL_MARKERS)
        and not _has_element_columns(table)
    ):
        # Schedule tables carry grade + temperature/cooling only; leaving them
        # as ``classification`` drops every heat-treatment row.
        return "heat_treatment"
    if (
        ("试验项目" in text or "检验项目" in text or "test item" in text)
        and ("试验方法" in text or "test method" in text)
    ):
        return "inspection"
    inspection_table = any(marker in text for marker in INSPECTION_TABLE_MARKERS)
    if (
        _has_element_columns(table)
        or any(marker in text for marker in CHEMICAL_MARKERS)
        or ("化学成分" in text and not inspection_table)
    ):
        return "chemical_composition"
    if any(marker in text for marker in MECHANICAL_CONCRETE):
        return "mechanical_properties"
    if "property" in text and "value" in text:
        return "mechanical_properties"
    if any(marker in text for marker in INSPECTION_MARKERS):
        return "inspection"
    if "力学性能" in text:
        return "mechanical_properties"
    if any(marker in text for marker in ADMIN_MARKERS) or STANDARD_CODE_RE.search(text):
        return "admin"
    if any(marker in text for marker in CLASSIFICATION_MARKERS if marker != "牌号"):
        return "classification"
    return "unknown"


def _caption_profile(caption: str | None) -> str:
    text = clean_text(caption).lower()
    if not text:
        return "unknown"
    if "化学成分" in text:
        return "chemical_composition"
    if any(marker in text for marker in INSPECTION_MARKERS):
        return "inspection"
    if any(marker in text for marker in MECHANICAL_MARKERS):
        return "mechanical_properties"
    if any(marker in text for marker in DIMENSION_MARKERS):
        return "dimension"
    if any(marker in text for marker in CLASSIFICATION_MARKERS):
        return "classification"
    return "unknown"


def classify_profile(table: TableGrid) -> str:
    caption = clean_text(table.caption).lower()
    if any(
        marker in caption
        for marker in ("对应关系", "换算", "conversion", "correspondence")
    ):
        return "admin"
    if any(
        marker in caption
        for marker in ("允许差", "permissible variation", "product analysis")
    ):
        return "admin"
    if any(marker in caption for marker in INCLUSION_MARKERS):
        return "inspection"
    if len(table.rows) <= table.header_rows:
        return "admin"
    header = header_text(table, include_caption=False)
    if not header.strip():
        return "admin"
    profile = _strong_header_profile(table, header)
    if profile != "unknown":
        return profile
    profile = _caption_profile(table.caption)
    if profile != "unknown":
        return profile
    if _has_element_rows(table):
        # Transposed chemistry tables (grades as columns, elements as rows)
        # often keep "牌号" in the header and would otherwise fall through to
        # classification.
        return "chemical_composition"
    if any(marker in header for marker in DIMENSION_MARKERS):
        return "dimension"
    if any(marker in header for marker in CLASSIFICATION_MARKERS):
        return "classification"
    return "unknown"


def detect_orientation(table: TableGrid) -> str:
    first_header = " ".join(table.header_paths[0]) if table.header_paths else ""
    if "元素" in first_header:
        return "element_rows"
    if _has_element_rows(table):
        return "element_rows"
    if "牌号" in first_header or "级别" in first_header:
        return "grade_rows"

    data_rows = table.rows[table.header_rows :]
    if data_rows:
        first_cells = [clean_text(row[0]) for row in data_rows if row]
        element_hits = sum(1 for cell in first_cells if _is_element_cell(cell))
        if first_cells and element_hits / len(first_cells) >= 0.6 and element_hits >= 3:
            return "element_rows"
        first_data = first_cells[0] if first_cells else ""
        if _is_element_cell(first_data):
            grade_like = sum(
                1
                for path in table.header_paths[1:]
                if any("牌号" in part or "级别" in part for part in path)
            )
            if grade_like:
                return "element_rows"
    return "grade_rows"


def annotate_table(table: TableGrid) -> TableGrid:
    table.profile = classify_profile(table)
    table.orientation = detect_orientation(table)
    if table.profile == "unknown" and table.orientation == "element_rows":
        table.profile = "chemical_composition"
    return table
