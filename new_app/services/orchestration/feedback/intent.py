"""Deterministic intent resolution for vague user feedback.

Turns a one-line complaint ("室温拉伸抽取效果不好") into a structured intent:
assertion category, scope and candidate targets.  The matching algorithm holds
no business vocabulary: concepts come from the versioned dictionary, so new
wording is a dictionary change rather than a code change.
"""

from __future__ import annotations

from typing import Any

from .concepts import Concept, ConceptDictionary, load_dictionary
from .measures import normalize
from .outline import build_outline

# (category, verdict, keywords) — checked in order; first hit wins.
CATEGORY_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("wrong_unit", "wrong", ("单位",)),
    ("duplicate", "extra", ("重复",)),
    (
        "missing_value",
        "missing",
        (
            "没有抽取", "没抽取", "未抽取", "没有提取", "没提取", "未提取",
            "未解析", "没解析", "漏", "缺失", "缺少", "抽不出", "没有",
        ),
    ),
    (
        "wrong_requirement",
        "wrong",
        (
            "要求", "上下限", "指标", "范围", "不小于", "不大于",
            "大于", "小于", ">=", "<=", "≥", "≤",
        ),
    ),
    (
        "wrong_value",
        "wrong",
        ("不对", "不正确", "错误", "有误", "不符", "错了", "偏差", "不准"),
    ),
    ("unspecified", "ambiguous", ("效果不好", "效果差", "质量差", "不好", "不理想", "有问题")),
)

FIELD_CATEGORIES = {"wrong_value", "wrong_requirement", "wrong_unit"}

# 用户描述里的字段维度。长词在前，避免“取样数量”被“取样”抢先。
FIELD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "试验方法",
        (
            "试验方法", "检验方法", "检测方法", "试验标准", "方法标准",
            "测试方法", "test method", "testing method",
        ),
    ),
    ("取样数量", ("取样数量", "抽样数量", "取样数")),
    ("取样位置", ("取样位置", "取样部位")),
    (
        "取样说明",
        ("取样说明", "取样规定", "取样要求", "取样", "采样", "抽样"),
    ),
    (
        "标准要求",
        ("标准要求", "要求值", "上下限", "限值", "指标", "要求", "范围"),
    ),
    ("单位", ("单位",)),
    ("材料牌号", ("材料牌号", "牌号", "钢号")),
    ("方向", ("方向",)),
    ("试验温度", ("试验温度", "温度")),
    ("尺寸厚度", ("尺寸厚度", "厚度", "规格")),
    ("项目名称", ("项目名称", "检验项目", "项目")),
)
METHOD_FIELDS = {"试验方法", "取样", "取样数量", "取样位置", "取样说明"}


def _detect_field(text: str, category: str) -> tuple[str, str]:
    """Return (field, matched keyword) from the user's complaint.

    The field matters for routing: "试验方法缺失" is a document-level rule
    problem, while "标准要求不正确" points at the value/requirement columns.
    """
    for field, keywords in FIELD_RULES:
        for keyword in keywords:
            if normalize(keyword) in text:
                return field, keyword
    if category == "missing_value":
        return "项目名称", ""
    if category in FIELD_CATEGORIES:
        return "标准要求", ""
    return "", ""



def _classify(text: str) -> tuple[str, str]:
    for category, verdict, keywords in CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category, verdict
    return "other", "ambiguous"


def _clause_concept(text: str, dictionary: ConceptDictionary) -> Concept | None:
    for concept in dictionary.by_kind("clause"):
        if any(normalize(term) in text for term in concept.terms()):
            return concept
    return None


def _subject_name(text: str, dictionary: ConceptDictionary, concept: Concept | None) -> str:
    """报告subject时优先业务对象：'化学成分试验方法' -> 化学成分，而不是试验方法。"""
    if concept is None or concept.section_kind != "clause":
        return concept.name if concept else ""
    best_name = concept.name
    best_length = 0
    for candidate in dictionary.concepts:
        if candidate.section_kind == "clause":
            continue
        for term in candidate.terms():
            token = normalize(term)
            if token and token in text and len(token) > best_length:
                best_name, best_length = candidate.name, len(token)
    return best_name


def _signals(
    entry: dict[str, Any], concept: Concept
) -> tuple[int, list[str], list[str], list[str]]:
    """Score an outline entry; return (score, signals, measures, condition_hits)."""
    haystack = normalize(" ".join([str(entry.get("caption") or ""), *entry["headers"]]))
    score = 0
    signals: list[str] = []
    alias_hit = [alias for alias in concept.aliases if normalize(alias) in haystack]
    parent_hit = [parent for parent in concept.parents if normalize(parent) in haystack]
    matched = sorted(set(entry["measures"]) & set(concept.measures))
    condition_hit = [
        condition for condition in concept.conditions if normalize(condition) in haystack
    ]
    anti_hit = [
        condition
        for condition in concept.anti_conditions
        if normalize(condition) in haystack
    ]
    if alias_hit:
        score += 3
        signals.append(f"表题/表头命中「{alias_hit[0]}」")
    elif parent_hit:
        score += 2
        signals.append(f"上下位概念命中「{parent_hit[0]}」")
    if matched:
        score += 2 * len(matched)
        signals.append("列语义命中 " + "/".join(matched))
    if entry.get("section_kind") and entry["section_kind"] == concept.section_kind:
        score += 2
        signals.append(f"章节类型命中 {entry['section_kind']}")
    if condition_hit:
        score += 2
        signals.append(f"条件命中「{condition_hit[0]}」")
    if anti_hit:
        score -= 3
        signals.append(f"条件冲突「{anti_hit[0]}」")
    return score, signals, matched, condition_hit


def _confidence(score: int) -> float:
    return round(min(0.95, max(0.2, 0.35 + 0.04 * score)), 2)


def resolve_intent(
    utterance: str,
    tables: list[dict[str, Any]],
    records: list[dict[str, Any]] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    target: dict[str, Any] | None = None,
    *,
    dictionary: ConceptDictionary | None = None,
    outline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve free-form feedback into category/scope/candidate targets."""
    records = records or []
    diagnostics = diagnostics or []
    target = target or {}
    dictionary = dictionary or load_dictionary()
    outline = outline if outline is not None else build_outline(tables, records, diagnostics)
    text = normalize(utterance)
    category, verdict = _classify(text)
    field, field_term = _detect_field(text, category)
    method_field = field in METHOD_FIELDS

    concept = _clause_concept(text, dictionary)
    matched_term = ""
    if concept is None:
        match = dictionary.match(text)
        if match is not None:
            concept, matched_term = match

    property_hits: list[str] = []
    candidates: list[dict[str, Any]] = []
    if concept is not None and concept.section_kind != "clause":
        wanted = {normalize(measure) for measure in concept.measures}
        for record in records:
            for name in (record.get("properties") or {}):
                if normalize(name) in wanted and name not in property_hits:
                    property_hits.append(name)

        scored: list[tuple[int, int, int, int, dict[str, Any], list[str], list[str]]] = []
        for entry in outline:
            score, signals, matched, condition_hit = _signals(entry, concept)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    len(condition_hit),
                    int(entry.get("records") or 0),
                    -int(entry.get("page_no") or 0),
                    entry,
                    signals,
                    matched,
                )
            )
        scored.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3]))
        for score, _, _, _, entry, signals, matched in scored[:5]:
            candidates.append(
                {
                    "table_id": entry["table_id"],
                    "page_no": entry["page_no"],
                    "record_ids": [],
                    "property": property_hits[0] if property_hits else None,
                    "reason": "；".join(signals) or "表型匹配",
                    "measures_matched": matched,
                    "confidence": _confidence(score),
                    "records": int(entry.get("records") or 0),
                }
            )

    clause = concept is not None and concept.section_kind == "clause"
    subject = _subject_name(text, dictionary, concept)
    if clause or method_field:
        scope = "clause"
    elif property_hits and category in FIELD_CATEGORIES:
        scope = "field"
    elif candidates:
        scope = "table"
    else:
        scope = "document"

    if scope in {"table", "field"} and candidates:
        confidence = candidates[0]["confidence"]
    elif scope == "field":
        confidence = 0.8
    elif scope == "clause":
        confidence = 0.75
    else:
        confidence = 0.2

    assumption = ""
    if scope == "document":
        assumption = "未定位到具体表，按整篇文档核对"
    elif scope == "table" and candidates:
        top = candidates[0]
        assumption = f"按表 {top['table_id']}（第 {top['page_no']} 页）整表核对"
    elif scope == "field":
        assumption = f"按字段 {'/'.join(property_hits[:4])} 核对"
    elif scope == "clause":
        if method_field:
            assumption = "按文档级试验方法/取样绑定核对，不修改数据表"
        else:
            assumption = "按试验方法/检验规则条款核对，不修改数据表"

    clarification = _build_clarification(scope, candidates, confidence)
    clarifying = clarification["question"] if clarification else None
    evidence: list[dict[str, Any]] = []
    if candidates:
        evidence.append(
            {
                "page_no": candidates[0]["page_no"],
                "table_id": candidates[0]["table_id"],
                "quote": _caption(outline, candidates[0]["table_id"]) or "",
            }
        )

    return {
        "concept_id": concept.concept_id if concept else "",
        "concept": concept.name if concept else "",
        "subject": subject,
        "field": field,
        "field_term": field_term,
        "method_field": method_field,
        "missing_project": field == "项目名称" and category == "missing_value",
        "measures": property_hits
        or (list(concept.measures) if concept is not None else []),
        "matched_term": matched_term,
        "dictionary_version": dictionary.version,
        "category": category,
        "verdict": verdict,
        "scope": scope,
        "interpretation": (
            f"用户认为{subject or '抽取结果'}存在问题（{category}）"
        ),
        "candidate_targets": candidates,
        "properties": property_hits,
        "assumption": assumption,
        "clarifying_question": clarifying,
        "clarification": clarification,
        "evidence": evidence,
        "confidence": confidence,
    }


def _caption(outline: list[dict[str, Any]], table_id: str) -> str | None:
    for entry in outline:
        if entry.get("table_id") == table_id:
            return entry.get("caption")
    return None


def _build_clarification(
    scope: str,
    candidates: list[dict[str, Any]],
    confidence: float,
) -> dict[str, Any] | None:
    """One question with options when table choice is genuinely ambiguous."""
    if scope != "table" or not candidates:
        return None
    top = candidates[0]
    if len(candidates) >= 2:
        second = candidates[1]
        gap = float(top.get("confidence") or 0) - float(second.get("confidence") or 0)
        tied = gap <= 0.05 or (
            int(top.get("records") or 0) == int(second.get("records") or 0)
            and int(top.get("page_no") or 0) != int(second.get("page_no") or 0)
        )
        if tied:
            options = [
                {
                    "table_id": str(item.get("table_id") or ""),
                    "page_no": int(item.get("page_no") or 0),
                    "label": (
                        f"{item.get('table_id')}（第 {item.get('page_no')} 页，"
                        f"{item.get('reason') or '表型匹配'}）"
                    ),
                }
                for item in candidates[:3]
            ]
            options.append(
                {"table_id": "", "page_no": 0, "label": "都不是，请补充说明"}
            )
            letters = "ABCD"
            rendered = "；".join(
                f"{letters[index]}. {option['label']}"
                for index, option in enumerate(options)
            )
            return {
                "reason": "tie",
                "question": f"你指的是哪张表？{rendered}",
                "options": options,
            }
    if confidence < 0.5:
        return {
            "reason": "low_confidence",
            "question": (
                f"你指的是表 {top.get('table_id')}（第 {top.get('page_no')} 页）吗？"
                "A. 是；B. 不是，请补充说明"
            ),
            "options": [
                {
                    "table_id": str(top.get("table_id") or ""),
                    "page_no": int(top.get("page_no") or 0),
                    "label": "是",
                },
                {"table_id": "", "page_no": 0, "label": "不是，请补充说明"},
            ],
        }
    return None


def needs_clarification(intent: dict[str, Any]) -> bool:
    """Ask only when the model rerank did not resolve the ambiguity."""
    if (intent.get("rerank") or {}).get("applied"):
        return False
    return bool(intent.get("clarification"))


def needs_rerank(intent: dict[str, Any]) -> bool:
    """True when rule scoring leaves two table candidates effectively tied."""
    if str(intent.get("scope") or "") != "table":
        return False
    candidates = list(intent.get("candidate_targets") or [])
    if len(candidates) < 2:
        return False
    first, second = candidates[0], candidates[1]
    gap = float(first.get("confidence") or 0) - float(second.get("confidence") or 0)
    if gap <= 0.05:
        return True
    return (
        int(first.get("records") or 0) == int(second.get("records") or 0)
        and int(first.get("page_no") or 0) != int(second.get("page_no") or 0)
    )


def apply_rerank(intent: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """Move the model-chosen candidate to the front; keep rule output on failure."""
    result = dict(intent)
    table_id = str(output.get("table_id") or "")
    if not output.get("model_used") or not table_id:
        result["rerank"] = {
            "applied": False,
            "reason": str(output.get("reason") or "模型未给出可用选择"),
        }
        return result
    candidates = list(intent.get("candidate_targets") or [])
    chosen = next(
        (item for item in candidates if str(item.get("table_id") or "") == table_id),
        None,
    )
    if chosen is None:
        result["rerank"] = {
            "applied": False,
            "reason": "模型选择的 table_id 不在候选内",
        }
        return result
    result["candidate_targets"] = [chosen] + [
        item for item in candidates if item is not chosen
    ]
    result["confidence"] = max(
        float(intent.get("confidence") or 0),
        float(output.get("confidence") or 0),
    )
    result["assumption"] = (
        f"按表 {table_id}（第 {chosen.get('page_no')} 页）整表核对（模型重排）"
    )
    result["clarifying_question"] = None
    result["clarification"] = None
    result["rerank"] = {
        "applied": True,
        "table_id": table_id,
        "reason": str(output.get("reason") or ""),
        "confidence": float(output.get("confidence") or 0),
    }
    evidence = list(intent.get("evidence") or [])
    if not any(str(item.get("table_id") or "") == table_id for item in evidence):
        evidence.insert(
            0,
            {
                "page_no": chosen.get("page_no"),
                "table_id": table_id,
                "quote": _caption_for(intent, table_id),
            },
        )
    result["evidence"] = evidence
    return result


def _caption_for(intent: dict[str, Any], table_id: str) -> str:
    for item in intent.get("candidate_targets") or []:
        if str(item.get("table_id") or "") == table_id:
            reason = str(item.get("reason") or "")
            return reason.split("；")[0] if reason else ""
    return ""
