"""Understand arbitrary user feedback before choosing a repair action.

The locator is deterministic-first; this module adds a model triage step so
feedback does not have to name a record. The model may decide the problem is
about one field, one table/inspection item, a clause, or the whole document.
When it cannot decide, it must say what extra detail is needed instead of
rejecting the feedback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..contracts import DocumentResult
from ..tablegrid.normalize import clean_text
from .contracts import FeedbackTarget
from .locator import expected_from_text, locate_target
from .planner import _parse_json

AUDIT_SCOPES = {"table", "document", "clause"}
TRIAGE_TEMPLATE = """你是金属材料文档抽取反馈的分析器。用户可能指出某个字段错误、整张表或某个检验项目有问题、条款问题，或整篇文档有问题。
请判断反馈的范围、涉及对象和下一步动作。只输出 JSON：
{"scope":"field|table|document|clause|unknown","record_id":"可选","table_id":"可选","property":"可选","clause_id":"可选","expected":"可选","action":"reparse|audit|need_more_info","reason":"判断依据","need_info":"action=need_more_info 时具体要用户补充什么"}
规则：
- 能明确到字段或记录：scope=field，action=reparse
- 描述整张表或某个检验项目（如“室温拉伸大部分内容有问题”）：scope=table，action=audit
- 描述整篇、格式、版式：scope=document，action=audit
- 描述某条款：scope=clause，action=audit
- 不能判断：scope=unknown，action=need_more_info，并给出具体补充项
- 只能使用下面给出的 ID，不能编造
文档：{document}
表：{tables}
记录：{records}
条款：{clauses}
检验项目：{inspections}
规则定位提示：{hint}
反馈类别：{category}
反馈描述：{description}
原文引文：{source_quote}
期望值：{expected}
"""


@dataclass
class FeedbackAnalysis:
    scope: str
    target: FeedbackTarget
    expected: str | None
    action: str
    reason: str = ""
    need_info: str | None = None

    @property
    def rule_code(self) -> str:
        return {
            "field": "user_feedback",
            "table": "user_feedback_table",
            "document": "user_feedback_document",
            "clause": "user_feedback_clause",
        }.get(self.scope, "user_feedback")


def analyze_feedback(
    result: DocumentResult,
    description: str,
    source_quote: str = "",
    *,
    category: str = "other",
    expected_value: str | None = None,
    model_url: str | None = None,
    model_name: str = "",
    timeout: float = 60.0,
) -> FeedbackAnalysis:
    """Return the scope and next action for one feedback item."""

    hint = locate_target(result, description, source_quote, model_url=None)
    if model_url:
        analysis = _model_analysis(
            result,
            description,
            source_quote,
            category=category,
            expected_value=expected_value,
            hint=hint,
            model_url=model_url,
            model_name=model_name,
            timeout=timeout,
        )
        if analysis is not None:
            if (
                analysis.scope == "table"
                and not analysis.target.feature
                and hint is not None
                and hint.target.table_id == analysis.target.table_id
            ):
                analysis.target = analysis.target.model_copy(
                    update={"feature": hint.target.feature}
                )
            return analysis
    return _rule_analysis(
        result,
        description,
        source_quote,
        category=category,
        model_available=bool(model_url),
    )


def _rule_analysis(
    result: DocumentResult,
    description: str,
    source_quote: str,
    *,
    category: str,
    model_available: bool,
) -> FeedbackAnalysis:
    located = locate_target(result, description, source_quote, model_url=None)
    if located is not None:
        target = located.target
        if target.record_id:
            return FeedbackAnalysis(
                "field", target, located.expected, "reparse", "规则定位到记录"
            )
        if target.table_id:
            return FeedbackAnalysis(
                "table",
                target,
                located.expected,
                "audit",
                "规则定位到表/检验项目",
            )
    if category == "other" and clean_text(description):
        return FeedbackAnalysis(
            "document",
            FeedbackTarget(feature="整篇"),
            expected_from_text(clean_text(description)),
            "audit" if model_available else "need_more_info",
            "其他类反馈按整篇处理",
            None if model_available else "请补充具体元素/字段、表号或原文数值",
        )
    return FeedbackAnalysis(
        "unknown",
        FeedbackTarget(),
        None,
        "need_more_info",
        "规则无法定位",
        "请补充元素/字段名、表号、原文数值或期望值，或说明是哪张表/哪个检验项目有问题",
    )


def _model_analysis(
    result: DocumentResult,
    description: str,
    source_quote: str,
    *,
    category: str,
    expected_value: str | None,
    hint,
    model_url: str,
    model_name: str,
    timeout: float,
) -> FeedbackAnalysis | None:
    prompt = (
        TRIAGE_TEMPLATE.replace("{document}", _document_context(result))
        .replace("{tables}", _tables_context(result))
        .replace("{records}", _records_context(result))
        .replace("{clauses}", _clauses_context(result))
        .replace("{inspections}", _inspections_context(result))
        .replace("{hint}", _hint_context(hint))
        .replace("{category}", category)
        .replace("{description}", description or "")
        .replace("{source_quote}", source_quote or "")
        .replace("{expected}", expected_value or "")
    )
    try:
        import httpx

        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post(
                f"{model_url.rstrip('/')}/chat/completions",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "只输出 JSON，不要解释。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 512,
                    "response_format": {"type": "json_object"},
                    "stream": False,
                },
            )
            response.raise_for_status()
        payload = _parse_json(response.json()["choices"][0]["message"]["content"])
    except Exception:  # noqa: BLE001 - triage is best effort
        return None
    return _analysis_from_payload(
        result, payload, description, expected_value=expected_value
    )


def _analysis_from_payload(
    result: DocumentResult,
    payload: dict,
    description: str,
    *,
    expected_value: str | None,
) -> FeedbackAnalysis | None:
    scope = str(payload.get("scope") or "").lower()
    action = str(payload.get("action") or "").lower()
    expected = (
        str(payload.get("expected") or "").strip()
        or expected_value
        or expected_from_text(clean_text(description))
    )
    need_info = str(payload.get("need_info") or "").strip() or None
    reason = str(payload.get("reason") or "").strip()

    if action == "need_more_info" or scope == "unknown":
        return FeedbackAnalysis(
            "unknown",
            FeedbackTarget(),
            expected,
            "need_more_info",
            reason or "模型无法判断范围",
            need_info
            or "请补充元素/字段名、表号、原文数值或期望值，或说明是哪张表/哪个检验项目有问题",
        )

    record_id = str(payload.get("record_id") or "")
    property_name = str(payload.get("property") or "").strip()
    table_id = str(payload.get("table_id") or "")
    clause_id = str(payload.get("clause_id") or "")

    record = next(
        (item for item in result.records if item.record_id == record_id), None
    )
    if record is not None and scope == "field":
        if property_name and property_name not in record.properties:
            property_name = ""
        return FeedbackAnalysis(
            "field",
            FeedbackTarget(
                record_id=record.record_id,
                property=property_name or None,
                table_id=record.source_table_id or None,
                grade=record.grade or None,
                condition=record.condition or None,
            ),
            expected,
            "reparse",
            reason,
        )

    table = next(
        (item for item in result.tables if item.table_id == table_id), None
    )
    if table is not None and scope in AUDIT_SCOPES:
        return FeedbackAnalysis(
            "table",
            FeedbackTarget(
                table_id=table.table_id,
                feature=str(payload.get("feature") or "").strip() or None,
            ),
            expected,
            "audit",
            reason,
        )

    if scope == "document":
        return FeedbackAnalysis(
            "document",
            FeedbackTarget(feature="整篇"),
            expected,
            "audit",
            reason,
        )

    clause = next(
        (item for item in result.clauses if item.clause_id == clause_id), None
    )
    if clause is not None and scope == "clause":
        return FeedbackAnalysis(
            "clause",
            FeedbackTarget(feature=f"条款 {clause.clause_id}"),
            expected,
            "audit",
            reason,
        )
    return None


def _hint_context(hint) -> str:
    if hint is None:
        return "无"
    return json.dumps(
        {
            "record_id": hint.target.record_id,
            "table_id": hint.target.table_id,
            "property": hint.target.property,
            "expected": hint.expected,
        },
        ensure_ascii=False,
    )


def _document_context(result: DocumentResult) -> str:
    return json.dumps(
        {
            "title": result.document.title,
            "standard_no": result.document.standard_no,
            "page_count": result.document.page_count,
        },
        ensure_ascii=False,
    )


def _tables_context(result: DocumentResult) -> str:
    counts = {
        table.table_id: sum(
            1 for record in result.records if record.source_table_id == table.table_id
        )
        for table in result.tables
    }
    return json.dumps(
        [
            {
                "table_id": table.table_id,
                "caption": table.caption,
                "profile": table.profile,
                "records": counts.get(table.table_id, 0),
                "header": [
                    " ".join(part for part in path if part)
                    for path in table.header_paths[:6]
                ],
            }
            for table in result.tables
        ],
        ensure_ascii=False,
    )


def _records_context(result: DocumentResult, limit: int = 60) -> str:
    rows = []
    for record in result.records[:limit]:
        rows.append(
            {
                "record_id": record.record_id,
                "table_id": record.source_table_id,
                "grade": record.grade or record.grade_level,
                "condition": record.condition,
                "properties": {
                    name: value.raw or value.text
                    for name, value in record.properties.items()
                },
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def _clauses_context(result: DocumentResult, limit: int = 30) -> str:
    return json.dumps(
        [
            {"clause_id": clause.clause_id, "title": clause.title}
            for clause in result.clauses[:limit]
        ],
        ensure_ascii=False,
    )


def _inspections_context(result: DocumentResult, limit: int = 30) -> str:
    return json.dumps(
        [{"item": item.item} for item in result.inspection_items[:limit]],
        ensure_ascii=False,
    )
