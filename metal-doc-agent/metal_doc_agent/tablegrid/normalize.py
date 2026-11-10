"""Deterministic value normalization.

Models should return raw text; code owns number/unit/comparator semantics. This
module is intentionally dependency-free and heavily unit-tested.
"""

from __future__ import annotations

import re
from typing import Any

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# Full element symbol whitelist aligned with the business chemistry items.
# A narrow list used to shrink unknown two-letter symbols to their first
# letter: "Hg" (mercury) became hydrogen and "Na" became nitrogen.
ELEMENTS = {
    "Ac", "Ag", "Al", "Ar", "As", "At", "Au", "B", "Ba", "Be", "Bi", "Bk",
    "Br", "C", "Ca", "Cd", "Ce", "Cf", "Cl", "Cm", "Co", "Cr", "Cs", "Cu",
    "Dy", "Er", "Es", "Eu", "F", "Fe", "Fm", "Fr", "Ga", "Gd", "Ge", "H",
    "He", "Hf", "Hg", "Ho", "I", "In", "Ir", "K", "La", "Li", "Lr", "Lu",
    "Md", "Mg", "Mn", "Mo", "N", "Na", "Nb", "Nd", "Ni", "Np", "O", "Os",
    "P", "Pa", "Pb", "Pd", "Pm", "Po", "Pr", "Pt", "Pu", "Ra", "Rb", "Re",
    "Rh", "Rn", "Ru", "S", "Sb", "Sc", "Se", "Si", "Sm", "Sn", "Sr", "Ta",
    "Tb", "Tc", "Te", "Th", "Ti", "Tl", "Tm", "U", "V", "W", "Y", "Yb",
    "Zn", "Zr",
}

# English element names appear in imported/foreign-language chemistry tables
# (e.g. "Carbon, Max | 0.22"). Only whole tokens are accepted so that
# "environment" does not become nitrogen.
ENGLISH_ELEMENTS = {
    "aluminium": "Al", "aluminum": "Al", "antimony": "Sb", "arsenic": "As",
    "beryllium": "Be", "bismuth": "Bi", "boron": "B", "cadmium": "Cd",
    "calcium": "Ca", "carbon": "C", "cerium": "Ce", "chromium": "Cr",
    "cobalt": "Co", "copper": "Cu", "gallium": "Ga", "germanium": "Ge",
    "hafnium": "Hf", "hydrogen": "H", "indium": "In", "iridium": "Ir",
    "iron": "Fe", "lanthanum": "La", "lead": "Pb", "lithium": "Li",
    "magnesium": "Mg",
    "manganese": "Mn", "molybdenum": "Mo", "nickel": "Ni", "niobium": "Nb",
    "nitrogen": "N", "osmium": "Os", "oxygen": "O", "palladium": "Pd",
    "phosphorus": "P", "phosphorous": "P", "platinum": "Pt",
    "potassium": "K", "rhenium": "Re", "rhodium": "Rh", "ruthenium": "Ru",
    "selenium": "Se",
    "silicon": "Si", "silver": "Ag", "sodium": "Na", "sulfur": "S",
    "sulphur": "S",
    "tantalum": "Ta", "tellurium": "Te", "tin": "Sn", "titanium": "Ti",
    "tungsten": "W", "vanadium": "V", "yttrium": "Y", "zinc": "Zn",
    "zirconium": "Zr",
}

UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?P<unit>%|MPa|GPa|mm|cm|m|HBW?|HRC|HRB|HV|℃|°C|K|g/cm3|kg/m3)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def clean_text(raw: str | None) -> str:
    if raw is None:
        return ""
    text = str(raw).translate(_FULLWIDTH_DIGITS)
    replacements = {
        "％": "%",
        "．": ".",
        "～": "~",
        "≦": "≤",
        "≧": "≥",
        "＜": "<",
        "＞": ">",
        "—": "-",
        "–": "-",
        "－": "-",
        "＋": "+",
        "\u00a0": " ",
        "\u3000": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("$", "")
    text = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\sigma\s*_?\{?([^{}\s]*)\}?", r"σ\1", text)
    text = re.sub(r"\\delta\s*_?\{?([^{}\s]*)\}?", r"δ\1", text)
    text = re.sub(r"\\psi\s*_?\{?([^{}\s]*)\}?", r"ψ\1", text)
    text = re.sub(r"\\phi\s*_?\{?([^{}\s]*)\}?", r"φ\1", text)
    # OCR/LaTeX comparators: \geqslant590MPa -> ≥590MPa (before "\" removal).
    text = text.replace("\\geqslant", "≥").replace("\\leqslant", "≤")
    text = re.sub(r"\\geq(?![a-zA-Z])", "≥", text)
    text = re.sub(r"\\leq(?![a-zA-Z])", "≤", text)
    text = text.replace("{", "").replace("}", "").replace("^", "").replace("_", "")
    text = text.replace("\\", "")
    text = re.sub(r"\s+", " ", text).strip()
    # OCR often inserts a space inside a decimal: 0.000 03 -> 0.00003.
    # Only merge when the left side already has a decimal point; otherwise
    # "表1 304NG" would become "表1304NG" and lose the grade token boundary.
    text = re.sub(r"(\d+\.\d+)\s+(\d+)", r"\1\2", text)
    return text


def parse_number(raw: str | None) -> float | None:
    text = clean_text(raw).replace(",", "")
    match = NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_unit(raw: str | None) -> str | None:
    text = clean_text(raw)
    if re.search(r"N\s*/\s*mm\s*(?:²|2)", text, re.IGNORECASE):
        return "MPa"
    if re.search(r"MPa\s*[·•.]?\s*[mM]\s*\^?\s*1\s*/\s*2", text):
        return "MPa·m^1/2"
    if re.search(r"J\s*/\s*cm", text):
        return "J/cm²"
    # Headers frequently attach the unit to the symbol without a separator,
    # e.g. "抗拉强度RmMPa", "断后伸长率A%", "冲击吸收能量KU1J". The lookbehind
    # in UNIT_RE rejects those, so handle the unambiguous tokens directly.
    if "%" in text or "％" in text:
        return "%"
    if "MPa" in text or "mpa" in text:
        return "MPa"
    if re.search(r"(?<![A-Za-z])J(?![A-Za-z])", text, re.IGNORECASE):
        return "J"
    match = UNIT_RE.search(text)
    if not match:
        return None
    unit = match.group("unit")
    return {"mpa": "MPa", "gpa": "GPa"}.get(unit.lower(), unit)


def normalize_value(raw: str | None, unit: str | None = None) -> dict[str, Any]:
    text = clean_text(raw)
    if not text or text in {"-", "/", "—", "–"}:
        return {"raw": raw or "", "comparator": "na", "text": None, "unit": unit}
    if "余量" in text:
        return {"raw": text, "comparator": "text", "text": "余量", "unit": unit}
    if "提供实测" in text or "实测" in text:
        return {"raw": text, "comparator": "text", "text": "提供实测数据", "unit": unit}
    if "提供数据" in text or text in {"报出", "记录"}:
        # Keep the document wording; "提供数据" is an explicit deliverable
        # requirement, not a missing value.
        return {"raw": text, "comparator": "text", "text": text, "unit": unit}
    if text in {"不规定", "协商确定", "由供需双方协商", "协议"}:
        return {"raw": text, "comparator": "text", "text": text, "unit": unit}

    unit = unit or parse_unit(text)
    lowered = text.lower()

    comparator_patterns = [
        (r"^(?:≤|不大于|不超过|最高|最大|max)\s*(" + NUMBER_RE.pattern + r")", "max"),
        (r"^(?:≥|不小于|不低于|最低|最小|min)\s*(" + NUMBER_RE.pattern + r")", "min"),
        (r"^<\s*(" + NUMBER_RE.pattern + r")", "max"),
        (r"^>\s*(" + NUMBER_RE.pattern + r")", "min"),
    ]
    for pattern, comparator in comparator_patterns:
        match = re.match(pattern, lowered)
        if match:
            try:
                number = float(match.group(1))
            except ValueError:
                continue
            return {
                "raw": text,
                "comparator": comparator,
                "value": number,
                "unit": unit,
            }

    # Ranges: 0.015~0.060, 400~1500, 0.20 至 0.80, 0.20-0.80
    range_match = re.search(
        r"(" + NUMBER_RE.pattern + r")\s*(?:~|至|to|-)\s*(" + NUMBER_RE.pattern + r")",
        lowered,
    )
    if range_match:
        try:
            lower = float(range_match.group(1))
            upper = float(range_match.group(2))
        except ValueError:
            lower = upper = None
        if lower is not None and upper is not None:
            if lower > upper:
                lower, upper = upper, lower
            return {
                "raw": text,
                "comparator": "range",
                "lower": lower,
                "upper": upper,
                "unit": unit,
            }

    number = parse_number(text)
    if number is not None:
        return {"raw": text, "comparator": "eq", "value": number, "unit": unit}

    return {"raw": text, "comparator": "text", "text": text, "unit": unit}


MIN_PROPERTIES = {
    "Rm",
    "Rp0.2",
    "ReH",
    "ReL",
    "A",
    "A50mm",
    "Z",
    "KV2",
    "KU1",
    "KU2",
    "KU5",
    "LE",
    "持久时间",
    "缺口持久时间",
    "Am",
}


def apply_default_comparator(
    parsed: dict[str, Any],
    *,
    property_key: str | None = None,
    header_path: list[str] | None = None,
    chemical: bool = False,
) -> dict[str, Any]:
    """Apply table-level markers or property semantics to bare numeric values.

    OCR frequently drops the ``≥``/``≤`` symbol. The table header marker is the
    strongest evidence; otherwise mechanical strength/ductility values are
    minima and bare chemistry values in impurity blocks are maxima.
    """

    if parsed.get("comparator") != "eq":
        return parsed
    header_text = clean_text(" ".join(header_path or []))
    if "不大于" in header_text or "不超过" in header_text:
        parsed["comparator"] = "max"
    elif "不小于" in header_text or "不低于" in header_text:
        parsed["comparator"] = "min"
    elif property_key in MIN_PROPERTIES:
        parsed["comparator"] = "min"
    elif chemical:
        parsed["comparator"] = "max"
    return parsed


def canonical_property(header: str | None) -> str | None:
    text = clean_text(header).lower().replace(" ", "")
    if not text:
        return None
    # Cross-reference noise ("经淬火回火(见表A.4)后...") used to match the
    # single-letter alias "a" and turned every property into elongation.
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"见?\s*表\s*[a-z0-9.]+", "", text)
    aliases = {
        # English headers (imported specifications / bilingual standards).
        "tensilestrength": "Rm",
        "yieldstrength": "Rp0.2",
        "proofstrength": "Rp0.2",
        "0.2%proofstrength": "Rp0.2",
        "elongation": "A",
        "reductionofarea": "Z",
        "brinellhardness": "HB",
        "rockwellhardness": "HRC",
        "vickershardness": "HV",
        # ASTM/AMS headers often say only "Hardness, max"; Brinell is the
        # default scale, mirroring the Chinese bare "硬度" mapping below.
        "hardness": "HB",
        "impactenergy": "KV2",
        "charpyimpact": "KV2",
        # OCR variants of Rp0.2. "Rm1/2" is a misread Rp1/2; matching "rm"
        # first used to bind the proof-strength column to tensile strength.
        "规定非比例延伸强度": "Rp0.2",
        "规定塑性延伸强度": "Rp0.2",
        "规定残余延伸强度": "Rp0.2",
        "rm1/2": "Rp0.2",
        "rpo2": "Rp0.2",
        "rp02": "Rp0.2",
        "rpo.2": "Rp0.2",
        "缺口试样蠕变断裂时间": "缺口持久时间",
        "缺口持久时间": "缺口持久时间",
        "蠕变断裂后的伸长率": "Am",
        "蠕变断裂时间": "持久时间",
        "持久时间": "持久时间",
        "应力σ": "σ",
        "rm": "Rm",
        "σb": "Rm",
        "σb/mpa": "Rm",
        "抗拉强度": "Rm",
        "抗拉": "Rm",
        "rp0.2": "Rp0.2",
        "rp1": "Rp0.2",
        "σ0.2": "Rp0.2",
        "σ0.2/mpa": "Rp0.2",
        "reh": "ReH",
        "rel": "ReL",
        "屈服强度": "Rp0.2",
        "屈服": "Rp0.2",
        "a50mm": "A50mm",
        "a": "A",
        "δ": "A",
        "δ%": "A",
        "δs": "A",
        "δ5": "A",
        "断后伸长率": "A",
        "伸长率": "A",
        "z": "Z",
        "ψ": "Z",
        "ψ%": "Z",
        "psi": "Z",
        "psi%": "Z",
        "断面收缩率": "Z",
        "收缩率": "Z",
        "kic": "KIC",
        "kv2": "KV2",
        "ku1": "KU1",
        "ku2": "KU2",
        "ku5": "KU5",
        "aku": "KU2",
        "akuj": "KU2",
        "侧向膨胀值": "LE",
        "侧膨胀值": "LE",
        "ak": "KV2",
        "akv": "KV2",
        "冲击": "KV2",
        "冲击功": "KV2",
        "hb": "HB",
        "hbw": "HB",
        "hbs": "HB",
        "布氏硬度": "HB",
        "洛氏硬度": "HRC",
        "维氏硬度": "HV",
        "hrc": "HRC",
        "hrb": "HRB",
        "hv": "HV",
        "e": "E",
        "弹性模量": "E",
        # Bare "硬度" defaults to Brinell; an explicit scale token above wins.
        "硬度": "HB",
    }
    for key, value in aliases.items():
        if len(key) == 1:
            if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", text):
                return value
        elif key in text:
            return value
    return None


SUM_ELEMENT_RE = re.compile(r"[+＋]")
ELEMENT_COUNT_RE = re.compile(r"[A-Za-z][a-z]?\s*[+＋]\s*\d")


def canonical_element(header: str | None) -> str | None:
    text = clean_text(header)
    if not text:
        return None
    lower = text.lower()
    # Sum constraints ("Cr+Cu+Mo+Ni ≤0.70", "Cu+6Sn") do not describe a single
    # element; mapping them to the first symbol duplicated Cr and silently
    # changed the meaning of the limit. A two-element addition ("Ni+Ta") keeps
    # the documented first-element behaviour.
    if SUM_ELEMENT_RE.search(text):
        parts = [part for part in re.split(r"[+＋]", text) if part.strip()]
        if len(parts) >= 3 or ELEMENT_COUNT_RE.search(text):
            return None
    # Total / acid-soluble aluminium labels.
    if "总铝" in text or "酸溶铝" in text:
        return "Al"
    for name, symbol in sorted(
        ENGLISH_ELEMENTS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if re.search(rf"(?<![a-z]){name}(?![a-z])", lower):
            return symbol
    # Longest-prefix match handles OCR artifacts such as "Feb" (Fe + footnote b)
    # and "Als" (acid-soluble Al). Only a single footnote letter may trail the
    # element: "Pcm" is not phosphorus. Two-letter symbols are tried before
    # single letters, so "Hg"/"Na" never shrink to "H"/"N".
    for element in sorted(ELEMENTS, key=len, reverse=True):
        if text.startswith(element):
            rest = text[len(element) :]
            if not rest or not rest[0].isalpha() or re.match(r"[a-z](?![a-z])", rest):
                return element
    # Prefer an exact element-like token, e.g. "Ni+Ta".
    tokens = re.findall(r"(?<![A-Za-z])([A-Z][a-z]?)(?![A-Za-z])", text)
    for token in tokens:
        if token in ELEMENTS:
            return token
    return None


def resolve_element_label_from_notes(label: str, notes: str) -> str | None:
    """Disambiguate ``Na`` (sodium) from ``N a`` (nitrogen + footnote a).

    OCR drops the space, so a two-letter symbol can be one letter plus a
    footnote marker. The table's own notes decide: if they mention the single
    element (``Al:N≥2``) and not the two-letter symbol, the single element is
    the intended row.
    """

    symbol = canonical_element(label)
    if symbol is None or len(symbol) != 2:
        return symbol
    if clean_text(label) != symbol:
        return symbol
    if not notes:
        return symbol
    if re.search(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])", notes):
        return symbol
    trailing = symbol[1]
    # The trailing letter must really be a footnote marker ("a、" in the note
    # block); otherwise "Nb"/"Ni" would both collapse to nitrogen.
    marker = re.search(
        rf"(?:^|[\s、，,；;：:])({re.escape(trailing)})[、，,．.：:）)]",
        notes,
    )
    if marker is None:
        return symbol
    first = symbol[0]
    if re.search(rf"(?<![A-Za-z]){re.escape(first)}(?![A-Za-z])", notes):
        return first
    return symbol


def is_numeric_like(raw: str | None) -> bool:
    text = clean_text(raw)
    if not text or text in {"-", "/", "—", "–"}:
        return False
    if "余量" in text or "实测" in text:
        return True
    return bool(
        re.match(r"^(?:≤|≥|<|>|不大于|不小于)?\s*[-+]?\d", text)
        or re.match(r"^[-+]?\d+(?:\.\d+)?\s*(?:~|至)\s*[-+]?\d", text)
    )


def is_footnote_row(row: list[str]) -> bool:
    non_empty = [clean_text(cell) for cell in row if clean_text(cell)]
    if not non_empty:
        return False
    first = non_empty[0]
    if first.startswith("注") or "注：" in first:
        return True
    if len(non_empty) < 8:
        return False
    longest = max(non_empty, key=len)
    return len(longest) >= 20 and non_empty.count(longest) >= len(non_empty) - 3


NUMERIC_GRADES = {
    # Common 3-digit stainless/heat-resistant grades. Four-digit numbers are
    # aluminium grades; other bare numbers in grade columns are usually values
    # from a shifted row (e.g. 490 in a tensile column).
    "201", "202", "301", "302", "303", "304", "305", "309", "310", "314",
    "316", "317", "321", "329", "347", "348", "403", "405", "409", "410",
    "416", "420", "429", "430", "434", "436", "439", "440", "442", "443",
    "444", "446", "630", "631", "632", "633", "634", "635", "660",
}


def looks_like_grade(raw: str | None) -> bool:
    text = clean_text(raw)
    if not text:
        return False
    if text in {"级别", "牌号", "合金牌号", "Grade", "序号"}:
        return False
    if text in NUMERIC_GRADES:
        return True
    # Temper/condition codes (T6, O) are not material grades. H62 brass and
    # Q235 steel are grades, so H/Q are handled by the patterns below.
    if re.fullmatch(r"(?:T\d{1,3}[A-Z]?|O)", text):
        return False
    return bool(
        re.match(
            r"^(?:[A-Z]{1,4}-?\d{2,}[A-Za-z0-9-]*"
            r"|Cr\d{2,}[A-Za-z0-9-]*"
            r"|\d[A-Z]\d{2,}[A-Z0-9-]*"
            r"|\d{1,3}[A-Z][A-Za-z0-9.-]{2,}"
            r"|\d{2,}[A-Z][A-Za-z0-9-]*"
            r"|(?:H[A-Za-z]{0,2}|Q[A-Za-z]{0,2}|B[A-Za-z]{0,2}|Z[A-Za-z]{0,2})"
            r"\d{2,}(?:[.-]\d+)*[A-Za-z0-9.-]*"
            r"|[A-Z]{1,4}\d+)$",
            text,
        )
        or re.match(r"^(?:普通级|优质级|高纯级|Ⅰ类|Ⅱ类|Ⅲ类|I类|II类|III类)$", text)
    )
