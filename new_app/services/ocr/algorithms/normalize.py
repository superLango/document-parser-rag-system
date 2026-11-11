"""Deterministic text and unit normalization.

Rewritten from the legacy ``tablegrid/normalize.py`` with only the helpers the
table structure pipeline needs. Value comparison semantics stay in the record
binding layer (M3/M5).
"""

import re

from services.shared.text import clean_text

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

ENGLISH_ELEMENTS = {
    "aluminium": "Al", "aluminum": "Al", "antimony": "Sb", "arsenic": "As",
    "beryllium": "Be", "bismuth": "Bi", "boron": "B", "cadmium": "Cd",
    "calcium": "Ca", "carbon": "C", "cerium": "Ce", "chromium": "Cr",
    "cobalt": "Co", "copper": "Cu", "gallium": "Ga", "germanium": "Ge",
    "hafnium": "Hf", "hydrogen": "H", "indium": "In", "iridium": "Ir",
    "iron": "Fe", "lanthanum": "La", "lead": "Pb", "lithium": "Li",
    "magnesium": "Mg", "manganese": "Mn", "molybdenum": "Mo",
    "nickel": "Ni", "niobium": "Nb", "nitrogen": "N", "osmium": "Os",
    "oxygen": "O", "palladium": "Pd", "phosphorus": "P", "phosphorous": "P",
    "platinum": "Pt", "potassium": "K", "rhenium": "Re", "rhodium": "Rh",
    "ruthenium": "Ru", "selenium": "Se", "silicon": "Si", "silver": "Ag",
    "sodium": "Na", "sulfur": "S", "sulphur": "S", "tantalum": "Ta",
    "tellurium": "Te", "tin": "Sn", "titanium": "Ti", "tungsten": "W",
    "vanadium": "V", "yttrium": "Y", "zinc": "Zn", "zirconium": "Zr",
}

UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?P<unit>%|MPa|GPa|mm|cm|m|HBW?|HRC|HRB|HV|℃|°C|K|g/cm3|kg/m3)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

SUM_ELEMENT_RE = re.compile(r"[+＋]")
ELEMENT_COUNT_RE = re.compile(r"[A-Za-z][a-z]?\s*[+＋]\s*\d")
COMBINED_FORMULA_RE = re.compile(
    r"[（(]\s*([A-Z][a-z]?(?:\s*[+＋]\s*[A-Z][a-z]?)+)\s*[)）]"
)

NUMERIC_GRADES = {
    "201", "202", "301", "302", "303", "304", "305", "309", "310", "314",
    "316", "317", "321", "329", "347", "348", "403", "405", "409", "410",
    "416", "420", "429", "430", "434", "436", "439", "440", "442", "443",
    "444", "446", "630", "631", "632", "633", "634", "635", "660",
}


def parse_unit(raw: str | None) -> str | None:
    text = clean_text(raw)
    if re.search(r"N\s*/\s*mm\s*(?:²|2)", text, re.IGNORECASE):
        return "MPa"
    if re.search(r"MPa\s*[·•.]?\s*[mM]\s*\^?\s*1\s*/\s*2", text):
        return "MPa·m^1/2"
    if re.search(r"J\s*/\s*cm", text):
        return "J/cm²"
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


def looks_like_grade(raw: str | None) -> bool:
    text = clean_text(raw)
    if not text:
        return False
    if text in {"级别", "牌号", "合金牌号", "Grade", "序号"}:
        return False
    if text in NUMERIC_GRADES:
        return True
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


def canonical_element(header: str | None) -> str | None:
    text = clean_text(header)
    if not text:
        return None
    lower = text.lower()
    formula = COMBINED_FORMULA_RE.search(text)
    if formula:
        return re.sub(r"\s+", "", formula.group(1)).replace("＋", "+")
    if SUM_ELEMENT_RE.search(text):
        parts = [part for part in re.split(r"[+＋]", text) if part.strip()]
        if len(parts) >= 3 or ELEMENT_COUNT_RE.search(text):
            return None
    if "总铝" in text or "酸溶铝" in text:
        return "Al"
    for name, symbol in sorted(
        ENGLISH_ELEMENTS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if re.search(rf"(?<![a-z]){name}(?![a-z])", lower):
            return symbol
    for element in sorted(ELEMENTS, key=len, reverse=True):
        if text.startswith(element):
            rest = text[len(element) :]
            if not rest or not rest[0].isalpha() or re.match(r"[a-z](?![a-z])", rest):
                return element
    tokens = re.findall(r"(?<![A-Za-z])([A-Z][a-z]?)(?![A-Za-z])", text)
    for token in tokens:
        if token in ELEMENTS:
            return token
    return None
