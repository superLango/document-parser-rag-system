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
            "表面",
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
    return re.sub(r"\s+", " ", _normalize_doc_text(value)).strip(" ，,、;；")


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


def _weak_feature_ok(feature: str, sentence: str) -> bool:
    """Reject incidental mentions of a keyword (cleaning vs. NDT, duplex steel)."""
    lowered = _clean(sentence).lower()
    if feature == "低倍" and "grain flow" in lowered:
        return "forging" in lowered and (
            "contour" in lowered or "follow" in lowered
        )
    if feature == "铁素体":
        return any(
            keyword in lowered
            for keyword in (
                "α相",
                "α phase",
                "铁素体含量",
                "ferrite content",
                "ferrite phase",
                "alpha phase",
            )
        )
    if feature == "超声波检测":
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
    if feature == "外观":
        return bool(
            re.search(
                r"不应|不得|不允许|应|质量|洁净|缺陷|clean|free of|defect"
                r"|workmanship|appearance|uniform in quality|quality and condition"
                r"|alpha case|surface (?:quality|condition|finish)",
                lowered,
            )
        )
    if feature == "尺寸":
        return bool(
            re.search(
                r"尺寸|外形|厚度|壁厚|外径|dimension|tolerance|size|thickness|diameter",
                lowered,
            )
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
    pattern = re.compile(r"(?<=[。；;])|(?<=[.!?])\s+")
    return [part.strip() for part in pattern.split(_clean(text)) if part.strip()]


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
        blocked_section = top_kinds.get(top) in {"delivery", "packaging"}
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
        if primary and not (blocked_section or classification):
            # Only keep a requirement that actually names the item, or a
            # substantive English requirement ("Shall conform to...").
            # Lead-ins such as "Shall be as follows" let the child clause
            # fill the text.
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
            if not (
                _weak_feature_ok(primary, sentence)
                or _weak_feature_ok(primary, title or context_title)
            ):
                sentence = ""
            add_plan(
                clause,
                primary,
                sentence,
                priority=0 if title_feature else 1,
                append=bool(title_feature),
            )
        elif requirement:
            requirement_feature = feature_from_text(requirement)
            # Qualitative items are only credible inside a technical-requirement
            # section or under a qualitative heading; a passing mention in
            # 订货内容 ("尺寸、外形") is not an inspection item.
            if requirement_feature and requirement_feature not in QUALITATIVE_SET:
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
            for feature in features_from_text(probe):
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
                if feature in QUALITATIVE_SET and feature != primary:
                    if _weak_feature_ok(feature, lead or item):
                        add_plan(clause, feature, lead, item=item)

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
        if requirement and not entry["requirement"]:
            entry["requirement"] = requirement
        elif (
            requirement
            and plan["append"]
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
