"""Deterministic English → Chinese translation for extracted requirements.

The sandbox runtime is offline and must stay deterministic, so the translation
uses a metallurgical phrase table instead of a remote model.  It is applied to
the final prose records only; the original sentence is kept in ``raw_original``
and the evidence quote is untouched, so reviewers can still compare with the
source document.
"""

from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LETTER_RE = re.compile(r"[A-Za-z]")

# Whole-sentence templates seen in ASTM/AMS/ISO product specifications.
EXACT_TRANSLATIONS = {
    (
        "the grain size, determined as specified in clause 7, "
        "shall be no coarser than grain size no. 5."
    ): "按第7章规定测定的晶粒度不应粗于5级。",
    "the microscopic structure of the titanium in the annealed condition shall be uniform.": (
        "退火态钛材的显微组织应均匀。"
    ),
    (
        "product shall be uniform in quality and condition, sound, and free of foreign materials."
    ): "产品应质量和状态均匀、致密且无外来物。",
    "average grain size shall be no coarser than astm no. 5.": "平均晶粒度不应粗于ASTM 5级。",
}

# Longest phrases first so "shall be no coarser than" wins over "shall be".
PHRASES: tuple[tuple[str, str], ...] = (
    ("shall be no coarser than", "不应粗于"),
    ("shall be no finer than", "不应细于"),
    ("shall not be less than", "不应小于"),
    ("shall not be greater than", "不应大于"),
    ("shall be free of", "不应有"),
    ("shall be uniform in quality and condition", "质量和状态应均匀"),
    ("shall be uniform", "应均匀"),
    ("shall not exceed", "不得超过"),
    ("shall conform to", "应符合"),
    ("shall be as specified", "应符合规定"),
    ("shall be", "应为"),
    ("shall have", "应具有"),
    ("shall not", "不应"),
    ("must be", "必须为"),
    ("are not permitted", "不允许"),
    ("is not permitted", "不允许"),
    ("not permitted", "不允许"),
    ("is permissible", "允许"),
    ("may be", "可为"),
    ("determined in accordance with", "按…测定"),
    ("determined as specified in", "按…测定"),
    ("in accordance with", "按"),
    ("as specified in", "按"),
    ("at a magnification of", "在…倍放大下"),
    ("when examined at", "在…检验时"),
    ("when examined", "检验时"),
    ("for all products", "对所有产品"),
    ("for other products", "对于其他产品"),
    ("uniform in quality and condition", "质量和状态均匀"),
    ("there will be", ""),
    ("there shall be", ""),
    ("no coarser than", "不粗于"),
    ("no finer than", "不细于"),
    ("no continuous", "无连续"),
    ("no ", "无"),
    ("layer", "层"),
    ("not less than", "不小于"),
    ("not more than", "不大于"),
    ("free of", "无"),
    ("foreign materials", "外来物"),
    ("foreign phases", "外来相"),
    ("foreign phase", "外来相"),
    ("nonmetallic inclusions", "非金属夹杂物"),
    ("non-metallic inclusions", "非金属夹杂物"),
    ("inclusions", "非金属夹杂物"),
    ("inclusion", "非金属夹杂物"),
    ("continuous layer", "连续层"),
    ("alpha case", "α层"),
    ("beta transus", "β转变温度"),
    ("transformation temperature", "相变温度"),
    ("room temperature", "室温"),
    ("elevated temperature", "高温"),
    ("tensile strength", "抗拉强度"),
    ("yield strength", "屈服强度"),
    ("reduction of area", "断面收缩率"),
    ("elongation", "伸长率"),
    ("impact energy", "冲击吸收能量"),
    ("grain boundaries", "晶界"),
    ("grain boundary", "晶界"),
    ("grain flow", "流线"),
    ("grain size", "晶粒度"),
    ("die forgings", "模锻件"),
    ("flash welded rings", "闪光焊环"),
    ("cross-sectional area", "截面积"),
    ("non-recrystallized grains", "未再结晶晶粒"),
    ("general contour", "外形轮廓"),
    ("no evidence of", "无明显"),
    ("reentrant grain flow", "穿流"),
    ("acceptable to purchaser", "需方认可"),
    ("Laves phase", "拉夫斯相"),
    ("acicular phase", "针状相"),
    ("banding", "带状分布"),
    ("average", "平均"),
    ("finer", "更细"),
    ("exhibit", "具有"),
    ("inclusive", "含"),
    ("nominal", "公称"),
    ("results", "结果"),
    ("due to presence of", "由于存在"),
    ("up to", "最多"),
    ("may have", "可有"),
    ("microstructures", "显微组织"),
    ("microstructure", "显微组织"),
    ("hardness", "硬度"),
    ("corrosion resistance", "耐蚀性"),
    ("surface finish", "表面加工"),
    ("surface condition", "表面状态"),
    ("surface defects", "表面缺陷"),
    ("surface defect", "表面缺陷"),
    ("surfaces", "表面"),
    ("surface", "表面"),
    ("defects", "缺陷"),
    ("defect", "缺陷"),
    ("mill product", "轧制产品"),
    ("heat treatment", "热处理"),
    ("solution heat treated", "固溶处理"),
    ("annealed condition", "退火态"),
    ("annealed", "退火"),
    ("aged", "时效"),
    ("welds", "焊缝"),
    ("weld", "焊缝"),
    ("cladding", "覆层"),
    ("base metal", "母材"),
    ("certification report", "质量证明书"),
    ("purchase order", "订货单"),
    ("purchaser", "需方"),
    ("supplier", "供方"),
    ("requirements", "要求"),
    ("requirement", "要求"),
    ("specified", "规定"),
    ("minimum", "最小"),
    ("maximum", "最大"),
    ("shall be reported", "应报告"),
    ("reported", "报告"),
    ("measured", "测量"),
    ("determined", "测定"),
    ("examined", "检验"),
    ("bars", "棒材"),
    ("bar", "棒材"),
    ("plates", "板材"),
    ("plate", "板材"),
    ("sheets", "薄板"),
    ("sheet", "薄板"),
    ("strips", "带材"),
    ("strip", "带材"),
    ("wires", "丝材"),
    ("wire", "丝材"),
    ("tubes", "管材"),
    ("tube", "管材"),
    ("forgings", "锻件"),
    ("forging", "锻件"),
    ("billets", "坯料"),
    ("billet", "坯料"),
    ("materials", "材料"),
    ("material", "材料"),
    ("product", "产品"),
    ("products", "产品"),
    ("uniform", "均匀"),
    ("sound", "致密"),
    ("visible", "可见"),
)


def looks_english(text: str) -> bool:
    value = str(text or "")
    letters = len(LETTER_RE.findall(value))
    if letters < 16:
        return False
    if CJK_RE.search(value):
        return False
    return letters / max(1, len(value.strip())) >= 0.55


def _replace_numbers(text: str) -> str:
    text = re.sub(r"\bTable\s+([A-Z]?\s*\.?\s*\d+(?:\.\d+)*)", r"表\1", text, flags=re.I)
    text = re.sub(r"\bTables\s+([A-Z]?\s*\.?\s*\d+(?:\.\d+)*)", r"表\1", text, flags=re.I)
    text = re.sub(r"\bClause\s+([A-Z]?\s*\.?\s*\d+(?:\.\d+)*)", r"第\1章", text, flags=re.I)
    text = re.sub(r"\bSection\s+([A-Z]?\s*\.?\s*\d+(?:\.\d+)*)", r"第\1节", text, flags=re.I)
    return text


def _tidy(text: str) -> str:
    text = re.sub(r"\s*…\s*", "…", text)
    text = re.sub(r"…(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])…", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([，。；：、）])", r"\1", text)
    text = re.sub(r"([（])\s+", r"\1", text)
    text = text.replace(", ", "，").replace("; ", "；")
    text = re.sub(r"\.\s*$", "。", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"[，。；]{2,}", "，", text)
    return text.strip(" ，,;；")


def translate_requirement(text: str) -> str:
    """Translate one English requirement sentence; Chinese input is unchanged."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw or not looks_english(raw):
        return raw
    exact = EXACT_TRANSLATIONS.get(raw.lower())
    if exact:
        return exact
    result = _replace_numbers(raw)
    result = re.sub(
        r"\bat a magnification of\s+(\d+)\s*[x×]",
        r"在\1倍放大下",
        result,
        flags=re.I,
    )
    result = re.sub(
        r"\bwhen examined at\s+(\d+)\s*[x×](?:\s*magnification)?",
        r"在\1倍检验时",
        result,
        flags=re.I,
    )
    result = re.sub(
        r"\bno\s+(.+?)\s+shall be visible\b",
        r"不应有可见的\1",
        result,
        flags=re.I,
    )
    result = re.sub(r"\bshall be visible\b", "应可见", result, flags=re.I)
    # Protect vocabulary symbols and alloy/standard designations from word rules.
    for english, chinese in PHRASES:
        result = re.sub(
            rf"(?<![A-Za-z]){re.escape(english)}(?![A-Za-z])",
            chinese,
            result,
            flags=re.I,
        )
    result = re.sub(r"\bthe\b", "", result, flags=re.I)
    result = re.sub(r"\band\b", "且", result, flags=re.I)
    result = re.sub(r"\bor\b", "或", result, flags=re.I)
    result = re.sub(r"\bof\b", "的", result, flags=re.I)
    return _tidy(result)
