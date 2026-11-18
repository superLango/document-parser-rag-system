"""Reference graph and method binding for one OCR document.

Standard library only.

The normative-reference section names the standards the document depends on;
clauses then cite them inline ("按 GB/T 228.1 进行").  This module builds that
graph, marks citations that never appear in the normative list, and derives a
``feature -> method`` binding used to fill empty ``试验方法`` cells.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

SCHEMA_VERSION = "document-references/1"
STANDARD_RE = re.compile(
    r"(?P<org>GB\s*/\s*T|GBIT|GB\s*厅|GBT|GB|GJB\s*/\s*Z|GJB|JB\s*/\s*T|JB|"
    r"YB\s*/\s*T|YB|YS\s*/\s*T|YST|YS|HB\s*/\s*Z|HB|ASTM|ASME|ISO|AMS(?:-STD)?|"
    r"EN|DIN|QJ|NB\s*/\s*T|API|Q\s*/\s*[A-Za-z]{1,4})\s*"
    r"(?P<num>[A-Z]?\s*\d+(?:\.\s*\d+)*(?:\s*[-—–:]\s*\d{1,4})*)"
    r"(?:\s+(?P<year>\d{4}))?"
)
NORMATIVE_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*2(?:\.0)?\s*[、.．]?\s*"
    r"(?:规范性引用文件|引用标准|引用文件|normative\s+references"
    r"|applicable\s+documents?|referenced\s+documents?|references)\s*:?\s*$",
    re.IGNORECASE,
)
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?\d{1,2}(?:\.\s*\d{1,3})*\.?\s+[\u4e00-\u9fffA-Za-z]"
)
TOP_LEVEL_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(\d{1,2})(?:\.|\s|$)")
CUE_RE = re.compile(
    r"按|见|符合|执行|依据|遵守|遵照|采用|引用"
    r"|in\s+accordance\s+with|according\s+to|per\b|conform(?:s|ing)?\s+to"
    r"|comply\s+with|specified\s+in|referenced\s+in",
    re.IGNORECASE,
)
SENTENCE_RE = re.compile(r"(?<=[。；;])|(?<=[.!?])\s+(?![0-9])")
SKIP_LINE_RE = re.compile(r"代替|历次版本|起草|编制|归口|提出|发布|实施|修订|相比")
RELATION_PRIORITY = {"normative": 3, "table_note": 2, "method": 2, "clause": 1, "other": 0}
# Sampling/preparation/packaging standards are not test methods.
NON_METHOD_RE = re.compile(
    r"^(?:GB/T\s*(?:20066|2975|222|8170|247|2101|1\.1)\b|(?:ISO|GB/T)\s*(?:9001|17025|14001|19001)\b|IATF)"
)
NON_METHOD_TITLE_MARKERS = (
    "取样",
    "制样",
    "试样制备",
    "包装",
    "标志",
    "质量证明书",
    "验收规则",
    "sampling",
    "packaging",
    "packing",
    "quality assurance",
    "tolerances",
    "dimensions",
)
METHOD_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("化学成分", ("化学成分", "化学分析", "成分分析", "chemical composition")),
    ("高温拉伸", ("高温拉伸", "high temperature tensile", "elevated temperature tensile")),
    ("室温拉伸", ("拉伸试验", "室温拉伸", "拉伸", "tensile", "tension test")),
    ("夏比冲击", ("冲击试验", "夏比", "charpy", "impact test")),
    ("布氏硬度", ("布氏硬度", "布氏", "brinell")),
    ("洛氏硬度", ("洛氏硬度", "洛氏", "rockwell")),
    ("维氏硬度", ("维氏硬度", "维氏", "vickers")),
    ("断裂韧度", ("断裂韧", "断裂韧性", "fracture toughness")),
    ("弯曲", ("弯曲试验", "弯曲", "bending", "bend test")),
    ("晶粒度", ("晶粒度", "晶粒", "grain size")),
    ("低倍", ("低倍组织", "低倍", "macrostructure", "macroetch", "grain flow")),
    ("高倍组织", ("高倍组织", "显微组织", "显微结构", "microstructure", "metallographic")),
    ("非金属夹杂", ("非金属夹杂", "夹杂物", "洁净度", "inclusion", "cleanliness")),
    ("超声波检测", ("超声", "ultrasonic")),
    ("涡流检测", ("涡流", "eddy current")),
    ("铁素体", ("铁素体", "ferrite")),
    ("外观", ("外观", "表面质量", "workmanship", "appearance")),
    ("尺寸", ("尺寸", "外形", "dimensions", "tolerances")),
    ("相变温度", ("相变温度", "transus", "transformation temperature")),
    ("晶间腐蚀", ("晶间腐蚀", "intergranular corrosion")),
    ("表面粗糙度", ("表面粗糙度", "roughness")),
    ("高温持久", ("持久", "蠕变", "creep", "stress rupture")),
)
SKIP_CLAUSE_KINDS = {"scope", "normative_reference", "terms"}
# 标准号本身就说明是哪项试验（GB/T 231.1 只能是布氏硬度），比所在条款标题可靠：
# OCR 丢了“6.4 硬度试验”标题时，231.1 会落进“冲击试验”条款里。
NUMBER_FAMILIES: tuple[tuple[str, str], ...] = (
    (r"^GB/T (?:228\.2|4338)\b", "高温拉伸"),
    (r"^GB/T 228(?:\.1)?$", "室温拉伸"),
    (r"^GB/T 229$", "夏比冲击"),
    (r"^GB/T 231(?:\.\d)?$", "布氏硬度"),
    (r"^GB/T 230(?:\.\d)?$", "洛氏硬度"),
    (r"^GB/T 4340(?:\.\d)?$", "维氏硬度"),
    (r"^GB/T 232$", "弯曲"),
    (r"^GB/T 226$", "低倍"),
    (r"^GB/T 6394$", "晶粒度"),
    (r"^GB/T 10561$", "非金属夹杂"),
    (r"^GB/T 13298$", "高倍组织"),
    (r"^GB/T 4334$", "晶间腐蚀"),
)


PRODUCT_TITLE_RE = re.compile(r"锻件|钢板|钢管|钢棒|钢带|型材|铸件|技术条件|通用要求")
METHOD_TITLE_RE = re.compile(r"方法|分析|测定|试验|检验|检测|评级|评定")


def _number_family(number: str) -> str:
    return next((family for pattern, family in NUMBER_FAMILIES if re.match(pattern, number)), "")

# -- cross-standard content requirements -----------------------------------
# A *content* reference defers the acceptance values of a category/parameter
# to another standard ("化学成分应符合 GB/T 3620.2 的规定").  A *method*
# reference only names how to test ("拉伸试验按 GB/T 228.1 的规定进行") and is
# already handled by the method bindings above.
CROSS_METHOD_HINT_RE = re.compile(
    r"方法|试验|检验|检测|测定|分析|评级|制样|取样|制备|探伤|校准|测量"
)
CROSS_SAMPLING_RE = re.compile(
    r"^(?:GB/T\s*(?:20066|2975|8170|247|2101|17505|1\.1))\b"
)
CROSS_PARAMETER_SUFFIXES = (
    "允许偏差",
    "公差",
    "偏差",
    "等级",
    "级别",
    "半径",
    "角度",
    "温度",
    "时间",
    "速率",
    "数量",
    "方向",
    "位置",
    "厚度",
    "直径",
    "长度",
    "宽度",
    "含量",
    "组织",
    "缺陷",
    "表面",
    "性能",
    "状态",
    "范围",
    "尺寸",
)
CROSS_PRODUCT_PREFIX_RE = re.compile(
    r"^(?:成品|板材|棒材|管材|丝材|锻件|铸件|钢棒|钢板|钢带|钢管|产品|原材料|"
    r"半成品|交货|所有|其他|其余|该|其|本|此)"
)
CROSS_FILLER_RE = re.compile(r"^(?:推荐|规定的|要求的|一般|通常|可|应|均|都|也|尚|须|并|且)+")
CROSS_STOP_SUBJECTS = {
    "要求",
    "规定",
    "标准",
    "内容",
    "项目",
    "指标",
    "结果",
    "质量",
}
CROSS_CATEGORY_HINTS = {
    "力学性能": "力学性能",
    "机械性能": "力学性能",
    "理化性能": "力学性能",
    "公称尺寸": "尺寸",
    "外径": "尺寸",
    "壁厚": "尺寸",
    "长度": "尺寸",
    "宽度": "尺寸",
    "厚度": "尺寸",
}
CROSS_SKIP_RE = re.compile(
    r"本文件|整合了|相比|代替|删除|增加了|引用|规范性|目次|前言|引言|起草|归口"
)


def _cross_subject(probe: str, start: int) -> str:
    window = probe[:start].strip()
    window = re.sub(
        r"(?:应?符合|应?满足|按照?|依据|根据|遵照|遵守|执行)+$", "", window
    )
    window = re.split(r"[，。；：、,;:！？]", window)[-1]
    window = re.sub(r"(?:应|均|都|也|亦|尚|须|并|且|可|的)+$", "", window)
    value = _clean(window)
    for _ in range(3):
        before = value
        value = CROSS_PRODUCT_PREFIX_RE.sub("", value)
        value = CROSS_FILLER_RE.sub("", value)
        value = value.strip(" 的等")
        if value == before:
            break
    return value


def _cross_feature(subject: str, title: str, probe: str) -> str:
    for text in (subject, title, probe):
        family = _family(text)
        if family:
            return family
        for keyword, mapped in CROSS_CATEGORY_HINTS.items():
            if keyword in text:
                return mapped
    return ""


def _cross_parameter(subject: str, feature: str) -> str:
    if not subject or subject in CROSS_STOP_SUBJECTS:
        return ""
    if len(subject) > 14 or re.search(r"[和及与或、]", subject):
        # "公称外径和公称壁厚" 这类多参数/类别限定语按整类导入。
        return ""
    suffix = next(
        (item for item in CROSS_PARAMETER_SUFFIXES if subject.endswith(item)), ""
    )
    if not suffix:
        return ""
    # "公称尺寸"/"板材的化学成分" 是类别限定语，不是单参数。
    if feature and feature in subject and len(subject) - len(feature) <= 3:
        return ""
    return re.sub(r"\s+", "", subject)


def _task_id(feature: str, parameter: str, standard_no: str, edition: str) -> str:
    import hashlib

    key = "|".join([feature, parameter, standard_no, edition])
    return f"xstd-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


def _cross_candidates(clauses: list[dict[str, Any]], self_no: str) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for clause in clauses:
        kind = str(clause.get("kind") or "")
        if kind in SKIP_CLAUSE_KINDS:
            continue
        clause_id = str(clause.get("clause_id") or "")
        page_no = int(clause.get("page_no") or 0)
        title = _clean(clause.get("title"))
        text = _clean(clause.get("text"))
        for sentence in SENTENCE_RE.split(f"{title}。{text}"):
            probe = _clean(sentence)
            if not probe or not CUE_RE.search(probe):
                continue
            if CROSS_SKIP_RE.search(probe):
                continue
            if re.search(r"方法", probe) and not re.search(r"应?符合|应?满足", probe):
                # "化学成分分析按…规定的方法测定" 是方法引用。
                continue
            for match in STANDARD_RE.finditer(probe):
                number, edition = _standard(
                    match.group("org"), match.group("num"), match.group("year") or ""
                )
                if not number or number == self_no:
                    continue
                if CROSS_SAMPLING_RE.match(number):
                    continue
                raw_subject = _cross_subject(probe, match.start())
                if not raw_subject:
                    # 标准号列表项（"GB/T 223.3、GB/T 223.4…"）没有自己的
                    # 要求对象，不能给每一项都建任务。
                    continue
                if not re.search(r"[\u4e00-\u9fffA-Za-z]", raw_subject):
                    # OCR 在标准号之间插入的 "9. 1" 之类的噪声。
                    continue
                subject = raw_subject if raw_subject not in CROSS_STOP_SUBJECTS else ""
                tail = probe[match.end() : match.end() + 24]
                # “（试验条件：400℃）”不是“按某标准做试验”的方法引用。
                if re.search(
                    r"方法|测定|试验(?!条件)|检验|分析|检测", tail
                ) and not re.search(r"应?符合|应?满足", probe[: match.start()]):
                    continue
                feature = _cross_feature(subject, title, probe)
                parameter = _cross_parameter(subject, feature)
                if not feature and not parameter:
                    continue
                # "拉伸试验方法按 GB/T 228.1" / "低倍组织试验方法按 GB/T 226"
                # 是方法引用，不导入内容。
                if CROSS_METHOD_HINT_RE.search(subject):
                    continue
                scope = "parameter" if parameter else "category"
                task_id = _task_id(feature, parameter, number, edition)
                payload = {
                    "task_id": task_id,
                    "feature": feature,
                    "scope": scope,
                    "parameter": parameter,
                    "standard_no": number,
                    "edition": edition,
                    "kind": "content",
                    "clause_id": clause_id,
                    "page_no": page_no,
                    "quote": probe[:300],
                    "title": title[:160],
                }
                existing = found.get(task_id)
                if existing is None:
                    found[task_id] = payload
                elif not existing.get("clause_id") and clause_id:
                    existing["clause_id"] = clause_id
                    existing["page_no"] = page_no
    return sorted(
        found.values(),
        key=lambda item: (item["page_no"], item["standard_no"], item["feature"]),
    )


def _clean(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _pages(ocr: dict[str, Any]) -> list[tuple[int, str]]:
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(ocr.get("pages") or [], start=1):
        if not isinstance(page, dict):
            continue
        markdown = str(page.get("markdown") or "")
        if markdown.strip():
            pages.append((int(page.get("page_no") or index), markdown))
    if pages:
        return pages
    markdown = str(ocr.get("markdown") or "")
    return [(0, markdown)] if markdown.strip() else []


def _standard(org: str, number: str, year: str = "") -> tuple[str, str]:
    head = re.sub(r"\s+", "", unicodedata.normalize("NFKC", org or "")).upper()
    head = (
        head.replace("GBIT", "GB/T")
        .replace("GB厅", "GB/T")
        .replace("GBT", "GB/T")
        .replace("YST", "YS/T")
    )
    tail = re.sub(r"\s+", "", unicodedata.normalize("NFKC", number or ""))
    tail = tail.replace("－", "-").replace("—", "-").replace("–", "-").replace(":", "-")
    edition = re.sub(r"\s+", "", year or "")
    if not edition:
        match = re.search(r"-(\d{4})$", tail)
        if match and 1900 <= int(match.group(1)) <= 2099:
            edition = match.group(1)
            tail = tail[: match.start()]
    return f"{head} {tail}".strip(), edition


def _entry(
    match: re.Match[str],
    raw: str,
    relation: str,
    page_no: int = 0,
    clause_id: str = "",
    title: str = "",
) -> dict[str, Any] | None:
    standard_no, edition = _standard(
        match.group("org"), match.group("num"), match.group("year") or ""
    )
    if not standard_no:
        return None
    return {
        "raw": _clean(raw)[:240],
        "standard_no": standard_no,
        "title": _clean(title)[:160],
        "edition": edition,
        "dated": bool(edition),
        "relation": relation,
        "clause_id": clause_id,
        "page_no": page_no,
        "resolved": relation == "normative",
        "source": "normative_list" if relation == "normative" else "clause",
    }


def _normative_entries(pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    in_section = False
    org_hint = ""
    for page_no, markdown in pages:
        for raw_line in markdown.splitlines():
            line = _clean(raw_line).lstrip("# ").strip()
            if not line:
                continue
            if NORMATIVE_HEADING_RE.match(line):
                in_section = True
                org_hint = ""
                continue
            if in_section and HEADING_RE.match(line):
                top = TOP_LEVEL_RE.match(line)
                # "2.1 ASTM Standards" is still inside the normative section;
                # "3. Terminology" ends it.
                if top is None or top.group(1) != "2":
                    in_section = False
                    continue
            if not in_section or SKIP_LINE_RE.search(line):
                continue
            hinted = re.match(
                r"^(?:2(?:\.\d+)?\s+)?(ASTM|ASME|AMS|ISO|SAE|DIN|EN)\b",
                line,
                re.IGNORECASE,
            )
            if hinted:
                org_hint = hinted.group(1).upper()
            match = STANDARD_RE.search(line)
            if match is not None:
                suffix = line[match.end() :].lstrip(":：，,、 ")
                entry = _entry(
                    match, line, relation="normative", page_no=page_no, title=suffix
                )
                if entry is not None:
                    entries.append(entry)
                continue
            # ASTM lists designations without the "ASTM" prefix under
            # "2.1 ASTM Standards" ("E213 Practice for Ultrasonic Testing...").
            if org_hint == "ASTM":
                bare = re.match(r"^(?P<num>[A-Z]{1,2}\s*\d{1,5}(?:-\d{2,4})?)\b", line)
                if bare is None:
                    continue
                synthetic = f"ASTM {line}"
                syn_match = STANDARD_RE.search(synthetic)
                if syn_match is None:
                    continue
                suffix = line[bare.end() :].lstrip(":：，,、 ")
                entry = _entry(
                    syn_match,
                    line,
                    relation="normative",
                    page_no=page_no,
                    title=suffix,
                )
                if entry is not None:
                    entries.append(entry)
    return entries


def _clause_entries(clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for clause in clauses:
        kind = str(clause.get("kind") or "")
        if kind in SKIP_CLAUSE_KINDS:
            continue
        clause_id = str(clause.get("clause_id") or "")
        page_no = int(clause.get("page_no") or 0)
        title = _clean(clause.get("title"))
        text = _clean(clause.get("text"))
        fields = clause.get("fields") or {}
        method = _clean((fields.get("method_standard") or {}).get("raw"))
        if method:
            match = STANDARD_RE.search(method)
            if match is not None:
                entry = _entry(
                    match,
                    f"{title} {method}".strip(),
                    relation="method",
                    page_no=page_no,
                    clause_id=clause_id,
                    title=title,
                )
                if entry is not None:
                    entries.append(entry)
        probe = f"{title} {text}"
        if not CUE_RE.search(probe):
            continue
        for match in STANDARD_RE.finditer(probe):
            entry = _entry(
                match,
                probe[max(0, match.start() - 24) : match.end() + 48],
                relation="clause",
                page_no=page_no,
                clause_id=clause_id,
                title=title,
            )
            if entry is not None:
                entries.append(entry)
    return entries


def _table_entries(inspections: list[dict[str, str]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in inspections:
        method = _clean(item.get("method"))
        requirement = _clean(item.get("requirement"))
        probe = " ".join(
            part for part in (_clean(item.get("item")), method, requirement) if part
        )
        if not probe:
            continue
        for match in STANDARD_RE.finditer(probe):
            entry = _entry(
                match,
                probe,
                relation="table_note",
                title=_clean(item.get("item")),
            )
            if entry is not None:
                entries.append(entry)
    return entries


def _merge(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry["standard_no"]
        existing = merged.get(key)
        if existing is None:
            merged[key] = entry
            continue
        if RELATION_PRIORITY.get(entry["relation"], 0) > RELATION_PRIORITY.get(
            existing["relation"], 0
        ):
            existing["relation"] = entry["relation"]
        if not existing["title"] and entry["title"]:
            existing["title"] = entry["title"]
        if not existing["edition"] and entry["edition"]:
            existing["edition"] = entry["edition"]
            existing["dated"] = True
        if not existing["clause_id"] and entry["clause_id"]:
            existing["clause_id"] = entry["clause_id"]
        if not existing["page_no"] and entry["page_no"]:
            existing["page_no"] = entry["page_no"]
    # OCR sometimes drops a digit ("GB/T 23" for "GB/T 230"). Drop the
    # truncated key when a longer number with the same prefix exists.
    numbers = list(merged)
    for number in numbers:
        for other in numbers:
            if other == number or not other.startswith(number):
                continue
            if len(other) > len(number) and other[len(number)].isdigit():
                merged.pop(number, None)
                break
    return list(merged.values())


def _is_method_standard(standard_no: str, title: str) -> bool:
    if NON_METHOD_RE.match(standard_no):
        return False
    lowered = _clean(title).lower()
    return not any(marker in lowered for marker in NON_METHOD_TITLE_MARKERS)


def _self_standard(pages: list[tuple[int, str]]) -> str:
    """Read the document's own standard number from the cover/title block."""
    stop_re = re.compile(
        r"^\s*(?:目\s*次|前\s*言|引\s*言|1\s*范围|2\s*规范性引用文件|规范性引用文件"
        r"|1\.?\s*scope|2\.?\s*(?:normative\s+references|referenced\s+documents"
        r"|applicable\s+documents))",
        re.IGNORECASE,
    )
    for _page_no, markdown in pages[:1]:
        for raw_line in markdown.splitlines()[:30]:
            line = _clean(raw_line)
            if not line:
                continue
            if stop_re.match(line):
                break
            if SKIP_LINE_RE.search(line):
                continue
            if any(marker in line for marker in ("代替", "发布", "实施", "前言")):
                continue
            match = STANDARD_RE.search(line)
            if match is None:
                continue
            number, _ = _standard(
                match.group("org"), match.group("num"), match.group("year") or ""
            )
            if number:
                return number
    return ""


def _family(text: str) -> str:
    value = _clean(text).lower()
    for family, keywords in METHOD_FAMILIES:
        if any(keyword in value for keyword in keywords):
            return family
    return ""


def _bindings(
    references: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
    self_no: str = "",
) -> dict[str, dict[str, Any]]:
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    # 规范性引用文件里标题是产品标准（“NB/T 47010 承压设备用不锈钢耐热钢锻件”）的，
    # “按 NB/T 47010 进行化学成分分析”只是转引，不是试验方法。
    products = {
        str(entry.get("standard_no") or "")
        for entry in references
        if entry.get("relation") == "normative"
        and PRODUCT_TITLE_RE.search(str(entry.get("title") or ""))
        and not METHOD_TITLE_RE.search(str(entry.get("title") or ""))
    }

    content_refs: set[str] = set()

    def offer(family: str, score: int, payload: dict[str, Any]) -> None:
        if not family or str(payload.get("method") or "") in products:
            return
        current = best.get(family)
        if current is None or score > current[0]:
            best[family] = (score, payload)

    for clause in clauses:
        kind = str(clause.get("kind") or "")
        if kind in SKIP_CLAUSE_KINDS:
            continue
        title = _clean(clause.get("title"))
        text = _clean(clause.get("text"))
        title_family = _family(title)
        clause_id = str(clause.get("clause_id") or "")
        page_no = int(clause.get("page_no") or 0)
        for sentence in SENTENCE_RE.split(f"{title} {text}"):
            probe = _clean(sentence)
            if not probe or not CUE_RE.search(probe):
                continue
            family = title_family or _family(probe)
            previous_end = 0
            for match in STANDARD_RE.finditer(probe):
                # “晶粒度按GB/T 6394，非金属夹杂物按GB/T 10561”：每个标准号归属
                # 紧挨在它前面点名的项目，而不是整句的第一个项目。
                local = _family(probe[previous_end : match.start()])
                previous_end = match.end()
                number, _ = _standard(
                    match.group("org"), match.group("num"), match.group("year") or ""
                )
                local = _number_family(number) or local
                if not (local or family):
                    continue
                if re.search(
                    r"(?:comply\s+with|conform\s+to|符合|满足)[^.。;；]{0,30}$",
                    probe[: match.start()],
                    re.I,
                ):
                    # “应符合 EN 10083-3 的要求”是内容要求（跨标准），不是试验方法。
                    continue
                if not number or number == self_no:
                    continue
                if not _is_method_standard(number, probe):
                    continue
                offer(
                    local or family,
                    40 if title_family or local else 20,
                    {
                        "method": number,
                        "source": "clause",
                        "clause_id": clause_id,
                        "page_no": page_no,
                        "quote": probe[:200],
                    },
                )
        fields = clause.get("fields") or {}
        method = _clean((fields.get("method_standard") or {}).get("raw"))
        if method:
            match = STANDARD_RE.search(method)
            if match is not None:
                number, _ = _standard(
                    match.group("org"), match.group("num"), match.group("year") or ""
                )
                family = title_family or _family(text)
                # “should comply with the requirement of EN 10083-3”：内容引用，不是方法。
                content_ref = bool(number) and re.search(
                    r"(?:comply\s+with|conform\s+to|符合|满足)[^.。;；]{0,40}"
                    + re.escape(number.split()[-1]),
                    f"{text} {_clean((fields.get("requirement") or {}).get("raw"))}",
                    re.I,
                )
                if content_ref:
                    content_refs.add(number)
                if (
                    number
                    and number != self_no
                    and family
                    and not content_ref
                    and _is_method_standard(number, f"{title} {method}")
                ):
                    offer(
                        family,
                        30 if title_family else 15,
                        {
                            "method": number,
                            "source": "clause",
                            "clause_id": clause_id,
                            "page_no": page_no,
                            "quote": _clean(f"{title} {method}")[:200],
                        },
                    )
    for reference in references:
        title = reference.get("title") or ""
        if not _is_method_standard(reference["standard_no"], title):
            continue
        if reference["standard_no"] in content_refs:
            continue
        family = _number_family(reference["standard_no"]) or _family(title)
        if not family:
            continue
        score = 30 if reference.get("relation") == "normative" else 10
        offer(
            family,
            score,
            {
                "method": reference["standard_no"],
                "source": reference.get("source") or "reference",
                "clause_id": reference.get("clause_id") or "",
                "page_no": int(reference.get("page_no") or 0),
                "quote": (_clean(title) or reference.get("raw") or "")[:200],
            },
        )
    return {family: payload for family, (_, payload) in sorted(best.items())}


def extract_references(
    ocr: dict[str, Any],
    clauses_payload: dict[str, Any],
    inspections: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    clauses = clauses_payload.get("clauses") or []
    pages = _pages(ocr)
    self_no = _self_standard(pages)
    normative = [
        entry
        for entry in _normative_entries(pages)
        if entry["standard_no"] != self_no
    ]
    entries = _merge(
        [
            *normative,
            *[
                entry
                for entry in _clause_entries(clauses)
                if entry["standard_no"] != self_no
            ],
            *[
                entry
                for entry in _table_entries(inspections or [])
                if entry["standard_no"] != self_no
            ],
        ]
    )
    normative_index = {
        entry["standard_no"] for entry in entries if entry["relation"] == "normative"
    }
    for entry in entries:
        if entry["relation"] != "normative":
            entry["resolved"] = entry["standard_no"] in normative_index
    entries.sort(
        key=lambda item: (
            -RELATION_PRIORITY.get(str(item.get("relation")), 0),
            str(item.get("standard_no")),
        )
    )
    unresolved = [entry for entry in entries if not entry.get("resolved")]
    bindings = _bindings(entries, clauses, self_no)
    cross_candidates = _cross_candidates(clauses, self_no)
    # 检验项目表的“验收指标”列也可能写“按 Q/S10-0533-2004”，这类引用
    # 同样需要进入跨标准展开；否则表格型要求只能保留文本。
    pseudo_clauses = [
        {
            "clause_id": str(item.get("clause") or ""),
            "title": "",
            "text": " ".join(
                part
                for part in (
                    str(item.get("item") or ""),
                    str(item.get("requirement") or item.get("method") or ""),
                )
                if part
            ),
            "kind": "technical_requirement",
            "page_no": 0,
        }
        for item in inspections or []
        if item.get("requirement") or item.get("method")
    ]
    if pseudo_clauses:
        known_ids = {str(task.get("task_id") or "") for task in cross_candidates}
        for task in _cross_candidates(pseudo_clauses, self_no):
            if str(task.get("task_id") or "") not in known_ids:
                cross_candidates.append(task)
                known_ids.add(str(task.get("task_id") or ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "self_standard": self_no,
        "references": entries,
        "unresolved": [
            {
                "standard_no": entry["standard_no"],
                "edition": entry.get("edition") or "",
                "relation": entry.get("relation") or "",
                "clause_id": entry.get("clause_id") or "",
                "page_no": entry.get("page_no") or 0,
            }
            for entry in unresolved
        ],
        "bindings": bindings,
        "cross_standard_candidates": cross_candidates,
        "stats": {
            "total": len(entries),
            "normative": len(normative_index),
            "citations": sum(
                1 for entry in entries if entry["relation"] != "normative"
            ),
            "unresolved": len(unresolved),
            "resolution_rate": round(
                (len(entries) - len(unresolved)) / len(entries), 4
            )
            if entries
            else 0.0,
            "bindings": len(bindings),
            "cross_standard_candidates": len(cross_candidates),
        },
    }
