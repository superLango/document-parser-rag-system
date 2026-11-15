"""Document item inventory: what the standard asks the laboratory to test.

The inventory merges three sources into one authoritative list:

* ``property_table``  - performance tables that already produced records;
* ``inspection_table`` - 检验项目表 rows (method / sampling / clause number);
* ``clause``          - prose requirements that never appear in a table.

Rows carry a stable status so the projection layer and the reviewer can tell a
confirmed numerical item from a prose-only item.  Standard library only.
"""

from __future__ import annotations

import re
from typing import Any

try:  # imported as a package (tests)
    from .builtin import (
        _feature_for_measure,
        _flatten_headers,
        _is_footnote_row,
        _normalize_doc_text,
    )
except ImportError:  # flat runtime image (/engine)
    from builtin import (  # type: ignore[no-redef]
        _feature_for_measure,
        _flatten_headers,
        _is_footnote_row,
        _normalize_doc_text,
    )

SCHEMA_VERSION = "document-inventory/1"

# Features that can only be judged from prose/qualitative requirements.
QUALITATIVE_FEATURES = (
    "晶粒度",
    "低倍",
    "高倍组织",
    "非金属夹杂",
    "超声波检测",
    "涡流检测",
    "铁素体",
    "外观",
    "尺寸",
    "相变温度",
    "晶间腐蚀",
    "断口",
    "表面粗糙度",
    "脱脂",
)
QUALITATIVE_SET = set(QUALITATIVE_FEATURES)

# Order matters: 高温拉伸 before 拉伸, 布氏 before generic 硬度, 晶粒度 before
# 尺寸 ("grain size" must not become a dimension item).
FEATURE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("化学成分", ("化学成分", "化学分析", "成分分析", "chemical composition")),
    ("高温拉伸", ("高温拉伸", "high temperature tensile", "elevated temperature tensile")),
    (
        "室温拉伸",
        ("室温拉伸", "拉伸试验", "拉伸", "tensile properties", "tension test", "tensile"),
    ),
    ("夏比冲击", ("夏比冲击", "冲击试验", "冲击", "charpy", "impact test", "impact")),
    ("布氏硬度", ("布氏硬度", "布氏", "brinell")),
    ("洛氏硬度", ("洛氏硬度", "洛氏", "rockwell")),
    ("维氏硬度", ("维氏硬度", "维氏", "vickers")),
    ("断裂韧度", ("断裂韧性", "断裂韧度", "断裂韧", "fracture toughness")),
    ("弯曲", ("弯曲试验", "弯曲", "bending", "bend test")),
    ("晶粒度", ("晶粒度", "grain size")),
    (
        "低倍",
        (
            "低倍组织",
            "低倍",
            "macrostructure",
            "macro structure",
            "macroexamination",
            "macro examination",
            "macroetch",
            "macro etch",
            "macrographic",
            "grain flow",
            "流线",
        ),
    ),
    (
        "高倍组织",
        (
            "高倍组织",
            "显微组织",
            "显微结构",
            "microstructure",
            "micro structure",
            "microscopic structure",
            "microexamination",
            "micro examination",
            "metallographic",
            "metallography",
            "structure of all material",
            "uniform structure",
        ),
    ),
    (
        "非金属夹杂",
        (
            "非金属夹杂",
            "夹杂物",
            "洁净度",
            "nonmetallic inclusion",
            "non-metallic inclusion",
            "inclusion content",
            "inclusions",
            "cleanliness",
        ),
    ),
    (
        "超声波检测",
        (
            "超声波检测",
            "超声波检验",
            "超声检测",
            "超声检验",
            "无损检测",
            "ultrasonic inspection",
            "ultrasonic examination",
            "ultrasonic testing",
            "ultrasonically inspected",
            "ultrasonic test",
            "ultrasonic quality",
        ),
    ),
    ("涡流检测", ("涡流检测", "涡流检验", "涡流", "eddy current", "eddy-current")),
    ("铁素体", ("铁素体", "α相含量", "α相", "ferrite", "alpha phase")),
    (
        "外观",
        (
            "外观质量",
            "外观",
            "表面质量",
            "表面加工",
            "表面要求",
            "内外表面",
            "交货表面",
            "表面及夹层",
            "表面洁净",
            "workmanship",
            "appearance",
            "surface quality",
            "surface condition",
            "surface finish",
            "alpha case",
            "quality",
            "表面缺陷",
        ),
    ),
    (
        "尺寸",
        (
            "尺寸",
            "外形",
            "厚度",
            "壁厚",
            "外径",
            "直径",
            "宽度",
            "长度",
            "不平度",
            "切斜",
            "圆度",
            "椭圆度",
            "tolerances",
            "tolerance",
            "dimensions",
            "dimensional",
        ),
    ),
    (
        "相变温度",
        (
            "相变温度",
            "β转变温度",
            "转变温度",
            "transformation temperature",
            "beta transus",
            "transus",
        ),
    ),
    ("晶间腐蚀", ("晶间腐蚀", "intergranular corrosion", "intergranular attack")),
    ("断口", ("断口", "fracture appearance", "fracture surface")),
    ("表面粗糙度", ("表面粗糙度", "粗糙度", "surface roughness", "roughness")),
    ("脱脂", ("脱脂", "degreasing", "degrease")),
    ("高温持久", ("持久", "蠕变", "creep", "stress rupture")),
)
FAMILY_BY_FEATURE = {
    "化学成分": "chemical",
    "室温拉伸": "mechanical",
    "高温拉伸": "mechanical",
    "夏比冲击": "mechanical",
    "布氏硬度": "mechanical",
    "洛氏硬度": "mechanical",
    "维氏硬度": "mechanical",
    "断裂韧度": "mechanical",
    "弯曲": "mechanical",
    "高温持久": "mechanical",
    "晶粒度": "metallographic",
    "低倍": "metallographic",
    "高倍组织": "metallographic",
    "非金属夹杂": "metallographic",
    "超声波检测": "nondestructive",
    "涡流检测": "nondestructive",
    "铁素体": "metallographic",
    "外观": "visual",
    "尺寸": "dimension",
    "相变温度": "thermal",
    "晶间腐蚀": "corrosion",
    "断口": "fracture",
    "表面粗糙度": "surface",
    "脱脂": "surface",
}
SKIP_CLAUSE_KINDS = {"scope", "normative_reference", "terms"}
AGGREGATE_ITEMS = {"力学性能", "机械性能", "性能"}
# 特殊要求清单里的占位项（“规定的显微组织”“更高的力学性能”）不是具体检验项目。
GENERIC_LIST_ITEM_RE = re.compile(
    r"^(?:规定的|更高|更严格|其它|其他)|要求$"
)
# ". " 只在下一句以大写字母/引号/括号开头时断句，避免截断“4. 0级”。
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。；;])|(?<=[.!?])\s+(?=[A-Z\"'“‘(（])")
CJK_GAP_RE = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
DECIMAL_GAP_RE = re.compile(r"(?<=\d)\.\s+(?=\d)")
# 方法条款只描述“怎么做”，不能当作验收要求。
METHOD_ONLY_RE = re.compile(
    r"(?:按|按照|依据|采用|用|接|见).{0,60}?(?:规定|方法).{0,12}?"
    r"(?:进行|执行|测量|检验|检测|评定|评级|分析)"
    r"|(?:方法|检验|检测|测量|评级|分析).{0,20}?"
    r"(?:按|按照|依据|接|见|采用|执行|符合).{0,40}?(?:规定|标准|方法)"
)
ACCEPTANCE_RE = re.compile(
    r"应|不得|不应|不允许|不小于|不大于|不超过|不低于|不粗于|<=|>=|≤|≥|%|mm|MPa|要求",
    re.IGNORECASE,
)
# 缺陷列举句（“表面不应有……夹杂物等缺陷”）属于外观要求，不是夹杂物检验。
DEFECT_ENUMERATION_RE = re.compile(
    r"不应有|不得有|不允许有|应无|不允许存在|无肉眼可见|free of|shall be free",
    re.IGNORECASE,
)
DEFECT_NOUN_RE = re.compile(
    r"夹杂|inclusion|裂纹|折叠|结疤|气孔|缩尾|起皮|压折|氧化皮|缺陷|defect",
    re.IGNORECASE,
)
# Rows that label a block or a note, never an inspection item.
SKIP_ITEMS = {
    "说明",
    "备注",
    "注",
    "目录",
    "序号",
    "引用文件",
    "规范性引用文件",
    "检验项目",
    "项目",
}


def _clean(value: Any) -> str:
    text = _normalize_doc_text(value)
    # OCR 行内断词：“晶 间腐蚀”“4. 0级”。
    text = DECIMAL_GAP_RE.sub(".", text)
    text = CJK_GAP_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" ，,、;；")


def feature_from_text(text: Any) -> str:
    value = _clean(text)
    if not value:
        return ""
    lowered = value.lower()
    # ASTM/ISO use short section titles for the workmanship requirement.
    if re.match(r"^(?:finish|surface finish|workmanship|appearance)\b", lowered):
        return "外观"
    for feature, keywords in FEATURE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return feature
    return ""


def _defect_enumeration(text: str) -> bool:
    """True for “表面不应有裂纹、夹杂物等缺陷” style acceptance sentences."""
    if DEFECT_ENUMERATION_RE.search(text) and DEFECT_NOUN_RE.search(text):
        return True
    # “裂纹、异类夹杂物、折叠等缺陷须全部清除”同样是缺陷清单。
    return (
        "夹杂" in text
        and "缺陷" in text
        and not re.search(r"含量|级别|评定", text)
    )


def _weak_feature_ok(feature: str, sentence: str) -> bool:
    """Reject incidental mentions of a keyword (cleaning vs. NDT, duplex steel)."""
    lowered = _clean(sentence).lower()
    # 验收/判定规则不是产品要求：“外观质量不合格时判定该件不合格”。
    if re.search(
        r"(?:检验|试验)结果.{0,12}(?:不合格|合格)|判定.{0,8}(?:该|为|产品|件)"
        r"|异议|每批.{0,12}(?:应进行|应检验).{0,20}检验"
        r"|of each lot|at least one specimen|specimen from each lot",
        lowered,
    ):
        return False
    # 术语/前言/附录背景说明不是检验要求。
    if re.match(
        r"^(?:本文件|本标准|该标准|用户根据|它不是|相变温度一致性是指|热-机械加工过程)",
        lowered,
    ) or "通常被称为" in lowered:
        return False
    if feature == "低倍" and "grain flow" in lowered:
        return "forging" in lowered and (
            "contour" in lowered or "follow" in lowered
        )
    if feature == "铁素体":
        # “显微组织中δ-铁素体的含量应不超过2%”是铁素体要求；
        # 仅出现“奥氏体-铁素体”牌号说明时不算。
        return bool(
            re.search(r"铁素体|α相|ferrite|alpha phase", lowered)
        ) and bool(
            re.search(r"含量|百分|%|不超过|不大于|不小于|级别|content", lowered)
        )
    if feature == "高倍组织":
        # δ-铁素体含量句应归入“铁素体”，不要重复生成显微组织记录。
        if re.search(r"铁素体|ferrite", lowered) and re.search(
            r"含量|百分|%|不超过|不大于", lowered
        ):
            return False
        return True
    if feature == "非金属夹杂":
        # “表面不应有……非金属夹杂物等缺陷”是外观缺陷清单。
        return not _defect_enumeration(lowered)
    if feature == "外观":
        # 弯曲/折弯试验的“试样表面不应开裂”属于弯曲性能，不是外观要求。
        if re.search(r"(?:弯曲|折弯).{0,8}(?:试验|性能|半径)", lowered) or re.search(
            r"\bbend(?:ing)?\s+(?:test|properties)", lowered
        ):
            return False
        # 脱脂是独立的表面处理项目，不是外观。
        if "脱脂" in lowered or "degreas" in lowered:
            return False
        # 压扁/弯曲等试验的合格判定说明不是外观要求。
        if re.search(r"判定依据|合格与否|试验结果", lowered):
            return False
        # “加工到最终厚度/直径”是制造工序要求，不是表面质量。
        if re.search(
            r"metallurgical working|processed to the final|final thickness|dimensional sizing",
            lowered,
        ):
            return False
        return bool(
            re.search(
                r"不应|不得|不允许|应|质量|洁净|缺陷|clean|free of|defect"
                r"|workmanship|appearance|uniform in quality|quality and condition"
                r"|alpha case|surface (?:quality|condition|finish)",
                lowered,
            )
        )
    if feature == "尺寸":
        # AMS 尺寸章节常写成“conform to all applicable requirements of AMS2241”。
        if re.search(r"conform to all applicable requirements", lowered) and not re.search(
            r"chemical|成分", lowered
        ):
            return True
        # “尺寸公差应在订货单中规定”是合同注记，不是尺寸指标。
        if re.search(
            r"应在订货单中规定|应在合同中规定|由供需双方协商", lowered
        ):
            return False
        # 化学成分分析允许差不是产品尺寸公差。
        if re.search(r"chemical|成分|化学分析", lowered) and re.search(
            r"tolerance|公差|偏差", lowered
        ):
            return False
        # 加工到最终厚度/直径是制造工序，不是尺寸公差。
        if re.search(
            r"metallurgical working|processed to the final|final thickness|dimensional sizing",
            lowered,
        ):
            return False
        # 显微组织/晶粒度条款里的“直径、厚度……”不是尺寸检验项。
        if re.search(r"显微组织|晶粒度|非金属夹杂|相变|铁素体", lowered) and not re.search(
            r"公差|偏差|允差|tolerance", lowered
        ):
            return False
        # “允许有局部不超过厚度允许偏差之半的划伤、擦伤、凹坑……”是表面缺陷。
        if re.search(
            r"划伤|擦伤|凹坑|凸点|打磨痕迹|麻点|压痕|辊印|色差|裂纹|折叠|结疤|氧化皮",
            lowered,
        ) and "缺陷" in lowered:
            return False
        # “清除缺陷后应保证最小壁厚”“凹坑、划痕允许存在”属于外观/缺陷处理。
        if re.search(
            r"缺陷|缺欠|清除|裂纹|折叠|结疤|氧化皮|凹坑|划痕", lowered
        ) and not re.search(r"允许偏差|尺寸公差|公差", lowered):
            return False
        # 取样/复验条款里的“尺寸大于60mm”“试样截面尺寸”不是产品尺寸要求。
        if re.search(r"复验|切取|取样|试样", lowered) and not re.search(
            r"允许偏差|尺寸公差|公差", lowered
        ):
            return False
        if "理论重量" in lowered or "计算重量" in lowered:
            return False
        # 交货数量/交货形态条款不是尺寸公差。
        if re.search(r"数量|交货总量|根数", lowered) and not re.search(
            r"公差|偏差", lowered
        ):
            return False
        if "交货" in lowered and not re.search(r"允许偏差|公差|偏差", lowered):
            return False
        # 扩口/压扁/弯曲等工艺试验条款只是用到了外径/壁厚。
        if re.search(r"扩口|压扁|弯曲|冲击|拉伸", lowered) and not re.search(
            r"公差|偏差|尺寸", lowered
        ):
            return False
        # 单说“直径不小于1.0mm可供直丝”是交货形态，不是尺寸公差。
        if "直径" in lowered and not re.search(
            r"尺寸|公差|偏差|允许偏差", lowered
        ):
            return False
        return bool(
            re.search(
                r"尺寸|外形|厚度|壁厚|外径|直径|长度|宽度|不平度|弯曲度"
                r"|dimension|tolerance|size|thickness|diameter|width|length",
                lowered,
            )
            and re.search(
                r"应|符合|不大于|不小于|不超过|测量|检验|规定|公差|偏差"
                r"|shall|conform|exceed|tolerance",
                lowered,
            )
        )
    if feature == "超声波检测":
        # “可用超声检测代替液压试验”是替代方案说明，不是独立的超声检验项。
        if "代替" in lowered or "替代" in lowered:
            return False
        return any(
            keyword in lowered
            for keyword in (
                "超声波检测",
                "超声波检验",
                "超声检测",
                "超声检验",
                "无损检测",
                "ultrasonic inspection",
                "ultrasonic examination",
                "ultrasonic testing",
                "ultrasonically inspected",
                "ultrasonic test",
                "ultrasonic quality",
                "nondestructive test",
            )
        )
    if feature == "涡流检测":
        # “穿流和严重的涡流”描述锻造流线，不是涡流检测；
        # “超声检测或涡流检测”是超声条款里的备选方法，不单独建项。
        if "代替" in lowered or "替代" in lowered:
            return False
        if "超声" in lowered or "ultrasonic" in lowered:
            return False
        return any(
            keyword in lowered
            for keyword in (
                "涡流检测",
                "涡流检验",
                "涡流探伤",
                "eddy current",
                "eddy-current",
            )
        )
    if feature == "相变温度":
        # “特殊相变温度要求应在订货单中规定”是合同注记。
        if re.search(r"订货单|合同", lowered) and "规定" in lowered:
            return False
        # “可低于β转变温度固溶处理”是工艺许可，不是测相变温度的要求。
        if re.search(
            r"(?:below|above|near|低于|高于|接近)\s*(?:the\s*)?"
            r"(?:beta\s*)?(?:transus|β转变温度|转变温度)",
            lowered,
        ) and not re.search(
            r"determine|measure|report|测定|测量|报告", lowered
        ):
            return False
        return True
    if feature == "表面粗糙度":
        # “使表面光泽和粗糙度趋于一致”是外观修磨要求，不是粗糙度指标。
        if "趋于一致" in lowered:
            return False
        return bool(
            re.search(r"\bra\b|不大于|不超过|应符合|符合表", lowered)
        )
    return True


def features_from_text(text: Any) -> list[str]:
    """All known features mentioned in a sentence, in keyword priority order."""
    value = _clean(text)
    if not value:
        return []
    lowered = value.lower()
    found: list[str] = []
    for feature, keywords in FEATURE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords) and feature not in found:
            found.append(feature)
    return found


def keywords_for(feature: str) -> tuple[str, ...]:
    for name, keywords in FEATURE_KEYWORDS:
        if name == feature:
            return keywords
    return ()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(_clean(text)) if part.strip()]


def _feature_sentence(text: str, feature: str) -> str:
    keywords = keywords_for(feature)
    if not keywords:
        return ""
    for part in _sentences(text):
        lowered = part.lower()
        if any(keyword in lowered for keyword in keywords):
            return part
    return ""


LIST_ITEM_RE = re.compile(
    r"(?:^|[;；,，:：]|\s)\s*(?:[a-zA-Z]\)|[（(]\d+[）)])"
    r"\s*(?P<item>[^;；,，。]{2,40})"
)


def _list_items(text: str) -> list[str]:
    return [
        _clean(match.group("item"))
        for match in LIST_ITEM_RE.finditer(text)
        if _clean(match.group("item"))
    ]


def _technical_prefixes(clauses: list[dict[str, Any]]) -> set[str]:
    """Top-level clauses that hold technical requirements ("6 技术要求")."""
    prefixes: set[str] = set()
    for clause in clauses:
        clause_id = str(clause.get("clause_id") or "")
        if not clause_id or "." in clause_id:
            continue
        if str(clause.get("kind") or "") != "technical_requirement":
            continue
        prefixes.add(clause_id.split("-")[0])
    return prefixes


def _under_prefix(clause_id: str, prefixes: set[str]) -> bool:
    if not clause_id:
        return False
    return any(
        clause_id == prefix or clause_id.startswith(f"{prefix}.")
        for prefix in prefixes
    )


def _entry(feature: str, item: str) -> dict[str, Any]:
    return {
        "inventory_id": "",
        "item": item or feature,
        "feature": feature,
        "family": FAMILY_BY_FEATURE.get(feature, ""),
        "source": "",
        "sources": [],
        "clause_id": "",
        "clause_ids": [],
        "table_ids": [],
        "requirement": "",
        "requirements": [],
        "method": "",
        "sampling": {"quantity": "", "location": "", "note": ""},
        "status": "probable",
        "page_no": 0,
        "evidence": [],
        "conflicts": [],
    }


def _add_source(entry: dict[str, Any], source: str) -> None:
    if source and source not in entry["sources"]:
        entry["sources"].append(source)
    if not entry["source"]:
        entry["source"] = source


def _add_evidence(entry: dict[str, Any], evidence_id: str) -> None:
    if evidence_id and evidence_id not in entry["evidence"]:
        entry["evidence"].append(evidence_id)


def _merge_method(entry: dict[str, Any], method: str) -> None:
    value = _clean(method)
    if not value:
        return
    if not entry["method"]:
        entry["method"] = value
    elif value not in entry["method"] and entry["method"] not in value:
        entry["conflicts"].append(f"method:{entry['method']}!={value}")


def _record_entries(
    records: list[dict[str, Any]], entries: dict[str, dict[str, Any]]
) -> set[str]:
    features: set[str] = set()
    for record in records:
        if str(record.get("profile") or "") in {"heat_treatment", "qualitative"}:
            continue
        table_id = str(record.get("table_id") or "")
        page_no = int(record.get("page_no") or 0)
        for measure in record.get("properties") or {}:
            feature = _feature_for_measure(record, str(measure))
            if not feature:
                continue
            features.add(feature)
            entry = entries.setdefault(feature, _entry(feature, feature))
            _add_source(entry, "property_table")
            entry["status"] = "confirmed"
            if table_id and table_id not in entry["table_ids"]:
                entry["table_ids"].append(table_id)
            if not entry["page_no"]:
                entry["page_no"] = page_no
    return features


def _inspection_entries(
    inspections: list[dict[str, str]],
    entries: dict[str, dict[str, Any]],
    evidence_sink: list[dict[str, Any]],
) -> None:
    for index, item in enumerate(inspections, start=1):
        name = _clean(item.get("item"))
        if not name or name in SKIP_ITEMS or len(name) < 2:
            continue
        feature = feature_from_text(name)
        key = feature or f"item:{name}"
        entry = entries.setdefault(key, _entry(feature, name))
        _add_source(entry, "inspection_table")
        if feature and entry["status"] != "confirmed":
            entry["status"] = "probable"
        if name and name != entry["item"]:
            entry["item"] = name
        _merge_method(entry, str(item.get("method") or ""))
        sampling = entry["sampling"]
        if not sampling["quantity"]:
            sampling["quantity"] = _clean(item.get("quantity"))
        if not sampling["location"]:
            sampling["location"] = _clean(item.get("location"))
        note = _clean(item.get("note"))
        if note and note not in sampling["note"]:
            sampling["note"] = f"{sampling['note']}；{note}" if sampling["note"] else note
        evidence_id = f"ev-inspection-{index}"
        quote = "；".join(
            part
            for part in (
                name,
                _clean(item.get("quantity")),
                _clean(item.get("location")),
                _clean(item.get("method")),
                _clean(item.get("note")),
            )
            if part
        )
        _add_evidence(entry, evidence_id)
        evidence_sink.append(
            {
                "evidence_id": evidence_id,
                "table_id": "",
                "page_no": 0,
                "row_index": index - 1,
                "raw_row": [],
                "cells": {},
                "quote": quote[:400],
                "source": "inspection_table",
            }
        )


def _clause_entries(
    clauses: list[dict[str, Any]],
    entries: dict[str, dict[str, Any]],
    evidence_sink: list[dict[str, Any]],
) -> None:
    # Sub-clauses such as "6.1 热轧钢棒的尺寸…" inherit the item family from
    # their parent heading ("6 尺寸、外形、重量").
    titles = {
        str(clause.get("clause_id") or ""): _clean(clause.get("title"))
        for clause in clauses
    }
    top_kinds: dict[str, str] = {}
    for clause in clauses:
        clause_id = str(clause.get("clause_id") or "")
        top = clause_id.split(".")[0].split("-")[0]
        if top:
            top_kinds.setdefault(top, str(clause.get("kind") or ""))
    method_sections = {
        top
        for top in top_kinds
        if top_kinds.get(top) == "test_method"
        or any(
            marker in titles.get(top, "").lower()
            for marker in ("试验方法", "检验方法", "test method", "test methods")
        )
    }
    # 4.3/6 等方法章节也可能挂在“4 质量保证规定”“6 技术要求”下面，
    # 需要按子条款前缀识别，而不只看顶层章节。
    method_prefixes = {
        str(clause.get("clause_id") or "")
        for clause in clauses
        if str(clause.get("kind") or "") == "test_method"
        or any(
            marker in _clean(clause.get("title")).lower()
            for marker in ("试验方法", "检验方法", "test method", "test methods")
        )
    }
    rule_sections = {
        top
        for top in top_kinds
        if any(
            marker in titles.get(top, "")
            for marker in ("检验规则", "验收规则", "复验规则", "质量保证")
        )
    }
    rule_prefixes = {
        str(clause.get("clause_id") or "")
        for clause in clauses
        if any(
            marker in _clean(clause.get("title"))
            for marker in (
                "检验规则",
                "验收规则",
                "复验",
                "判定规则",
                "质量保证",
                "报告",
            )
        )
    }

    def under_method(clause_id: str) -> bool:
        return any(
            clause_id == prefix or clause_id.startswith(f"{prefix}.")
            for prefix in method_prefixes
        )

    def under_rule(clause_id: str) -> bool:
        return any(
            clause_id == prefix or clause_id.startswith(f"{prefix}.")
            for prefix in rule_prefixes
        )
    prefixes = _technical_prefixes(clauses)
    plans: list[dict[str, Any]] = []
    seen_plans: set[tuple[str, str]] = set()

    def add_plan(
        clause: dict[str, Any],
        feature: str,
        requirement: str,
        *,
        item: str = "",
        priority: int = 1,
        append: bool = False,
    ) -> None:
        clause_id = str(clause.get("clause_id") or "")
        key = (clause_id, feature)
        if not feature or key in seen_plans:
            return
        seen_plans.add(key)
        plans.append(
            {
                "clause": clause,
                "feature": feature,
                "requirement": requirement,
                "item": item or feature,
                "priority": priority,
                "append": append,
            }
        )

    for clause in clauses:
        kind = str(clause.get("kind") or "")
        if kind in SKIP_CLAUSE_KINDS:
            continue
        fields = clause.get("fields") or {}
        requirement = _clean((fields.get("requirement") or {}).get("raw"))
        title = _clean(clause.get("title"))
        clause_id = str(clause.get("clause_id") or "")
        if not requirement and not title and not _clean(clause.get("text")):
            continue
        body_text = _clean(clause.get("text"))
        probe = f"{title} {body_text}".strip()
        top = clause_id.split(".")[0].split("-")[0]
        blocked_section = (
            top_kinds.get(top)
            in {"delivery", "packaging", "normative_reference", "scope"}
            or top in rule_sections
            or under_rule(clause_id)
            or any(
                marker in titles.get(top, "").lower()
                for marker in (
                    "术语",
                    "定义",
                    "terminology",
                    "definitions",
                    "foreword",
                    "introduction",
                    "前言",
                    "引言",
                )
            )
            or any(
                marker in title.lower()
                for marker in ("术语", "定义", "terminology", "definitions")
            )
        )
        # 第 6 章“试验方法”只写怎么做；把方法句当验收要求会覆盖第 5 章的真实要求
        # （例如 6.5“外观质量用目视检测”顶掉 5.5“表面应清洁、无氧化色”）。
        if (top in method_sections or under_method(clause_id)) and kind != "technical_requirement":
            continue
        classification = "分类" in title
        title_feature = feature_from_text(title)
        inherited = ""
        context_title = title
        if not title_feature and "." in clause_id:
            parts = clause_id.split(".")
            for depth in range(len(parts) - 1, 0, -1):
                parent_title = titles.get(".".join(parts[:depth]), "")
                if not context_title:
                    context_title = parent_title
                inherited = feature_from_text(parent_title)
                if inherited:
                    break
        primary = title_feature or inherited
        # 父标题只是分组（“3.7 高倍组织”）而子条款正文明确写了“晶粒度”
        # “非金属夹杂物”时，以正文点名的项目为准，避免把子项都塞进父类。
        list_items = _list_items(body_text)
        explicit = [
            name
            for name in features_from_text(f"{body_text} {requirement}")
            if name in QUALITATIVE_SET
            and _weak_feature_ok(name, f"{body_text} {requirement}")
        ]
        extra_qualitative: list[str] = []
        if not title_feature and explicit and not list_items:
            primary = explicit[0]
            extra_qualitative = [
                name for name in dict.fromkeys(explicit[1:]) if name != primary
            ]
        if primary and not (blocked_section or classification):
            # Only keep a requirement that actually names the item, or a
            # substantive English requirement ("Shall conform to...").
            # Lead-ins such as "Shall be as follows" let the child clause
            # fill the text.
            # 标题就是检验项目的短条款（“3.8 超声波检验”），整段都是该项目的
            # 要求；只取第一句会丢掉“验收标准应符合锻件图样”等后半句。
            sentence = ""
            if (
                title_feature
                and body_text
                and len(body_text) <= 400
                and re.match(
                    r"^(?:按|根据|需方|产品|板材|丝材|钢管|锻件|钢|合金|应|不得|不应"
                    r"|不允许|表面|外形|尺寸|晶粒|显微|非金属|超声|涡流"
                    r"|除|对|对于|在|当|凡|所有|每"
                    r"|The|All|Product|Material|Microstructure|Grain)",
                    body_text,
                )
            ):
                # 标题已限定项目，整段正文都属于该项目（如 9.1 同时含显微组织
                # 和晶粒度两句），只取第一句会漏掉后半段验收指标。
                sentence = body_text
            if not sentence:
                sentence = _feature_sentence(
                    f"{body_text} {requirement}".strip(), primary
                )
            lowered = requirement.lower()
            if not sentence:
                if (
                    title_feature
                    and len(requirement) >= 20
                    and re.search(r"\b(?:shall|should|must)\b", lowered)
                    and not lowered.startswith(
                        ("shall be as follows", "shall be as specified")
                    )
                ):
                    sentence = requirement
                elif inherited and re.search(
                    r"in accordance with|according to|\bperform\b|\bdetermine\b",
                    requirement,
                    re.I,
                ):
                    sentence = requirement
                elif (
                    inherited
                    and len(requirement) >= 20
                    and re.search(r"\b(?:shall|should|must)\b", lowered)
                    and _weak_feature_ok(primary, requirement)
                ):
                    sentence = requirement
                elif (
                    inherited
                    and len(requirement) >= 12
                    and re.search(
                        r"应|不得|不应|不允许|不小于|不大于|不超过|可按|可进行|可对|可提供",
                        requirement,
                    )
                    and _weak_feature_ok(primary, requirement)
                ):
                    # 中文子条款（3.10.1“锻件的非加工表面上不应有……”）通常
                    # 不带关键词以外的项目名，靠父标题继承项目。
                    sentence = requirement
                elif (
                    inherited
                    and len(body_text) >= 12
                    and re.search(
                        r"应|不得|不应|不允许|不小于|不大于|不超过|可按|可进行|可对|可提供",
                        body_text,
                    )
                    and _weak_feature_ok(primary, body_text)
                ):
                    # 子条款没有独立的 requirement 字段时，用正文。
                    sentence = body_text[:240]
                elif (
                    title_feature
                    and len(requirement) >= 12
                    and not METHOD_ONLY_RE.search(requirement)
                    and _weak_feature_ok(primary, requirement)
                ):
                    sentence = requirement
            # 项目名可以由父标题继承，但正文句子必须自身成立：
            # “表面不应有……夹杂物”不能因为父标题是“外观质量”就变成夹杂物要求。
            if sentence and not _weak_feature_ok(primary, sentence):
                sentence = ""
            # “晶粒度评级方法按GB/T 6394 的规定执行”只提供试验方法，
            # 不能覆盖技术要求里的验收指标。
            if sentence and METHOD_ONLY_RE.search(sentence) and not ACCEPTANCE_RE.search(
                sentence
            ):
                sentence = ""
            add_plan(
                clause,
                primary,
                sentence,
                priority=0 if title_feature else 1,
                append=bool(title_feature),
            )
            # 同一句明确点名多个项目（“非金属夹杂物和晶间腐蚀试验”）。
            for extra in extra_qualitative:
                extra_sentence = (
                    _feature_sentence(
                        f"{body_text} {requirement}".strip(), extra
                    )
                    or requirement
                )
                if (
                    extra_sentence
                    and METHOD_ONLY_RE.search(extra_sentence)
                    and not ACCEPTANCE_RE.search(extra_sentence)
                ):
                    extra_sentence = ""
                # “最大外廓尺寸”只是顺带提到尺寸，不是尺寸公差要求。
                if extra == "尺寸" and not re.search(
                    r"公差|偏差|允许偏差|外形|厚度|壁厚|外径|长度|宽度|不平度|弯曲度",
                    extra_sentence,
                ):
                    continue
                if extra_sentence and _weak_feature_ok(extra, extra_sentence):
                    add_plan(clause, extra, extra_sentence)
        elif requirement and not (blocked_section or classification):
            requirement_feature = feature_from_text(requirement)
            # Qualitative items are only credible inside a technical-requirement
            # section or under a qualitative heading; a passing mention in
            # 订货内容 ("尺寸、外形") is not an inspection item.
            if requirement_feature == "尺寸":
                if _weak_feature_ok("尺寸", requirement):
                    add_plan(clause, requirement_feature, requirement, append=True)
            elif requirement_feature and requirement_feature not in QUALITATIVE_SET:
                add_plan(clause, requirement_feature, requirement, append=True)

        body_allowed = (
            not (blocked_section or classification)
            and (
                primary in QUALITATIVE_SET
                or _under_prefix(clause_id, prefixes)
                or any(
                    marker in context_title.lower()
                    for marker in (
                        "要求",
                        "性能",
                        "组织",
                        "试验",
                        "检验",
                        "检测",
                        "质量",
                        "properties",
                        "requirements",
                        "quality",
                        "inspection",
                        "testing",
                        "tests",
                    )
                )
            )
        )
        if body_allowed:
            # 主项目已经是金相/外观等定性项目时，同一句里顺带出现的其他金相词
            # 多半是缺陷举例（“低倍上应无非金属夹杂”“显微组织中δ-铁素体”），
            # 不再重复生成第二张金相记录。
            secondary = (
                [] if primary in QUALITATIVE_SET else features_from_text(probe)
            )
            for feature in secondary:
                if feature not in QUALITATIVE_SET or feature == primary:
                    continue
                # Bare 厚度/外径 words are too weak to prove a dimension item
                # outside an appearance/dimension clause.
                if feature == "尺寸" and not (
                    primary in QUALITATIVE_SET
                    or any(marker in title for marker in ("尺寸", "外形", "厚度", "表面"))
                ):
                    continue
                sentence = _feature_sentence(body_text, feature)
                # A bare list item ("b) 非金属夹杂物") is handled below with
                # the parent requirement as its text.
                if re.search(r"(?:[a-zA-Z]\)|[（(]\d+[）)])", sentence):
                    continue
                if sentence and _weak_feature_ok(feature, sentence):
                    add_plan(clause, feature, sentence)
            sentences = _sentences(body_text)
            lead = requirement or (sentences[0] if sentences else "")
            for item in _list_items(body_text):
                feature = feature_from_text(item)
                if feature not in QUALITATIVE_SET or feature == primary:
                    continue
                # “c) 规定的显微组织”“f) 无损检测的要求”只是特殊要求清单的
                # 占位项，没有可验收的具体指标。
                if GENERIC_LIST_ITEM_RE.search(item):
                    continue
                text = lead
                if item and item not in lead:
                    text = f"{lead} {item}".strip()
                if _weak_feature_ok(feature, text or item):
                    add_plan(clause, feature, text, item=item)

    plans.sort(key=lambda plan: plan["priority"])
    for plan in plans:
        clause = plan["clause"]
        feature = plan["feature"]
        requirement = plan["requirement"]
        fields = clause.get("fields") or {}
        entry = entries.setdefault(feature, _entry(feature, plan["item"]))
        _add_source(entry, "clause")
        if entry["status"] != "confirmed":
            entry["status"] = "probable"
        clause_id = str(clause.get("clause_id") or "")
        if clause_id:
            entry["clause_id"] = entry["clause_id"] or clause_id
            if clause_id not in entry["clause_ids"]:
                entry["clause_ids"].append(clause_id)
        if not entry["page_no"]:
            entry["page_no"] = int(clause.get("page_no") or 0)
        if requirement:
            known = {
                str(item.get("text") or "") for item in entry["requirements"]
            }
            if requirement not in known:
                entry["requirements"].append(
                    {
                        "text": requirement,
                        "clause_id": clause_id,
                        "item": plan["item"],
                        "page_no": int(clause.get("page_no") or 0),
                        "method": _clean(
                            (fields.get("method_standard") or {}).get("raw")
                        ),
                        "sampling": {
                            "quantity": _clean(
                                (fields.get("sample_quantity") or {}).get("raw")
                            ),
                            "location": _clean(
                                (fields.get("sample_location") or {}).get("raw")
                            ),
                            "note": "",
                        },
                    }
                )
            if not entry["requirement"]:
                entry["requirement"] = requirement
            elif (
                plan["append"]
                and requirement not in entry["requirement"]
                and len(entry["requirement"]) < 500
            ):
                entry["requirement"] = f"{entry['requirement']}；{requirement}"[:600]
        method = _clean((fields.get("method_standard") or {}).get("raw"))
        _merge_method(entry, method)
        sampling = entry["sampling"]
        if not sampling["quantity"]:
            sampling["quantity"] = _clean((fields.get("sample_quantity") or {}).get("raw"))
        if not sampling["location"]:
            sampling["location"] = _clean((fields.get("sample_location") or {}).get("raw"))
        for evidence in clause.get("evidence") or []:
            _add_evidence(entry, str(evidence.get("evidence_id") or ""))
        evidence_id = f"ev-clause-{clause_id}"
        if requirement and not any(
            str(item.get("evidence_id") or "") == evidence_id
            for item in evidence_sink
        ):
            evidence_sink.append(
                {
                    "evidence_id": evidence_id,
                    "table_id": "",
                    "page_no": int(clause.get("page_no") or 0),
                    "row_index": 0,
                    "raw_row": [],
                    "cells": {},
                    "quote": requirement[:400],
                    "source": "clause",
                }
            )


TABLE_BLOCK_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
FOOTNOTE_RE = re.compile(r"^(?:[A-Z]|注\s*\d*|NOTE\s*\d*)\s*[:：.]?\s+")


def _footnote_entries(
    ocr: dict[str, Any],
    entries: dict[str, dict[str, Any]],
    evidence_sink: list[dict[str, Any]],
) -> None:
    """Read table footnotes: ASTM prints real requirements after the table."""
    for page in ocr.get("pages") or []:
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("page_no") or 0)
        text = TABLE_BLOCK_RE.sub("\n", str(page.get("markdown") or ""))
        for index, raw in enumerate(re.split(r"\n\s*\n", text), start=1):
            paragraph = _clean(raw)
            if len(paragraph) < 20 or not FOOTNOTE_RE.match(paragraph):
                continue
            if not any(
                marker in paragraph.lower()
                for marker in ("shall", "should", "must", "应", "不得", "不应", "不允许")
            ):
                continue
            text_body = FOOTNOTE_RE.sub("", paragraph)
            for feature in features_from_text(text_body):
                if feature not in QUALITATIVE_SET:
                    continue
                sentence = _feature_sentence(text_body, feature) or text_body
                if not _weak_feature_ok(feature, sentence):
                    continue
                entry = entries.setdefault(feature, _entry(feature, feature))
                _add_source(entry, "prose")
                if entry["status"] != "confirmed":
                    entry["status"] = "probable"
                if not entry["requirement"]:
                    entry["requirement"] = sentence
                if not entry["page_no"]:
                    entry["page_no"] = page_no
                evidence_id = f"ev-footnote-{page_no}-{index}"
                _add_evidence(entry, evidence_id)
                if not any(
                    str(item.get("evidence_id") or "") == evidence_id
                    for item in evidence_sink
                ):
                    evidence_sink.append(
                        {
                            "evidence_id": evidence_id,
                            "table_id": "",
                            "page_no": page_no,
                            "row_index": index - 1,
                            "raw_row": [],
                            "cells": {},
                            "quote": sentence[:400],
                            "source": "prose",
                        }
                    )


def build_inventory(
    records: list[dict[str, Any]],
    clauses_payload: dict[str, Any],
    inspections: list[dict[str, str]],
    ocr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge records, inspection rows and clauses into the item inventory."""
    entries: dict[str, dict[str, Any]] = {}
    evidence_sink: list[dict[str, Any]] = []
    record_features = _record_entries(records, entries)
    _inspection_entries(inspections, entries, evidence_sink)
    _clause_entries(clauses_payload.get("clauses") or [], entries, evidence_sink)
    if ocr:
        _footnote_entries(ocr, entries, evidence_sink)

    items: list[dict[str, Any]] = []
    for entry in entries.values():
        if entry["conflicts"] and entry["status"] != "confirmed":
            entry["status"] = "ambiguous"
        if not entry["sources"]:
            entry["status"] = "new"
        items.append(entry)
    items.sort(
        key=lambda item: (
            0 if item["status"] == "confirmed" else 1,
            str(item["feature"] or item["item"]),
        )
    )
    for index, entry in enumerate(items, start=1):
        entry["inventory_id"] = f"inv-{index:03d}"

    inventory_features = {
        str(entry["feature"]) for entry in items if entry.get("feature")
    }
    aligned = sorted(record_features & inventory_features)
    coverage = {
        "record_features": sorted(record_features),
        "inventory_features": sorted(inventory_features),
        "aligned": aligned,
        "aligned_ratio": round(
            len(aligned) / len(record_features), 4
        )
        if record_features
        else 0.0,
        "confirmed": sum(1 for entry in items if entry["status"] == "confirmed"),
        "probable": sum(1 for entry in items if entry["status"] == "probable"),
        "ambiguous": sum(1 for entry in items if entry["status"] == "ambiguous"),
        "clause_only": sum(
            1
            for entry in items
            if entry["status"] == "probable"
            and "clause" in entry["sources"]
            and "property_table" not in entry["sources"]
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "coverage": coverage,
        "evidence": evidence_sink,
    }


def _column(headers: list[str], markers: tuple[str, ...]) -> int | None:
    for index, header in enumerate(headers):
        if any(marker in header for marker in markers):
            return index
    return None


def extract_classifications(ocr: dict[str, Any]) -> list[dict[str, Any]]:
    """Read grade/state and grade crosswalk tables (non-record tables).

    These tables describe the material designation system rather than a test
    item, so they never become records; they are reported as classifications in
    ``document_intelligence.json`` with the originating table/row.
    """
    items: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for table in ocr.get("tables") or []:
        headers = _flatten_headers(table)
        if not headers:
            continue
        grade_col = _column(headers, ("牌号", "钢号", "grade"))
        if grade_col is None:
            continue
        state_col = _column(headers, ("状态",))
        meaning_col = _column(headers, ("含义", "代号", "说明"))
        crosswalk = any(
            marker in header
            for header in headers
            for marker in (
                "对照",
                "国外",
                "相应",
                "近似",
                "ASTM",
                "JIS",
                "ISO",
                "DIN",
                "UNS",
                "ASME",
            )
        )
        if state_col is None and not crosswalk:
            continue
        if state_col is not None and meaning_col is None and not crosswalk:
            continue
        header_rows = int(table.get("header_rows") or 1)
        table_id = str(table.get("table_id") or "")
        page_no = int(table.get("page_no") or 0)
        for row_index, row in enumerate((table.get("rows") or [])[header_rows:]):
            if not isinstance(row, list) or grade_col >= len(row):
                continue
            if _is_footnote_row(row):
                continue
            grade = _clean(row[grade_col])
            if not grade or grade in {"牌号", "钢号", "grade"}:
                continue
            if state_col is not None:
                state = _clean(row[state_col]) if state_col < len(row) else ""
                meaning = (
                    _clean(row[meaning_col])
                    if meaning_col is not None and meaning_col < len(row)
                    else ""
                )
                if not state and not meaning:
                    continue
                key = ("grade_state", grade, state, meaning)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "kind": "grade_state",
                        "grade": grade,
                        "state": state,
                        "meaning": meaning,
                        "crosswalk": {},
                        "table_id": table_id,
                        "page_no": page_no,
                        "row_index": row_index,
                        "evidence_id": f"ev-class-{table_id}-{row_index}",
                        "quote": "；".join(
                            part for part in (grade, state, meaning) if part
                        )[:240],
                    }
                )
                continue
            pairs = {
                headers[index]: _clean(row[index])
                for index in range(min(len(headers), len(row)))
                if index != grade_col and _clean(row[index])
            }
            if not pairs:
                continue
            key = ("grade_crosswalk", grade, tuple(sorted(pairs.items())))
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "kind": "grade_crosswalk",
                    "grade": grade,
                    "state": "",
                    "meaning": "",
                    "crosswalk": pairs,
                    "table_id": table_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "evidence_id": f"ev-class-{table_id}-{row_index}",
                    "quote": "；".join(
                        [grade, *(f"{key}:{value}" for key, value in pairs.items())]
                    )[:240],
                }
            )
    return items
