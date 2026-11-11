"""Item taxonomy for ItemInventory (M1.7)."""

from __future__ import annotations

import re

from ..tablegrid.normalize import clean_text

FAMILY_LABELS = {
    "tensile": "拉伸",
    "impact": "冲击",
    "stress_rupture": "持久",
    "creep": "蠕变",
    "hardness": "硬度",
    "bend": "弯曲",
    "chemical_composition": "化学成分",
    "metallography": "金相",
    "corrosion": "腐蚀",
    "ndt": "无损检测",
    "dimension": "尺寸",
    "surface": "表面质量",
    "marking": "标识/包装",
    "shear": "剪切",
    "fracture_toughness": "断裂韧性",
    "fatigue": "疲劳",
    "upset": "顶锻",
    "hardenability": "淬透性",
    "inspection": "检验项目",
}

_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("stress_rupture", ("持久", "持久强度", "持久时间", "stress rupture")),
    ("creep", ("蠕变", "蠕变速率", "蠕变极限", "creep")),
    ("impact", ("冲击", "夏比", "kv2", "ku2", "ku5", "akv", "impact", "charpy")),
    ("hardness", ("硬度", "布氏", "洛氏", "维氏", "hbw", "hrc", "hv", "hardness", "brinell", "rockwell", "vickers")),
    ("dimension", ("尺寸", "直径", "厚度", "偏差", "外形", "形状", "切斜度", "弯曲度", "不圆度", "dimension", "diameter", "thickness", "tolerance")),
    ("bend", ("弯曲", "冷弯", "bend")),
    ("chemical_composition", ("化学成分", "元素", "化学分析", "氧含量", "氮含量", "氢含量", "composition", "chemical analysis", "alloying element")),
    ("metallography", ("低倍", "高倍", "晶粒度", "夹杂物", "脱碳层", "显微组织", "微观", "α层", "α相", "断口", "塔形", "发纹", "自由铁素体", "ds类", "grain size", "microstructure", "macrostructure", "inclusion")),
    ("corrosion", ("晶间腐蚀", "盐雾", "腐蚀", "耐湿热", "耐沸水", "耐盐酸", "耐硝酸", "耐酸", "耐碱", "corrosion")),
    ("fracture_toughness", ("断裂韧性", "kic", "jic", "ctod", "fracture toughness")),
    ("fatigue", ("疲劳", "裂纹扩展", "s-n", "fatigue")),
    ("upset", ("顶锻", "upset")),
    ("hardenability", ("淬透性", "hardenability")),
    ("ndt", ("超声", "射线", "荧光", "磁粉", "渗透", "无损", "探伤", "ultrasonic", "radiographic", "penetrant", "magnetic particle")),
    ("surface", ("表面质量", "外观", "表面缺陷", "表面", "膜层", "耐磨", "抗杯突", "surface", "appearance")),
    ("marking", ("标识", "标志", "包装", "marking", "packaging")),
    ("shear", ("剪切", "shear")),
    ("tensile", ("拉伸", "抗拉", "屈服", "伸长率", "收缩率", "rm", "rel", "rp0.2", "tensile", "yield strength", "elongation", "reduction of area", "proof strength")),
]

_TEMPERATURE = (
    ("室温", "室温"),
    ("常温", "室温"),
    ("瞬时", "室温"),
    ("高温", "高温"),
    ("低温", "低温"),
)
_IMPACT_TYPES = (("夏比", "夏比"), ("仪器化", "仪器化"), ("v型", "夏比"), ("u型", "夏比"))
_HARDNESS = (("布氏", "brinell"), ("洛氏", "rockwell"), ("维氏", "vickers"))


def normalize_item(value: str | None) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"\s+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    return text


def split_item_text(value: str) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = re.split(r"[、；;,，/]+", text)
    return [part.strip() for part in parts if part.strip()]


def classify_item(raw: str, facets: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    text = normalize_item(raw)
    result = dict(facets or {})
    for family, keywords in _PATTERNS:
        if any(normalize_item(keyword) in text for keyword in keywords):
            family_value = family
            break
    else:
        family_value = "unknown"

    for keyword, value in _TEMPERATURE:
        if normalize_item(keyword) in text:
            result.setdefault("temperature", value)
    for keyword, value in _IMPACT_TYPES:
        if normalize_item(keyword) in text:
            result.setdefault("impact_type", value)
    for keyword, value in _HARDNESS:
        if normalize_item(keyword) in text:
            result.setdefault("hardness_scale", value)
    return family_value, result


def canonical_item(raw: str, family: str, facets: dict[str, str] | None = None) -> str:
    text = clean_text(raw)
    facets = facets or {}
    if normalize_item(text) in {"", normalize_item(family)}:
        text = FAMILY_LABELS.get(family, family)
    normalized = normalize_item(text)
    for explicit in (
        "室温拉伸",
        "高温拉伸",
        "低温拉伸",
        "低温冲击",
        "夏比冲击",
        "低温夏比冲击",
        "布氏硬度",
        "洛氏硬度",
        "维氏硬度",
    ):
        if normalize_item(explicit) in normalized:
            return explicit

    if family == "tensile":
        temperature = facets.get("temperature")
        return f"{temperature}拉伸" if temperature else "拉伸"
    if family == "impact":
        impact_type = facets.get("impact_type")
        temperature = facets.get("temperature")
        if impact_type == "夏比":
            if temperature:
                return f"{temperature}夏比冲击"
            return "夏比冲击"
        if temperature:
            return f"{temperature}冲击"
        return "冲击"
    if family == "hardness":
        scale = facets.get("hardness_scale")
        if scale == "brinell":
            return "布氏硬度"
        if scale == "rockwell":
            return "洛氏硬度"
        if scale == "vickers":
            return "维氏硬度"
        return "硬度"
    if family == "stress_rupture":
        return "持久"
    if family == "creep":
        return "蠕变"
    if family == "chemical_composition":
        return "化学成分"
    if family == "bend":
        return "弯曲"
    if family == "metallography":
        for keyword, label in (
            ("断口", "断口组织"),
            ("低倍", "低倍组织"),
            ("高倍", "高倍组织"),
            ("晶粒", "晶粒度"),
            ("微观", "显微组织"),
            ("显微", "显微组织"),
        ):
            if keyword in normalized:
                return label
        return text or FAMILY_LABELS.get(family, family)
    if family == "corrosion":
        return text or FAMILY_LABELS.get(family, family)
    if family == "fracture_toughness":
        return "断裂韧性"
    if family == "upset":
        return "顶锻"
    if family == "hardenability":
        return "末端淬透性"
    if family == "fatigue":
        if "裂纹扩展" in normalized:
            return "疲劳裂纹扩展"
        if "疲劳寿命" in normalized or "s-n" in normalized:
            return "疲劳寿命"
        return "疲劳"
    if family == "ndt":
        for keyword, label in (
            ("超声", "超声检测"),
            ("射线", "射线检测"),
            ("荧光", "荧光检测"),
            ("磁粉", "磁粉检测"),
            ("渗透", "渗透检测"),
        ):
            if normalize_item(keyword) in normalized:
                return label
        return text or "无损检测"
    if family == "dimension":
        for keyword in ("切斜度", "弯曲度", "不圆度"):
            if keyword in normalized:
                return keyword
        return text or "尺寸"
    if family == "surface":
        return text or "表面质量"
    if family == "marking":
        if "包装" in normalized:
            return "包装"
        if "标识" in normalized or "标志" in normalized:
            return "产品标识"
        return text or FAMILY_LABELS.get(family, family)
    if family == "shear":
        return text or FAMILY_LABELS.get(family, family)
    return text or FAMILY_LABELS.get(family, family)


IDENTITY_FACETS = {"temperature", "impact_type", "hardness_scale"}

IDENTITY_FACETS_BY_FAMILY = {
    "tensile": ("temperature",),
    "impact": ("temperature", "impact_type"),
    "hardness": ("hardness_scale",),
}

UMBRELLA_TERMS = ("力学性能", "物理性能", "理化性能", "工艺性能", "化学性能", "理化")


def is_umbrella(raw: str) -> bool:
    return any(term in normalize_item(raw) for term in UMBRELLA_TERMS)


def item_key(item_canonical: str, family: str, facets: dict[str, str]) -> tuple:
    dims = IDENTITY_FACETS_BY_FAMILY.get(family, ())
    facet_key = tuple(
        sorted(
            (key, value)
            for key, value in facets.items()
            if key in dims and value
        )
    )
    return normalize_item(item_canonical), family, facet_key
