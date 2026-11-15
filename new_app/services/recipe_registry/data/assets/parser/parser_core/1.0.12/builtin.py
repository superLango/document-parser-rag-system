"""Deterministic built-in recipe engine.

Only the Python standard library is used: this file is copied into the
sandbox runtime image and executed with a read-only root filesystem.
"""

from __future__ import annotations

import re
from typing import Any

FOOTNOTE_RE = re.compile(r"[①-⑳]|\[\d+\]|\(\d+\)|（\d+）|\*+$")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
UNIT_RE = re.compile(r"^[A-Za-z%‰°℃Ωμ]+(?:\.[A-Za-z]+)?$")
GRADE_MAX_LEN = 64
PARSER_REVISION = "1.0.1"
_revision_reported = False
# Layout OCR sometimes emits the same table twice (page continuation copies).
_table_fingerprints: set[tuple] = set()
GRADE_SENTENCE_CHARS = ("。", "；", "，", "：", ";")
GRADE_HEADER_MARKERS = (
    "不小于",
    "不大于",
    "牌号",
    "屈服强度",
    "抗拉强度",
    "断后伸长率",
    "伸长率",
    "断面收缩率",
    "冲击",
    "硬度",
    "化学成分",
    "力学性能",
    "试验",
    "单位",
)
ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$")
# Footnote references attached to merged table cells, e.g. "T3 4/ (See 6.4)".
GRADE_FOOTNOTE_RE = re.compile(
    r"[（(]\s*(?:see|note|见|注)\s*(?:note|见|注)?\s*[\d.]*\s*[)）]",
    re.IGNORECASE,
)
GRADE_TAIL_MARKER_RE = re.compile(r"(?:^|\s)\d+/\s*$")
CJK_SPACED_RE = re.compile(r"^[\u4e00-\u9fff]+\s+[\u4e00-\u9fff\s]+$")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# Cells that only mean "not specified"; they must not become properties.
SKIP_CELL_VALUES = {"-", "—", "–", "/", "…", "...", "－", "―"}
# Row-key cells that label a block or a value limit, never a material grade.
PLACEHOLDER_GRADE_RE = re.compile(
    r"^(?:元素|element|含量|基|基体|余|余量|类别|状态|日期|更改人|更改内容(?:及说明)?|"
    r"版次|页码|编号|备注|检测标准|化学成分|主要成分|熔炼分析|成品分析|"
    r"max(?:imum)?|min(?:imum)?|最大(?:值)?|最小(?:值)?|上限|下限|"
    r"规定值|标准|要求|元素含量.*|wt%.*)$",
    re.IGNORECASE,
)
STANDARD_CODE_RE = re.compile(
    r"^(?:GB|GJB|JB|NB|YB|YS|ASTM|ASME|API|ISO|EN|DIN|RCC-M|HAF)\s*/?\s*[A-Z]?\s*\d",
    re.IGNORECASE,
)


def _placeholder_grade(value: str) -> bool:
    """True when a row-key cell labels a block instead of a material grade."""
    text = normalize(strip_footnote(value))
    if not text or text in {"0", "~", "-", "/"}:
        return True
    return bool(PLACEHOLDER_GRADE_RE.fullmatch(text))


def _header_text(header: str) -> str:
    """Readable header path for condition/grade text without joining separators."""
    text = strip_footnote(str(header or ""))
    return re.sub(r"\s*/\s*", " ", text).strip()


def _group_label(header: str) -> str:
    """Return the header group that owns a measure column.

    Multi-group tables repeat the same measure under different temperatures or
    directions (``室温拉伸试验 / Rm``, ``350℃拉伸试验 / Rm``).  The group label is
    the path above the measure column.
    """
    text = str(header or "")
    if " / " not in text:
        return ""
    return strip_footnote(text.rsplit(" / ", 1)[0]).strip()

MEASURE_ALIASES: dict[str, list[str]] = {
    "Rm": ["抗拉强度", "拉伸强度", "σb", "tensile strength", "tensile"],
    "Rp0.2": [
        "屈服强度",
        "规定塑性延伸强度",
        "σ0.2",
        "yield strength",
        "0.2 percent offset",
        "proof strength",
    ],
    "Rp1.0": ["屈服强度", "σ1.0", "proof strength"],
    "ReH": ["上屈服强度", "屈服强度", "upper yield"],
    "ReL": ["下屈服强度", "屈服强度", "lower yield"],
    "A": [
        "断后伸长率",
        "伸长率",
        "延伸率",
        "δs",
        "δ5",
        "elongation",
        "extension",
    ],
    "Z": ["断面收缩率", "收缩率", "ψ", "reduction of area"],
    "KU2": ["冲击吸收能量", "冲击功", "kv2", "kuj", "akuj", "impact energy", "charpy"],
    "KV2": ["冲击吸收能量", "冲击功", "ku2", "akv", "impact energy", "charpy"],
    "KU5": ["冲击吸收能量", "冲击功", "impact energy", "charpy"],
    "HB": ["布氏硬度", "硬度", "hbw", "brinell", "hardness"],
    "HBW": ["布氏硬度", "硬度", "hb", "brinell", "hardness"],
    "HRC": ["洛氏硬度", "rockwell"],
    "HRB": ["洛氏硬度", "rockwell"],
    "HV": ["维氏硬度", "vickers"],
    "E": [
        "弹性模量",
        "杨氏模量",
        "elastic modulus",
        "modulus of elasticity",
        "young's modulus",
    ],
    "侧向膨胀值": ["侧向膨胀值", "侧向膨胀", "lateral expansion"],
    "持久时间": ["持久时间", "断裂时间", "stress rupture", "rupture life", "time to rupture"],
    "持久应力": ["持久应力", "持久强度", "stress rupture strength"],
    "持久温度": ["持久温度", "rupture temperature"],
    "蠕变速率": ["蠕变速率", "creep rate"],
    "蠕变变形": ["蠕变变形", "creep deformation", "creep strain"],
    "KIC": ["断裂韧性", "fracture toughness"],
    "CEV": ["碳当量", "carbon equivalent"],
    "Pcm": ["焊接裂纹敏感性", "crack sensitivity"],
    "Fe": ["铁", "iron"],
    "Si": ["硅", "silicon"],
    "Mn": ["锰", "manganese"],
    "P": ["磷", "phosphorus"],
    "S": ["硫", "sulfur", "sulphur"],
    "Ni": ["镍", "nickel"],
    "Cr": ["铬", "chromium"],
    "Mo": ["钼", "molybdenum"],
    "Cu": ["铜", "copper"],
    "Al": ["铝", "aluminum", "aluminium"],
    "Ti": ["钛", "titanium"],
    "V": ["钒", "vanadium"],
    "Nb": ["铌", "niobium", "columbium"],
    "N": ["氮", "nitrogen"],
    "O": ["氧", "oxygen"],
    "H": ["氢", "hydrogen"],
    "B": ["硼", "boron"],
    "W": ["钨", "tungsten"],
    "Co": ["钴", "cobalt"],
    "Zr": ["锆", "zirconium"],
    "Ta": ["钽", "tantalum"],
    "Re": ["铼", "rhenium"],
    "Sn": ["锡", "tin"],
    "As": ["砷", "arsenic"],
    "Pb": ["铅", "lead"],
    "Sb": ["锑", "antimony"],
    "Bi": ["铋", "bismuth"],
    "Ca": ["钙", "calcium"],
    "Mg": ["镁", "magnesium"],
    "Zn": ["锌", "zinc"],
    "Ce": ["铈", "cerium"],
    "La": ["镧", "lanthanum"],
    "Y": ["钇", "yttrium"],
    "Nd": ["钕", "neodymium"],
    "Se": ["硒", "selenium"],
    "Te": ["碲", "tellurium"],
    "Ag": ["银", "silver"],
}

# Header symbols are authoritative: a column labelled KV2 must stay KV2 even
# when the recipe binds KU2 (and HBW must not be relabelled HB, etc.).
SYMBOL_CANON: dict[str, str] = {name.lower(): name for name in MEASURE_ALIASES}
SYMBOL_CANON.update(
    {
        "rel": "ReL",
        "reh": "ReH",
        "σb": "Rm",
        "σ0.2": "Rp0.2",
        "σ1.0": "Rp1.0",
        "δs": "A",
        "δ5": "A",
        "ψ": "Z",
    }
)
# ``Re`` is rhenium in chemistry but yield strength in mechanical tables; the
# recipe binding decides which one applies.
SYMBOL_CANON.pop("re", None)
SYMBOL_RE = re.compile(r"[A-Za-z]+(?:[0-9]+(?:\.[0-9]+)?)?")

ELEMENT_SYMBOLS = {
    "H", "B", "C", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S", "K",
    "Ca", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "As", "Se", "Sr", "Y", "Zr", "Nb", "Mo", "Ag", "Cd", "In", "Sn", "Sb",
    "Te", "Ba", "La", "Ce", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er",
    "Yb", "Ta", "W", "Re", "Pb", "Bi", "Th", "U",
}

CONDITION_TOKENS = (
    "规格",
    "尺寸",
    "方向",
    "试验温度",
    "温度",
    "状态",
    "热处理",
    "取样",
    "厚度",
    "交货",
    "交货状态",
    "热处理状态",
    "试样",
    "试样状态",
    "取样方向",
    "部位",
    "公称",
    "类型",
    "壁厚",
    "外径",
    "产品形式",
    "表面状态",
    "轧制",
    "冷轧",
    "热轧",
    "固溶",
    "时效",
    "退火",
    "正火",
    "回火",
    "淬火",
    "thickness",
    "orientation",
    "diameter",
    "width",
    "length",
    "temperature",
    "specimen",
)
DIMENSION_HEADER_MARKERS = (
    "厚度",
    "thickness",
    "规格",
    "尺寸",
    "直径",
    "diameter",
    "宽度",
    "width",
    "长度",
    "length",
    "外径",
)
DEFAULT_ROW_KEY = (
    "牌号",
    "钢号",
    "grade",
    "材料牌号",
    "常用材料",
    "钢种",
    "材料",
    "合金牌号",
    "材料名称",
    "级别",
    "钢级",
    "质量等级",
    "统一数字代号",
    "新牌号",
    "原牌号",
    "锻件种类",
    "temper",
    "element",
    "alloy",
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def strip_footnote(text: str) -> str:
    return FOOTNOTE_RE.sub("", (text or "").strip()).strip()


def _header_columns(table: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    rows = table.get("rows") or []
    header_rows = int(table.get("header_rows") or 1)
    paths = table.get("header_paths") or []
    n_cols = int(table.get("n_cols") or 0)

    if paths:
        headers = [" / ".join(part for part in p if part) for p in paths]
        # TableGrid.rows keeps the header rows; header_paths describes them.
        data = rows[header_rows:] if header_rows > 0 else rows
        return headers, data
    if not rows:
        return [], []
    header_rows = max(1, min(header_rows, len(rows)))
    width = n_cols or max(len(r) for r in rows)
    headers = []
    for col in range(width):
        parts = []
        for row in rows[:header_rows]:
            if col < len(row) and row[col] and row[col] not in parts:
                parts.append(row[col])
        headers.append(" / ".join(parts))
    data = rows[header_rows:]
    return headers, data


def _iter_blocks(table: dict[str, Any]):
    """Yield (block_id, headers, data_rows) for a table or its blocks."""
    headers, data = _header_columns(table)
    if headers and data:
        yield table.get("block_id") or "", headers, data
        return
    for block in table.get("blocks") or []:
        block_table = {
            "rows": block.get("rows") or [],
            "header_rows": block.get("header_rows") or 1,
            "header_paths": block.get("header_paths") or [],
            "n_cols": len(block.get("rows", [[]])[0]) if block.get("rows") else 0,
        }
        block_headers, block_data = _header_columns(block_table)
        if block_headers:
            yield block.get("block_id") or "", block_headers, block_data


def _is_dimension_header(header: str) -> bool:
    text = normalize(header)
    return any(marker in text for marker in DIMENSION_HEADER_MARKERS)


HEADER_MARK_STRIP = "≤≥<>=±≤≥*＊"
# Symbols that OCR commonly splits with spaces ("R m", "KU 2", "HB W").
SPACED_SYMBOLS = {
    "rm",
    "rp0.2",
    "rp1.0",
    "rel",
    "reh",
    "ku2",
    "kv2",
    "ku5",
    "hbw",
    "hbs",
    "hrc",
    "hrb",
    "hv",
}


def _header_parts(header: str) -> list[str]:
    """Split a header into comparable tokens.

    Limit markers are part of the printed header (``P≤``, ``Cu≤``) but not part
    of the measure name, so they are stripped before matching.
    """
    parts = []
    for part in re.split(r"[/\s()（）,，;；%％]+", normalize(header)):
        token = part.strip(HEADER_MARK_STRIP)
        if token:
            parts.append(token)
    return parts


def _alias_matches(header: str, token: str) -> bool:
    """Short ASCII symbols must match a whole header component.

    ``hb`` must not match ``hbw`` and ``c`` must not match ``cr``; longer
    English phrases (``yield strength``) keep substring matching. Chinese
    aliases also keep substring matching because headers add qualifiers.
    """
    if CJK_RE.search(token):
        # Chinese qualifiers must match inside longer labels: "方向" in
        # "试样方向", "磷" in "磷含量".
        return token in header
    if not re.fullmatch(r"[a-z0-9.]+", token):
        # Greek symbols (σb, σ0.2, δ5) are printed as a prefix of the unit.
        if token in header:
            return True
    if len(token) <= 8:
        if token in _header_parts(header):
            return True
    else:
        return token in header
    if token in SPACED_SYMBOLS:
        # OCR splits printed symbols: "R m", "KU 2", "R eL (R ) p0.2".
        compact = re.sub(r"[()（）]", "", header)
        if compact.startswith(token):
            return True
        if any(char.isdigit() for char in token) and token in compact:
            return True
    return False


def _find_column(
    headers: list[str],
    aliases: list[str],
    used: set[int],
    *,
    skip_group: bool = False,
) -> int | None:
    def scoped(header: str) -> str:
        # Multi-level headers repeat a group heading above each measure
        # ("拉伸性能 / 抗拉强度Rm", "硬度 / 冲击吸收能量KV2"); the heading must
        # not satisfy an unrelated alias such as "硬度".
        if skip_group and " / " in header:
            head, rest = header.split(" / ", 1)
            if CJK_RE.search(head) and rest.strip() and not UNIT_RE.match(rest.strip()):
                return rest
        return header

    normalized = [normalize(scoped(h)) for h in headers]
    for alias in aliases:
        token = normalize(alias)
        if not token:
            continue
        for idx, header in enumerate(normalized):
            if idx in used:
                continue
            if _alias_matches(header, token):
                return idx
    return None


def _detect_measure(header: str, bound: str) -> str:
    """Return the symbol printed in the header when it is a known measure."""
    text = normalize(header)
    # Drop unit tails so ``抗拉强度/N/mm2`` is not mistaken for nitrogen.
    text = re.sub(r"(?:n/mm2|n/mm²|j/cm2|j/cm²|mpa|gpa)", "", text)
    if "/" in text:
        text = text.rsplit("/", 1)[0]
    if bound in {"Rp0.2", "ReL", "ReH"} and "p0.2" in text:
        # Headers such as ``ReL (Rp0.2)`` print both symbols; the proof
        # strength is the canonical measure (matches the legacy baseline).
        return "Rp0.2"
    has_cjk = bool(CJK_RE.search(text))
    parts = set(_header_parts(text))
    for symbol in SYMBOL_RE.findall(text):
        canonical = SYMBOL_CANON.get(symbol)
        if not canonical:
            continue
        if len(symbol) == 1 and (has_cjk or symbol not in parts):
            # Footnote markers such as "拉伸试验b" are not measures.
            continue
        return "HB" if canonical in {"HBW", "HBS"} else canonical
    return "HB" if bound in {"HBW", "HBS"} else bound


UNIT_WORDS = (
    ("n/mm2", "N/mm2"),
    ("n/mm²", "N/mm2"),
    ("mpa", "MPa"),
    ("ksi", "ksi"),
    ("j/cm2", "J/cm2"),
    ("j/cm²", "J/cm2"),
    ("percent", "%"),
    ("%", "%"),
    ("hbw", "HBW"),
    ("hb", "HB"),
    ("hrc", "HRC"),
    ("hrb", "HRB"),
    ("hv", "HV"),
)


def _extract_unit(header: str, explicit: str | None) -> str:
    if "/" in header:
        tail = header.rsplit("/", 1)[-1].strip()
        if tail and len(tail) <= 12 and UNIT_RE.match(tail):
            return tail
    lowered = normalize(header)
    for token, unit in UNIT_WORDS:
        if token in lowered:
            return unit
    return explicit.strip() if explicit else ""


def _parse_value(cell: str, strip_marks: bool) -> dict[str, Any] | None:
    raw = strip_footnote(cell) if strip_marks else (cell or "").strip()
    if not raw:
        return None
    match = NUMBER_RE.search(raw)
    value = float(match.group()) if match else None
    operator = None
    for candidate in ("≥", "≤", ">", "<", "～", "~"):
        if candidate in raw:
            operator = candidate
            break
    return {"value": value, "raw": raw, "operator": operator}


def _measure_aliases(measure: str) -> list[str]:
    aliases = list(MEASURE_ALIASES.get(measure, []))
    # Single-letter element symbols (C, P, S, N, ...) must be searchable too.
    aliases.insert(0, measure)
    return list(dict.fromkeys(aliases))


def _grade_valid(grade: str, *, allow_numeric: bool = False) -> bool:
    if not grade or len(grade) > GRADE_MAX_LEN:
        return False
    if len(grade) > 10 and CJK_RE.search(grade):
        # Footnote sentences ("SMLS,非冷扩径[见API Spec 5L...]") are not grades.
        return False
    if STANDARD_CODE_RE.match(grade):
        return False
    if any(mark in grade for mark in GRADE_SENTENCE_CHARS):
        return False
    if grade.startswith(("注", "说明", "备注")):
        return False
    if any(marker in grade for marker in GRADE_HEADER_MARKERS):
        return False
    if CJK_SPACED_RE.fullmatch(grade):
        # OCR-spaced section headers such as "结 梅 钢" / "不 锈 钢 及 耐 热 钢".
        return False
    if grade.endswith(("-", "—", "/")):
        # Footnote fragments such as "F1472-".
        return False
    if " + " in grade:
        # Combined document titles such as "ISO 5832-3 + ASTM F136-13".
        return False
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", grade):
        # Numeric grades (45, 20, 65Mn style) are valid only when the column
        # was explicitly identified as the row key.
        return allow_numeric and bool(re.fullmatch(r"\d{1,6}", grade))
    return True


GRADE_SPLIT_RE = re.compile(r"[、,，;；\s]+")
NUMERIC_GRADE_RE = re.compile(r"\d{1,4}")


def _grade_like(piece: str) -> bool:
    if not piece or len(piece) > 30:
        return False
    if NUMERIC_GRADE_RE.fullmatch(piece):
        return True
    if not re.search(r"\d", piece):
        return False
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", piece):
        return False
    return not any(ch in piece for ch in "。；，：;~≤≥<>%％")


def _split_grades(grade: str) -> list[str]:
    """Split merged grade cells that use explicit separators.

    Concatenated grades without separators are intentionally left untouched:
    splitting them would corrupt legitimate stainless grades such as
    ``022Cr17Ni12Mo2``.
    """
    text = GRADE_FOOTNOTE_RE.sub("", grade)
    text = GRADE_TAIL_MARKER_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = [part.strip() for part in GRADE_SPLIT_RE.split(text) if part.strip()]
    if len(parts) <= 1:
        return [text] if text else []
    valid = [part for part in parts if _grade_like(part)]
    return valid if len(valid) > 1 else [text]


def _condition_key(conditions: dict[str, str]) -> str:
    return "|".join(sorted(normalize(value) for value in conditions.values() if value))


def _is_footnote_row(cells: list[str]) -> bool:
    text = "".join(cells).strip()
    if not text:
        return True
    return text.startswith(("注", "注：", "说明", "备注")) or bool(
        re.match(r"^[①-⑳]", text)
    )


def _element_symbol(text: str) -> str:
    cleaned = strip_footnote(text).strip()
    if ELEMENT_RE.fullmatch(cleaned) and cleaned in ELEMENT_SYMBOLS:
        return cleaned
    base = re.sub(r"\(.*?\)|（.*?）|[%％]", "", cleaned).strip()
    if ELEMENT_RE.fullmatch(base) and base in ELEMENT_SYMBOLS:
        return base
    tokens = re.findall(r"[A-Z][a-z]?", base)
    if len(tokens) == 1 and tokens[0] in ELEMENT_SYMBOLS:
        return tokens[0]
    return ""


def _nonvalue_label(raw: str) -> bool:
    """A cell that repeats an element/header label instead of holding a value."""
    text = str(raw or "").strip()
    return bool(_element_symbol(text)) or "元素" in text


def _prose_cell(raw: str, parsed: dict[str, Any]) -> bool:
    """Footnote prose accidentally aligned with a measure column."""
    text = str(raw or "").strip()
    if parsed.get("value") is not None:
        return False
    return _nonvalue_label(text) or (len(text) > 24 and bool(CJK_RE.search(text)))


def _grade_from_header(header: str) -> str:
    text = strip_footnote(header)
    text = text.split("/")[-1].strip() or text
    text = re.sub(r"^(牌号|钢号|grade|材料牌号)\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _parse_element_table(
    table: dict[str, Any],
    *,
    table_id: str,
    page_no: int,
    profile: str,
    recipe_id: str,
    recipe_version: str,
    strip_marks: bool,
    units: list[str],
    binding_units: dict[str, str],
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Parse chemical tables that are organised by element instead of by grade.

    Two layouts are supported: element labels in the first column (values per
    condition column) and element labels in the header (values per row group).
    """
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None

    for block_id, headers, data_rows in _iter_blocks(table):
        row_total += len(data_rows)
        if not headers or not data_rows:
            continue

        element_row_layout = any(
            _element_symbol(row[0])
            for row in data_rows[:8]
            if row and str(row[0] or "").strip()
        )
        if element_row_layout:
            for col in range(1, len(headers)):
                condition = _grade_from_header(headers[col])
                if not condition or _placeholder_grade(condition):
                    # Keep the printed block label (e.g. "元素含量，wt.% Min").
                    condition = _header_text(headers[col]) or f"col{col + 1}"
                properties: dict[str, Any] = {}
                cells: dict[str, str] = {}
                for row in data_rows:
                    symbol = _element_symbol(row[0] if row else "")
                    if not symbol or col >= len(row):
                        continue
                    parsed = _parse_value(row[col], strip_marks)
                    if parsed is None:
                        continue
                    raw_value = str(parsed.get("raw") or "").strip()
                    if raw_value in SKIP_CELL_VALUES:
                        continue
                    if _prose_cell(raw_value, parsed):
                        continue
                    unit = _extract_unit(
                        headers[col], explicit_unit
                    ) or binding_units.get(symbol, "")
                    if not unit and profile == "chemical_composition":
                        unit = "%"
                    parsed["unit"] = unit
                    parsed["column"] = headers[col]
                    properties[symbol] = parsed
                    cells[symbol] = row[col]
                if not properties:
                    continue
                record_id = f"{table_id}-C{col + 1}"
                records.append(
                    {
                        "record_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": col - 1,
                        "recipe_id": recipe_id,
                        "recipe_version": recipe_version,
                        "profile": profile,
                        "grade": "~",
                        "conditions": {"依据": condition},
                        "condition_key": normalize(condition),
                        "properties": properties,
                        "evidence_refs": [record_id],
                        "source": {
                            "table_id": table_id,
                            "block_id": block_id,
                            "page_no": page_no,
                            "row_index": col - 1,
                        },
                    }
                )
                evidence.append(
                    {
                        "evidence_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": col - 1,
                        "raw_row": list(cells.values()),
                        "cells": cells,
                    }
                )
            continue

        element_cols = [
            (idx, _element_symbol(header)) for idx, header in enumerate(headers[1:], start=1)
        ]
        element_cols = [(idx, symbol) for idx, symbol in element_cols if symbol]
        if not element_cols:
            diagnostics.append(
                {
                    "code": "ELEMENT_COLUMNS_NOT_FOUND",
                    "message": f"table {table_id} has no element labels",
                    "severity": "warning",
                    "detail": {"table_id": table_id, "headers": headers},
                }
            )
            continue
        for row_index, row in enumerate(data_rows):
            if _is_footnote_row(row):
                continue
            label = strip_footnote(row[0] if row else "") or "含量"
            if not _grade_valid(label):
                continue
            properties = {}
            cells = {}
            for col, symbol in element_cols:
                if col >= len(row):
                    continue
                parsed = _parse_value(row[col], strip_marks)
                if parsed is None:
                    continue
                raw_value = str(parsed.get("raw") or "").strip()
                if raw_value in SKIP_CELL_VALUES:
                    continue
                if _prose_cell(raw_value, parsed):
                    continue
                unit = _extract_unit(
                    headers[col], explicit_unit
                ) or binding_units.get(symbol, "")
                if not unit and profile == "chemical_composition":
                    unit = "%"
                parsed["unit"] = unit
                parsed["column"] = headers[col]
                properties[symbol] = parsed
                cells[symbol] = row[col]
            if not properties:
                continue
            record_id = f"{table_id}-R{row_index + 1}"
            records.append(
                {
                    "record_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "profile": profile,
                    "grade": "~",
                    "conditions": {"依据": label},
                    "condition_key": normalize(label),
                    "properties": properties,
                    "evidence_refs": [record_id],
                    "source": {
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                    },
                }
            )
            evidence.append(
                {
                    "evidence_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "raw_row": list(row),
                    "cells": cells,
                }
            )

    if not records:
        diagnostics.append(
            {
                "code": "NO_RECORDS",
                "message": f"table {table_id} produced no records",
                "severity": "warning",
                "detail": {"table_id": table_id},
            }
        )
    summary = {
        "table_id": table_id,
        "page_no": page_no,
        "profile": profile,
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "rows": row_total,
        "records": len(records),
    }
    return records, evidence, summary


def _parse_chemical_columns(
    table: dict[str, Any],
    *,
    table_id: str,
    page_no: int,
    profile: str,
    recipe_id: str,
    recipe_version: str,
    strip_marks: bool,
    units: list[str],
    binding_units: dict[str, str],
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Fallback for grade-less chemical tables (element columns, one data row)."""
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None
    for block_id, headers, data_rows in _iter_blocks(table):
        row_total += len(data_rows)
        element_cols = [
            (idx, symbol)
            for idx, header in enumerate(headers)
            if (symbol := _element_symbol(header))
        ]
        if len(element_cols) < 3:
            continue
        for row_index, row in enumerate(data_rows):
            if _is_footnote_row(row):
                continue
            properties: dict[str, Any] = {}
            cells: dict[str, str] = {}
            for col, symbol in element_cols:
                if col >= len(row):
                    continue
                parsed = _parse_value(row[col], strip_marks)
                if parsed is None:
                    continue
                raw_value = str(parsed.get("raw") or "").strip()
                if raw_value in SKIP_CELL_VALUES:
                    continue
                if _prose_cell(raw_value, parsed):
                    continue
                unit = _extract_unit(
                    headers[col], explicit_unit
                ) or binding_units.get(symbol, "")
                if not unit and profile == "chemical_composition":
                    unit = "%"
                parsed["unit"] = unit
                parsed["column"] = headers[col]
                properties[symbol] = parsed
                cells[symbol] = row[col]
            if len(properties) < 2:
                continue
            record_id = f"{table_id}-R{row_index + 1}"
            records.append(
                {
                    "record_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "profile": profile,
                    "grade": "~",
                    "conditions": {},
                    "condition_key": "",
                    "properties": properties,
                    "evidence_refs": [record_id],
                    "source": {
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                    },
                }
            )
            evidence.append(
                {
                    "evidence_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "raw_row": list(row),
                    "cells": cells,
                }
            )
    if not records:
        diagnostics.append(
            {
                "code": "NO_RECORDS",
                "message": f"table {table_id} produced no records",
                "severity": "warning",
                "detail": {"table_id": table_id},
            }
        )
    summary = {
        "table_id": table_id,
        "page_no": page_no,
        "profile": profile,
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "rows": row_total,
        "records": len(records),
    }
    return records, evidence, summary


def parse_table(
    table: dict[str, Any],
    manifest: dict[str, Any] | None,
    assignment: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    table_id = str(table.get("table_id") or "unknown")
    page_no = int(table.get("page_no") or 0)
    global _revision_reported
    fingerprint = (
        str(table.get("caption") or ""),
        tuple(tuple(str(cell) for cell in row) for row in (table.get("rows") or [])),
        tuple(
            tuple(str(part) for part in path)
            for path in (table.get("header_paths") or [])
        ),
    )
    if fingerprint in _table_fingerprints:
        diagnostics.append(
            {
                "code": "DUPLICATE_TABLE",
                "message": f"table {table_id} duplicates an earlier table",
                "severity": "info",
                "detail": {"table_id": table_id},
            }
        )
        return [], [], {
            "table_id": table_id,
            "page_no": page_no,
            "profile": str((manifest or {}).get("profile") or table.get("profile") or "unknown"),
            "recipe_id": str(
                (assignment or {}).get("recipe_id") or (manifest or {}).get("recipe_id") or ""
            ),
            "recipe_version": str(
                (assignment or {}).get("version") or (manifest or {}).get("version") or ""
            ),
            "rows": len(table.get("rows") or []),
            "records": 0,
        }
    _table_fingerprints.add(fingerprint)
    if not _revision_reported:
        diagnostics.append(
            {
                "code": "PARSER_BUNDLE",
                "message": f"parser revision {PARSER_REVISION}",
                "severity": "info",
                "detail": {"revision": PARSER_REVISION},
            }
        )
        _revision_reported = True
    recipe_id = str((assignment or {}).get("recipe_id") or (manifest or {}).get("recipe_id") or "")
    recipe_version = str(
        (assignment or {}).get("version") or (manifest or {}).get("version") or ""
    )
    profile = str((manifest or {}).get("profile") or table.get("profile") or "unknown")
    bindings = (manifest or {}).get("bindings") or {}
    binding_units = {
        str(name): str((config or {}).get("unit") or "")
        for name, config in (bindings.get("measures") or {}).items()
        if isinstance(config, dict)
    }
    rules = (manifest or {}).get("rules") or {}
    strip_marks = bool(rules.get("strip_footnote_marks", True))
    units = table.get("units") or []
    try:  # imported as a package (tests)
        from .strategies import nonrecord_reason
    except ImportError:  # flat runtime image (/engine)
        from strategies import nonrecord_reason

    reason = nonrecord_reason(table)
    if reason:
        diagnostics.append(
            {
                "code": "NONRECORD_TABLE",
                "message": f"table {table_id} is not a record table: {reason}",
                "severity": "info",
                "detail": {"table_id": table_id, "reason": reason},
            }
        )
        return [], [], {
            "table_id": table_id,
            "page_no": page_no,
            "profile": profile,
            "recipe_id": recipe_id,
            "recipe_version": recipe_version,
            "rows": len(table.get("rows") or []),
            "records": 0,
        }
    if rules.get("transposed"):
        return _parse_element_table(
            table,
            table_id=table_id,
            page_no=page_no,
            profile=profile,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            strip_marks=strip_marks,
            units=units,
            binding_units=binding_units,
            diagnostics=diagnostics,
        )

    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    record_count = 0
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None

    for block_id, headers, data_rows in _iter_blocks(table):
        used: set[int] = set()
        row_key_tokens = list(
            dict.fromkeys([*(bindings.get("row_key") or []), *DEFAULT_ROW_KEY])
        )
        key_col = _find_column(headers, row_key_tokens, set())
        key_found = key_col is not None
        if key_col is None:
            diagnostics.append(
                {
                    "code": "ROW_KEY_NOT_FOUND",
                    "message": f"table {table_id} has no row-key column",
                    "severity": "warning",
                    "detail": {"table_id": table_id, "headers": headers},
                }
            )
            key_col = 0
        used.add(key_col)

        measure_cols: dict[str, int] = {}
        pending: list[str] = []
        # Pass 1: exact symbols win, so HB never steals HBW (and C never Cr).
        for measure in (bindings.get("measures") or {}):
            col = _find_column(headers, [str(measure)], used, skip_group=True)
            if col is None:
                col = _find_column(headers, [str(measure)], used)
            if col is None:
                pending.append(str(measure))
                continue
            used.add(col)
            measure_cols[str(measure)] = col
        # Pass 2: alias matching for columns without an explicit symbol.
        for measure in pending:
            col = _find_column(headers, _measure_aliases(measure), used, skip_group=True)
            if col is None:
                col = _find_column(headers, _measure_aliases(measure), used)
            if col is None:
                diagnostics.append(
                    {
                        "code": "MEASURE_COLUMN_MISSING",
                        "message": f"measure {measure} not found in table {table_id}",
                        "severity": "warning",
                        "detail": {"table_id": table_id, "measure": str(measure)},
                    }
                )
                continue
            used.add(col)
            measure_cols[measure] = col

        # Repeated measures under different header groups (room/high temp,
        # direction, specimen size) become additional records, not lost columns.
        extra_groups: dict[str, list[tuple[str, int]]] = {}
        primary_labels = {
            _group_label(headers[col]) for col in measure_cols.values() if col < len(headers)
        }
        for measure, primary_col in list(measure_cols.items()):
            probe = set(used)
            probe.add(primary_col)
            while True:
                col = _find_column(headers, [str(measure)], probe, skip_group=True)
                if col is None:
                    col = _find_column(
                        headers, _measure_aliases(measure), probe, skip_group=True
                    )
                if col is None:
                    break
                probe.add(col)
                label = _group_label(headers[col])
                if label and label not in primary_labels:
                    extra_groups.setdefault(label, []).append((measure, col))

        condition_cols: dict[str, int] = {}
        # Longest label wins so "交货状态" is not reduced to "状态".
        condition_tokens = sorted(
            dict.fromkeys([*(bindings.get("conditions") or []), *CONDITION_TOKENS]),
            key=lambda token: -len(str(token)),
        )
        for token in condition_tokens:
            col = _find_column(headers, [str(token)], used)
            if col is not None:
                used.add(col)
                condition_cols[str(token)] = col

        for row_index, row in enumerate(data_rows):
            row_total += 1
            if _is_footnote_row(row):
                continue
            grade_cell = row[key_col] if key_col < len(row) else ""
            raw_grade = strip_footnote(grade_cell) if strip_marks else (grade_cell or "").strip()
            if _placeholder_grade(raw_grade):
                diagnostics.append(
                    {
                        "code": "ROW_KEY_PLACEHOLDER",
                        "message": "row skipped: key cell is a block label, not a grade",
                        "severity": "info",
                        "detail": {"table_id": table_id, "row_index": row_index},
                    }
                )
                continue
            dimension_condition = None
            if not key_found and _is_dimension_header(headers[key_col]):
                # A dimension/size column is a condition, not a grade.  This
                # happens in tables such as AMS 4050 Table 2B where the first
                # column is "Nominal Thickness" and no temper/grade column
                # exists.
                dimension_condition = raw_grade
                grades = ["~"] if dimension_condition else []
            else:
                grades = [
                    item
                    for item in _split_grades(raw_grade)
                    if _grade_valid(item, allow_numeric=key_found)
                ]
            if not grades:
                diagnostics.append(
                    {
                        "code": "ROW_SKIPPED",
                        "message": "row skipped: empty or invalid row key",
                        "severity": "info",
                        "detail": {"table_id": table_id, "row_index": row_index},
                    }
                )
                continue

            conditions = {
                name: strip_footnote(row[col])
                for name, col in sorted(condition_cols.items())
                if col < len(row) and strip_footnote(row[col])
            }
            if dimension_condition:
                conditions["规格"] = dimension_condition
            properties: dict[str, Any] = {}
            for measure, col in sorted(measure_cols.items()):
                cell = row[col] if col < len(row) else ""
                parsed = _parse_value(cell, strip_marks)
                if parsed is None:
                    continue
                raw_value = str(parsed.get("raw") or "").strip()
                if raw_value in SKIP_CELL_VALUES or _prose_cell(raw_value, parsed):
                    continue
                if (
                    profile == "chemical_composition"
                    and parsed.get("value") is not None
                    and float(parsed["value"]) < 0
                ):
                    # Composition tolerances are not composition values.
                    continue
                parsed["unit"] = _extract_unit(
                    headers[col], explicit_unit
                ) or binding_units.get(measure, "")
                parsed["column"] = headers[col]
                # Trust the symbol printed in the header (KV2 vs KU2, HBW vs HB).
                properties[_detect_measure(headers[col], measure)] = parsed

            if not properties:
                diagnostics.append(
                    {
                        "code": "EMPTY_RECORD_SKIPPED",
                        "message": "row produced no bound measures",
                        "severity": "info",
                        "detail": {"table_id": table_id, "row_index": row_index},
                    }
                )
                continue

            condition_key = _condition_key(conditions)
            if len(grades) > 1:
                diagnostics.append(
                    {
                        "code": "GRADE_SPLIT",
                        "message": f"merged grade split into {len(grades)} records",
                        "severity": "info",
                        "detail": {
                            "table_id": table_id,
                            "row_index": row_index,
                            "raw": raw_grade,
                        },
                    }
                )
            for grade_index, split_grade in enumerate(grades):
                record_count += 1
                record_id = f"{table_id}-R{row_index + 1}"
                if len(grades) > 1:
                    record_id = f"{record_id}-G{grade_index + 1}"
                record = {
                    "record_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "profile": profile,
                    "grade": split_grade,
                    "grade_raw": raw_grade if len(grades) > 1 else None,
                    "conditions": conditions,
                    "condition_key": condition_key,
                    "properties": properties,
                    "evidence_refs": [record_id],
                    "source": {
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                    },
                }
                records.append(record)
                evidence.append(
                    {
                        "evidence_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "raw_row": list(row),
                        "cells": {
                            headers[idx]: row[idx]
                            for idx in range(min(len(headers), len(row)))
                            if row[idx]
                        },
                    }
                )

            for extra_index, (label, columns) in enumerate(extra_groups.items(), start=1):
                extra_properties: dict[str, Any] = {}
                for measure, col in columns:
                    cell = row[col] if col < len(row) else ""
                    parsed = _parse_value(cell, strip_marks)
                    if parsed is None:
                        continue
                    raw_value = str(parsed.get("raw") or "").strip()
                    if raw_value in SKIP_CELL_VALUES:
                        continue
                    if _prose_cell(raw_value, parsed):
                        continue
                    if (
                        profile == "chemical_composition"
                        and parsed.get("value") is not None
                        and float(parsed["value"]) < 0
                    ):
                        continue
                    parsed["unit"] = _extract_unit(
                        headers[col], explicit_unit
                    ) or binding_units.get(measure, "")
                    parsed["column"] = headers[col]
                    extra_properties[_detect_measure(headers[col], measure)] = parsed
                if not extra_properties:
                    continue
                extra_conditions = dict(conditions)
                if "℃" in label or "温度" in label:
                    condition_name = "温度"
                elif "mm" in label or "厚" in label or "尺寸" in label:
                    condition_name = "规格"
                else:
                    condition_name = "状态"
                extra_conditions[condition_name] = label
                extra_id = f"{table_id}-R{row_index + 1}-X{extra_index}"
                records.append(
                    {
                        "record_id": extra_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "recipe_id": recipe_id,
                        "recipe_version": recipe_version,
                        "profile": profile,
                        "grade": grades[0],
                        "grade_raw": raw_grade if len(grades) > 1 else None,
                        "conditions": extra_conditions,
                        "condition_key": _condition_key(extra_conditions),
                        "properties": extra_properties,
                        "evidence_refs": [extra_id],
                        "source": {
                            "table_id": table_id,
                            "block_id": block_id,
                            "page_no": page_no,
                            "row_index": row_index,
                        },
                    }
                )
                evidence.append(
                    {
                        "evidence_id": extra_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "raw_row": list(row),
                        "cells": {
                            headers[col]: row[col]
                            for _, col in columns
                            if col < len(row) and row[col]
                        },
                    }
                )

    if not records and profile == "chemical_composition":
        # Composition tables often have no grade column (single specification).
        return _parse_chemical_columns(
            table,
            table_id=table_id,
            page_no=page_no,
            profile=profile,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            strip_marks=strip_marks,
            units=units,
            binding_units=binding_units,
            diagnostics=diagnostics,
        )

    if not records:
        # Column bindings did not match this table: fall back to the matrix
        # strategy chain (property / grade-property / property rows / hardness).
        strategy_chain = (manifest or {}).get("strategy_chain") or rules.get(
            "strategy_chain"
        )
        try:  # imported as a package (tests)
            from .strategies import run_strategy_chain
        except ImportError:  # flat runtime image (/engine)
            from strategies import run_strategy_chain

        result = run_strategy_chain(
            table,
            {
                "recipe_id": recipe_id,
                "recipe_version": recipe_version,
                "profile": profile,
                "measures": list((bindings.get("measures") or {}).keys()),
            },
            diagnostics,
            strategy_chain,
        )
        if result is not None:
            records, evidence = result

    if not records:
        diagnostics.append(
            {
                "code": "NO_RECORDS",
                "message": f"table {table_id} produced no records",
                "severity": "warning",
                "detail": {"table_id": table_id},
            }
        )

    summary = {
        "table_id": table_id,
        "page_no": page_no,
        "profile": profile,
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "rows": row_total,
        "records": len(records),
    }
    return records, evidence, summary
