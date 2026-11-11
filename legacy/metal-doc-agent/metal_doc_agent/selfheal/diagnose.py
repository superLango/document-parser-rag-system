"""Diagnose a feedback as an agent: mechanism, source-grounded correction, action."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import DocumentResult
from ..tablegrid.normalize import clean_text
from .config import SelfHealSettings
from .contracts import FeedbackTarget
from .evidence import GENERIC_TOKENS, build_evidence_pack, keyword_tokens
from .locate import load_trace
from .planner import _parse_json
from .resolve import Correction, resolve_correction

ROOT_CAUSES = {
    "ocr",
    "layout",
    "table_structure",
    "header_mapping",
    "value_parsing",
    "extraction_rule",
    "schema_dictionary",
    "document_meta",
    "source_absent",
    "pipeline_code",
    "unknown",
}
ACTIONS = {
    "reparse",
    "table_repair",
    "rule_fix",
    "code_patch",
    "document_meta",
    "report_only",
}
SCOPES = {
    "field",
    "table",
    "clause",
    "document",
    "missing_item",
    "missing_field",
    "document_meta",
}
METADATA_WORDS = ("标准编号", "标准号", "文件编号", "标准代号", "标准名称", "标题")
MISSING_WORDS = (
    "没有解析出来",
    "没解析出来",
    "未解析",
    "未提取",
    "没提取",
    "没有提取",
    "漏了",
    "漏项",
    "缺失",
    "缺少",
)
DIAGNOSE_TEMPLATE = """你是金属材料标准解析的诊断智能体。给定一次用户反馈和引擎产物证据，必须判断：
1) 错在哪个环节（root_cause）；2) 具体机制（mechanism）；3) 第一处偏离（first_divergence）；
4) 应改哪条规则（rule_change），而不是把本次答案写死；5) 从原文找到正确内容（expected）；
6) 下一步动作（action）。只输出 JSON：
{"root_cause":"ocr|layout|table_structure|header_mapping|value_parsing|extraction_rule|schema_dictionary|document_meta|source_absent|pipeline_code|unknown",
 "scope":"field|table|clause|document|missing_item|missing_field|document_meta",
 "action":"reparse|table_repair|rule_fix|code_patch|document_meta|report_only",
 "record_id":"可选","table_id":"可选","property":"可选","feature":"可选",
 "expected":"可选，只能取自证据中出现的原文",
 "mechanism":"错误发生的机制","first_divergence":"第一处与原文不一致的位置",
 "rule_change":{"rule_id":"规则标识","before":"当前逻辑","after":"应改成什么通用逻辑"},
 "reason":"判断依据","evidence":[{"page_no":1,"table_id":"","quote":"原文"}],
 "checks":["已核对的内容"],"code_hint":{"file":"","function":"","why":""},
 "confidence":0.0}
硬约束：
- 不允许把用户反馈里的具体值、牌号、标准号当作代码常量写死；
- expected 必须能在证据原文中找到，找不到就留空；
- 不要要求用户补充信息，除非描述为空；找不到就说明查过什么、缺在哪一层；
- 只能使用证据中出现的 ID，不能编造。
证据包：{pack}
规则定位提示：{hint}
已求得的正解候选：{correction}
反馈类别：{category}
反馈描述：{description}
原文引文：{source_quote}
用户期望值：{expected_value}
"""


@dataclass
class Diagnosis:
    root_cause: str
    scope: str
    action: str
    target: FeedbackTarget = field(default_factory=FeedbackTarget)
    expected: str | None = None
    mechanism: str = ""
    first_divergence: str = ""
    rule_change: dict[str, Any] | None = None
    reason: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    code_hint: dict[str, Any] | None = None
    confidence: float = 0.5
    model: bool = False
    correction: Correction | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "scope": self.scope,
            "action": self.action,
            "target": self.target.model_dump(mode="json"),
            "expected": self.expected,
            "mechanism": self.mechanism,
            "first_divergence": self.first_divergence,
            "rule_change": self.rule_change,
            "reason": self.reason,
            "evidence": self.evidence,
            "checks": self.checks,
            "code_hint": self.code_hint,
            "confidence": self.confidence,
            "model": self.model,
            "correction": self.correction.to_dict() if self.correction else None,
        }


def diagnose(
    settings: SelfHealSettings,
    result: DocumentResult,
    job_dir: str | Path | None,
    *,
    description: str,
    category: str = "other",
    target: FeedbackTarget | None = None,
    expected: str | None = None,
    source_quote: str = "",
) -> Diagnosis:
    target = target or FeedbackTarget()
    trace = load_trace(job_dir) if job_dir else {}
    pack = build_evidence_pack(
        result,
        job_dir,
        description=description,
        source_quote=source_quote,
        target=target,
        expected=expected,
        trace=trace,
    )
    correction = resolve_correction(
        result,
        job_dir,
        description=description,
        target=target,
        expected=expected,
        category=category,
    )
    hint = _feature_hint(result, description, settings)
    diagnosis = None
    if settings.model_base_url:
        diagnosis = _model_diagnosis(
            settings,
            pack,
            hint,
            correction,
            description=description,
            category=category,
            source_quote=source_quote,
            expected=expected,
        )
    if diagnosis is None:
        diagnosis = _rule_diagnosis(
            result,
            correction,
            hint,
            description=description,
            target=target,
            expected=expected,
            category=category,
        )
    diagnosis.correction = correction
    _merge_evidence(diagnosis, pack, correction)
    _prepend_table_evidence(diagnosis, result)
    if diagnosis.expected and correction.found and correction.value:
        diagnosis.expected = correction.value
    if not diagnosis.expected and correction.found and correction.value:
        diagnosis.expected = correction.value
    if not diagnosis.target.feature and hint:
        diagnosis.target = diagnosis.target.model_copy(update={"feature": hint})
    return diagnosis


def _feature_hint(
    result: DocumentResult, description: str, settings: SelfHealSettings
) -> str | None:
    text = clean_text(description)
    if not text:
        return None
    tokens = [
        token
        for token in keyword_tokens(description)
        if token not in GENERIC_TOKENS and len(token) >= 2
    ]
    candidates: list[tuple[str, int]] = []
    try:
        from ..schema_projection import load_dictionary_index

        index = load_dictionary_index(settings.project_root)
    except Exception:  # noqa: BLE001 - dictionary is optional for diagnosis
        index = None
    if index is not None:
        for entry in index.dictionary.entries:
            if entry.type != "item" or entry.status != "active":
                continue
            candidates.append((entry.business_name, 0))
            for alias in entry.aliases:
                candidates.append((alias, 0))
    candidates.extend((item.item, 1) for item in result.inspection_items)
    candidates.extend((table.caption or "", 2) for table in result.tables)

    best: tuple[int, int, str] | None = None
    for name, priority in candidates:
        cleaned = clean_text(name)
        if not cleaned:
            continue
        if cleaned in text:
            score = 100 + len(cleaned)
        else:
            matches = [token for token in tokens if token in cleaned]
            if not matches:
                continue
            score = max(len(token) for token in matches)
        key = (score, -priority)
        if best is None or key > (best[0], best[1]):
            best = (score, -priority, name)
    return best[2] if best is not None else None


def _model_diagnosis(
    settings: SelfHealSettings,
    pack: dict[str, Any],
    hint: str | None,
    correction: Correction,
    *,
    description: str,
    category: str,
    source_quote: str,
    expected: str | None,
) -> Diagnosis | None:
    prompt = (
        DIAGNOSE_TEMPLATE.replace(
            "{pack}", json.dumps(pack, ensure_ascii=False, default=str)
        )
        .replace("{hint}", hint or "无")
        .replace(
            "{correction}",
            json.dumps(correction.to_dict(), ensure_ascii=False, default=str),
        )
        .replace("{category}", category)
        .replace("{description}", description or "")
        .replace("{source_quote}", source_quote or "")
        .replace("{expected_value}", expected or "")
    )
    try:
        import httpx

        with httpx.Client(timeout=settings.model_timeout, trust_env=False) as client:
            response = client.post(
                f"{settings.model_base_url.rstrip('/')}/chat/completions",
                json={
                    "model": settings.model_name,
                    "messages": [
                        {"role": "system", "content": "只输出 JSON，不要解释。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 1600,
                    "response_format": {"type": "json_object"},
                    "stream": False,
                },
            )
            response.raise_for_status()
        payload = _parse_json(response.json()["choices"][0]["message"]["content"])
    except Exception:  # noqa: BLE001 - diagnosis falls back to rules
        return None
    return _payload_to_diagnosis(payload, pack, correction)


def _payload_to_diagnosis(
    payload: dict[str, Any], pack: dict[str, Any], correction: Correction
) -> Diagnosis:
    root_cause = str(payload.get("root_cause") or "unknown").lower()
    if root_cause not in ROOT_CAUSES:
        root_cause = "unknown"
    scope = str(payload.get("scope") or "unknown").lower()
    if scope not in SCOPES:
        scope = "document" if root_cause != "unknown" else "document"
    action = str(payload.get("action") or "").lower()
    if action not in ACTIONS:
        action = _action_for(root_cause, scope)

    target = FeedbackTarget(
        record_id=str(payload.get("record_id") or "").strip() or None,
        table_id=str(payload.get("table_id") or "").strip() or None,
        property=str(payload.get("property") or "").strip() or None,
        feature=str(payload.get("feature") or "").strip() or None,
    )
    if target.table_id and not any(
        table["table_id"] == target.table_id for table in pack.get("tables", [])
    ):
        target.table_id = None
    if target.record_id and not any(
        record["record_id"] == target.record_id for record in pack.get("records", [])
    ):
        target.record_id = None

    evidence = []
    for item in payload.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        if not quote:
            continue
        evidence.append(
            {
                "page_no": item.get("page_no"),
                "table_id": item.get("table_id"),
                "row": item.get("row"),
                "col": item.get("col"),
                "quote": quote[:300],
            }
        )
    checks = [str(item) for item in payload.get("checks") or [] if str(item).strip()]
    expected = str(payload.get("expected") or "").strip() or None
    if expected and not _text_in_pack(expected, pack):
        expected = None
    rule_change = payload.get("rule_change")
    if not isinstance(rule_change, dict):
        rule_change = None
    code_hint = payload.get("code_hint")
    if not isinstance(code_hint, dict):
        code_hint = None
    return Diagnosis(
        root_cause=root_cause,
        scope=scope,
        action=action,
        target=target,
        expected=expected,
        mechanism=str(payload.get("mechanism") or "").strip(),
        first_divergence=str(payload.get("first_divergence") or "").strip(),
        rule_change=rule_change,
        reason=str(payload.get("reason") or "").strip(),
        evidence=evidence,
        checks=checks,
        code_hint=code_hint,
        confidence=_confidence(payload.get("confidence")),
        model=True,
        correction=correction,
    )


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, number))


def _text_in_pack(text: str, pack: dict[str, Any]) -> bool:
    needle = re.sub(r"\s+", "", text)
    if not needle:
        return False
    haystack = json.dumps(pack, ensure_ascii=False, default=str)
    return needle in re.sub(r"\s+", "", haystack)


def _is_missing(text: str, category: str) -> bool:
    if category == "missing_value":
        return True
    if any(word in text for word in MISSING_WORDS):
        return True
    if any(word in text for word in ("缺失", "缺少", "漏了", "漏项")):
        return True
    if "出来" in text and any(word in text for word in ("没有", "没", "未")):
        return True
    return False


def _action_for(root_cause: str, scope: str) -> str:
    if root_cause == "document_meta" or scope == "document_meta":
        return "document_meta"
    if root_cause in {"table_structure", "header_mapping"}:
        return "table_repair"
    if root_cause in {"extraction_rule", "schema_dictionary", "value_parsing"}:
        return "rule_fix"
    if root_cause == "pipeline_code":
        return "code_patch"
    if root_cause in {"source_absent", "unknown"}:
        return "report_only"
    return "reparse"


def _rule_diagnosis(
    result: DocumentResult,
    correction: Correction,
    hint: str | None,
    *,
    description: str,
    target: FeedbackTarget,
    expected: str | None,
    category: str = "other",
) -> Diagnosis:
    text = clean_text(description)
    tokens = keyword_tokens(description)
    missing = _is_missing(text, category)

    if any(word in text for word in METADATA_WORDS):
        return Diagnosis(
            root_cause="document_meta",
            scope="document_meta",
            action="document_meta",
            target=FeedbackTarget(feature=correction.field or "standard_no"),
            expected=correction.value or expected,
            mechanism="标准编号/标题取自首页文本，当前解析值与封面不一致",
            first_divergence="document.standard_no 与首页原文不一致"
            if correction.found
            else "",
            rule_change={
                "rule_id": "ingest.cover_standard_no",
                "before": "仅从文件名解析标准编号",
                "after": "优先从首页页眉/封面解析，文件名兜底",
            },
            reason=correction.reason or "反馈指向文档元数据",
            evidence=correction.evidence,
            checks=correction.checked,
            confidence=0.8 if correction.found else 0.55,
        )

    if missing:
        missing_field = bool(target.property) or any(
            token in text for token in ("数量", "单位", "要求")
        )
        scope = "missing_field" if missing_field else "missing_item"
        table_id = target.table_id or _table_for_feature(result, hint or "")
        return Diagnosis(
            root_cause="extraction_rule",
            scope=scope,
            action="reparse",
            target=target.model_copy(
                update={
                    "feature": hint or target.feature,
                    "table_id": table_id,
                }
            ),
            expected=expected,
            mechanism=(
                "该内容在原文/表头存在，但未被抽取到结果中"
                if correction.found
                else "当前抽取链路未覆盖该内容"
            ),
            first_divergence=correction.reason,
            rule_change={
                "rule_id": "extraction.missing_content",
                "before": "只抽取已识别的表格列/项目",
                "after": "补充该字段/项目的识别与绑定规则",
            },
            reason=correction.reason or "反馈描述为内容缺失",
            evidence=correction.evidence,
            checks=correction.checked,
            confidence=0.7 if correction.found else 0.45,
        )

    table_id = target.table_id
    if not table_id and hint:
        table_id = _table_for_feature(result, hint)
    if table_id:
        return Diagnosis(
            root_cause="table_structure",
            scope="table",
            action="table_repair",
            target=FeedbackTarget(table_id=table_id, feature=hint or target.feature),
            expected=correction.value or expected,
            mechanism="表头/行结构与原文不一致，导致该表内容解析错误",
            first_divergence=correction.reason,
            rule_change={
                "rule_id": "tablegrid.header_and_rows",
                "before": "按当前表头与行结构解析",
                "after": "按原文表头层级与合并关系修正通用识别规则",
            },
            reason=correction.reason or "反馈指向整张表",
            evidence=correction.evidence,
            checks=correction.checked,
            confidence=0.6,
        )

    return Diagnosis(
        root_cause="unknown",
        scope="document",
        action="reparse",
        target=FeedbackTarget(feature=hint or "整篇"),
        expected=correction.value or expected,
        mechanism="规则无法缩小到单表/单字段，按整篇重新解析并比对",
        first_divergence=correction.reason,
        reason=correction.reason or "按整篇处理",
        evidence=correction.evidence,
        checks=correction.checked,
        confidence=0.4,
    )


def _table_for_feature(result: DocumentResult, feature: str) -> str | None:
    cleaned = clean_text(feature)
    if not cleaned:
        return None
    counts: list[tuple[int, str]] = []
    for table in result.tables:
        haystack = clean_text(
            " ".join([table.caption or ""] + [" ".join(path) for path in table.header_paths])
        )
        if cleaned in haystack:
            counts.append(
                (
                    sum(
                        1
                        for record in result.records
                        if record.source_table_id == table.table_id
                    ),
                    table.table_id,
                )
            )
    if not counts:
        if any(
            keyword in cleaned
            for keyword in ("拉伸", "力学", "强度", "屈服", "延伸", "收缩")
        ):
            counts = [
                (
                    sum(
                        1
                        for record in result.records
                        if record.source_table_id == table.table_id
                    ),
                    table.table_id,
                )
                for table in result.tables
                if table.profile == "mechanical_properties"
            ]
    if not counts:
        return None
    counts.sort(reverse=True)
    return counts[0][1]


def _merge_evidence(
    diagnosis: Diagnosis, pack: dict[str, Any], correction: Correction
) -> None:
    if correction.evidence:
        diagnosis.evidence = _unique_evidence(
            correction.evidence + diagnosis.evidence
        )
    if diagnosis.scope == "document_meta":
        first_page = [
            {
                "page_no": page.get("page_no"),
                "quote": str(page.get("excerpt") or "")[:300],
            }
            for page in pack.get("page_excerpts") or []
            if page.get("reason") == "首页（标准编号/标题核对）"
        ]
        diagnosis.evidence = _unique_evidence(first_page + diagnosis.evidence)
    if not diagnosis.evidence:
        diagnosis.evidence = list(pack.get("evidence_quotes") or [])
    if not diagnosis.evidence:
        for page in pack.get("page_excerpts") or []:
            quote = str(page.get("excerpt") or "")[:300]
            if quote:
                diagnosis.evidence.append(
                    {"page_no": page.get("page_no"), "quote": quote}
                )
            if len(diagnosis.evidence) >= 3:
                break
    for item in pack.get("checks") or []:
        if item not in diagnosis.checks:
            diagnosis.checks.append(item)
    for item in correction.checked:
        if item not in diagnosis.checks:
            diagnosis.checks.append(item)


def _prepend_table_evidence(
    diagnosis: Diagnosis, result: DocumentResult
) -> None:
    table_id = diagnosis.target.table_id
    if not table_id or diagnosis.scope not in {"table", "missing_field", "missing_item"}:
        return
    table = next(
        (item for item in result.tables if item.table_id == table_id), None
    )
    if table is None:
        return
    header = " | ".join(
        " ".join(part for part in path if part) for path in table.header_paths[:6]
    )
    quote = f"{table.caption or ''} {header}".strip()
    if not quote:
        return
    diagnosis.evidence = _unique_evidence(
        [
            {
                "page_no": table.page_no,
                "table_id": table.table_id,
                "quote": quote[:300],
            }
        ]
        + diagnosis.evidence
    )


def _unique_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (
            item.get("page_no"),
            item.get("table_id"),
            item.get("row"),
            item.get("col"),
            str(item.get("quote"))[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result[:8]
